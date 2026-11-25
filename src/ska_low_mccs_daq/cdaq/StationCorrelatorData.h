//
// Station beam correlator consumer. It correlates the substation beams of one station.
// Each substation is a TCC receiver and each frequency channel is a TCC channel.
//

#ifndef AAVS_DAQ_STATION_CORRELATOR_DATA_H
#define AAVS_DAQ_STATION_CORRELATOR_DATA_H

#include <atomic>
#include <complex>
#include <cstdint>
#include <memory>
#include <vector>

#include "DAQ.h"

#include <cudawrappers/cu.hpp>
#include "libtcc/Correlator.h"
#include "multi_array.h"

// Maximum number of substation beams (station beamformer regions)
constexpr uint16_t STATION_CORRELATOR_MAX_SUBSTATIONS = 48;

// Samples in one CSP station beam packet
constexpr uint32_t STATION_CORRELATOR_SAMPLES_PER_PACKET = 2048;

// Polarisations in station beam data
constexpr uint8_t STATION_CORRELATOR_NOF_POLS = 2;

// Time samples in one TCC block for 8-bit input
constexpr uint32_t STATION_CORRELATOR_TIMES_PER_BLOCK = 16;

// Index of an empty buffer. A packet counter can be 0, so 0 is not used.
constexpr uint64_t STATION_CORRELATOR_EMPTY = UINT64_MAX;

// Metadata for each integration
struct StationCorrelatorMetadata
{
    double time_taken;     // Wall-clock time to process the integration (ms)
    double h2d_time;       // Host to device copy (ms)
    double kern_time;      // TCC kernel (ms)
    double d2h_time;       // Device to host copy (ms)
    uint64_t scan_id;      // SPEAD scan ID of the last packet in the integration
    uint32_t nof_samples;  // Mean samples received for each substation and channel
    uint32_t nof_packets;  // Packets in the integration
    uint16_t station_id;   // SPEAD station ID of the last packet in the integration
    uint16_t start_channel;    // Frequency ID of TCC channel 0
    uint16_t nof_channels;     // Number of TCC channels
    uint16_t nof_substations;  // Number of TCC receivers
    uint8_t substation_ids[STATION_CORRELATOR_MAX_SUBSTATIONS];  // Substation ID of each receiver
};

// -----------------------------------------------------------------------------

// Data for one integration
struct StationCorrelatorBuffer
{
    // Packet counter at the start of the window, or STATION_CORRELATOR_EMPTY if the
    // buffer is free. The GPU thread sets it last when it releases the buffer.
    std::atomic<uint64_t> index{STATION_CORRELATOR_EMPTY};
    std::atomic<bool> ready{false};  // The buffer is ready for correlation
    double ref_time = 0;             // Time of the earliest packet
    uint32_t nof_packets = 0;        // Packets written
    uint64_t scan_id = 0;            // Scan ID of the last packet
    uint16_t station_id = 0;         // Station ID of the last packet
    uint16_t *data = nullptr;        // Pinned host memory in TCC layout
};

// Buffers between the packet thread and the GPU thread. The window logic is
// from StationDoubleBuffer. The storage is from TccDoubleBuffer, with a channel
// dimension. The layout is [C][T/16][R][P][16] of complex 8-bit samples.
class StationCorrelatorDoubleBuffer
{
public:
    StationCorrelatorDoubleBuffer(uint16_t nof_substations, uint16_t nof_channels,
                           uint32_t nof_samples, uint8_t nbuffers = 4);

    // Write one packet for one substation and one channel
    void write_data(uint16_t substation, uint16_t channel, uint32_t samples,
                    uint64_t packet_counter, uint16_t *data_ptr, double timestamp,
                    uint64_t scan_id, uint16_t station_id);

    // Mark the open buffers as ready when the stream stops
    void finish_write();

    // Return the next ready buffer, or nullptr
    StationCorrelatorBuffer *read_buffer();

    // Clear the buffer from read_buffer and give it back to the producer
    void release_buffer();

    size_t buffer_bytes() const { return buffer_bytes_; }

private:
    // Copy one packet into a buffer in TCC layout
    void copy_data(int index, uint16_t substation, uint16_t channel,
                   uint64_t start_sample, uint32_t samples, uint16_t *data_ptr,
                   double timestamp, uint64_t scan_id, uint16_t station_id);

    std::vector<StationCorrelatorBuffer> buffers_;
    std::vector<std::unique_ptr<cu::HostMemory>> pinned_;

    uint16_t nof_substations;
    uint16_t nof_channels;
    uint32_t nof_samples;
    uint8_t nbuffers;
    size_t buffer_bytes_;

    // Producer and consumer indices. Only the owner thread changes each one.
    int producer = 0;
    int consumer = 0;

    // Used only by the producer. After the producer marks a buffer ready, it does
    // not touch the buffer until the GPU thread releases it.
    bool current_open = false;   // The current buffer is open
    bool previous_open = false;  // The previous buffer accepts late packets
    uint64_t current_start = 0;  // Window start of the current buffer

    // Take the buffer at `producer` for the window that starts at `start`
    void claim(uint64_t start);

    struct timespec tim{0, 1000}, tim2{};
};

// -----------------------------------------------------------------------------

// GPU thread. It copies each ready buffer to the GPU, correlates it and calls the callback.
class StationCrossCorrelator : public RealTimeThread
{
public:
    StationCrossCorrelator(uint16_t nof_substations, uint16_t nof_channels,
                         uint32_t nof_samples, uint8_t nbuffers = 4);
    ~StationCrossCorrelator() override;

    StationCorrelatorDoubleBuffer *double_buffer;
    void setCallback(DataCallbackDynamic cb) { callback = cb; }

    // Metadata values that are the same for each integration
    void setMetadataTemplate(const StationCorrelatorMetadata &m) { metadata_template_ = m; }

protected:
    void threadEntry() override;

private:
    using SampleT = std::complex<int8_t>;
    using VisT = std::complex<int32_t>;

    // CUDA objects must come first (context needs device)
    cu::Device device_;
    cu::Context context_;
    cu::Stream stream_;

    // Extents next (sizes used by buffers)
    multi_array::extent<5> samplesExt_;
    multi_array::extent<4> visExt_;

    // Host/device buffers (need extents)
    cu::HostMemory hostVis_;
    cu::DeviceMemory devSamples_;
    cu::DeviceMemory devVis_;

    std::unique_ptr<tcc::Correlator> correlator_;
    DataCallbackDynamic callback{nullptr};
    StationCorrelatorMetadata metadata_template_{};

    uint16_t nof_substations;
    uint16_t nof_channels;

    struct timespec tic{}, toc{};
};

// -----------------------------------------------------------------------------

// Consumer for CSP station beam packets
class StationCorrelatorData : public DataConsumer
{
public:
    void setCallback(DataCallbackDynamic callback) override;

    bool initialiseConsumer(json configuration) override;

protected:
    bool packetFilter(unsigned char *udp_packet) override;

    bool processPacket() override;

    void cleanUp() override;

private:
    StationCorrelatorDoubleBuffer *double_buffer = nullptr;
    StationCrossCorrelator *cross_correlator = nullptr;

    // TCC receiver index for each substation ID, -1 if not configured
    int16_t substation_slot[256];

    uint16_t nof_substations = 0;
    uint16_t start_channel = 0;  // Frequency ID of TCC channel 0
    uint16_t nof_channels = 0;
    uint32_t nof_samples = 0;    // Samples per integration
};

extern "C" DataConsumer *stationcorrelator();

#endif // AAVS_DAQ_STATION_CORRELATOR_DATA_H
