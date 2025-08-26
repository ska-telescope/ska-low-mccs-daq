//
// Created by Tom Moynihan on 22/08/2025.
//

#ifndef AAVS_DAQ_CORRELATOR_H
#define AAVS_DAQ_CORRELATOR_H

#include <cstdlib>
#include <unistd.h>
#include <fcntl.h>
#include <cstring>
#include <cmath>
#include <string>
#include <complex>

#include "DAQ.h"
#include "TccDoubleBuffer.h"

#include <cudawrappers/nvrtc.hpp>
#include "libtcc/Correlator.h"
#include "multi_array.h"

#define ELAPSED_MS(start, stop) \
    ((((int64_t)stop.tv_sec - start.tv_sec) * 1000 * 1000 * 1000 + (stop.tv_nsec - start.tv_nsec)) / 1e6)

struct CorrelatorMetadata
{
    uint channel_id;
    double time_taken;
    uint nof_samples;
    uint nof_packets;
};

// -----------------------------------------------------------------------------

// Class which implements the GPU cross-correlator
class TensorCrossCorrelator : public RealTimeThread
{
public:
    TensorCrossCorrelator(uint32_t nof_fine_channels,
                          uint16_t nof_antennas,
                          uint32_t nof_samples,
                          uint8_t nof_pols,
                          uint8_t nbuffers = 4);
    ~TensorCrossCorrelator() override;
    TccDoubleBuffer *double_buffer;
    void setCallback(DataCallbackDynamic cb) { callback = cb; }

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
    cu::HostMemory hostSamples_;
    cu::HostMemory hostVis_;
    cu::DeviceMemory devSamples_;
    cu::DeviceMemory devVis_;

    std::unique_ptr<tcc::Correlator> correlator_;
    DataCallbackDynamic callback{nullptr};

    // config
    uint32_t nof_channels;
    uint16_t nof_antennas;
    uint32_t nof_samples;
    uint8_t nof_pols;

    struct timespec tic{}, toc{};
};

// -----------------------------------------------------------------------------

// Class which will hold the channelised data for correlation
class TensorCorrelatorData : public DataConsumer
{
public:
    // Override setDataCallback
    void setCallback(DataCallbackDynamic callback) override;

    // Initialise consumer
    bool initialiseConsumer(json configuration) override;

protected:
    // Packet filtering function to be passed to network thread
    inline bool packetFilter(unsigned char *udp_packet) override;

    // Grab SPEAD packet from buffer and process
    bool processPacket() override;

    // Override cleanup method
    void cleanUp() override;

private:
    // Pointer to Double Buffer
    TccDoubleBuffer *double_buffer;

    // Pointer to CrossCorrelator;
    TensorCrossCorrelator *cross_correlator;

    // Reference packet counter
    size_t reference_counter = 0;
    uint32_t rollover_counter = 0;

    // Data setup
    uint16_t nof_antennas = 0; // Number of antennas per tile
    uint8_t nof_pols = 0;      // Number of polarisations
    uint16_t nof_tiles = 0;    // Number of tiles
    uint16_t nof_channels = 0; // Number of channels
    uint32_t nof_samples = 0;  // Number of time samples
};

// Expose class factory for birales
extern "C" DataConsumer *tensorcorrelator() { return new TensorCorrelatorData; }

#endif // AAVS_DAQ_CORRELATOR_H
