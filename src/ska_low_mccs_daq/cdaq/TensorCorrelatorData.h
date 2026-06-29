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
#include "TccSplitRing.h"

#include <cudawrappers/nvrtc.hpp>
#include "libtcc/Correlator.h"
#include "multi_array.h"

#define ELAPSED_MS(start, stop) \
    ((((int64_t)stop.tv_sec - start.tv_sec) * 1000 * 1000 * 1000 + (stop.tv_nsec - start.tv_nsec)) / 1e6)

struct TensorCorrelatorMetadata
{
    uint channel_id;
    double time_taken;
    double h2d_time;
    double kern_time;
    double d2h_time;
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
                          uint16_t nof_active_antennas,
                          uint16_t nof_splits = 1,
                          uint32_t ring_size  = 64);
    ~TensorCrossCorrelator() override;

    std::unique_ptr<TccSplitRing> split_ring;
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

    // nof_splits_ must precede samplesExt_ (init-list order = declaration order)
    uint16_t nof_splits_;

    // Extents next (sizes used by buffers)
    multi_array::extent<5> samplesExt_;
    multi_array::extent<4> visExt_;

    // Host/device buffers (need extents)
    cu::HostMemory hostVis_;
    cu::DeviceMemory devSamples_;
    cu::DeviceMemory devVis_;

    std::unique_ptr<tcc::Correlator> correlator_;
    DataCallbackDynamic callback{nullptr};

    // Streaming helpers
    void copy_tail(const uint8_t *host_base, size_t split_start, size_t from, size_t to);
    void try_stream_partial(uint64_t global_split, size_t &split_streamed);

    // config
    uint32_t nof_channels;
    uint16_t nof_antennas;
    uint32_t nof_samples;
    uint8_t nof_pols;

    // precomputed streaming constants
    size_t split_m_;
    size_t m_stride_bytes_;
    size_t batch_m_;
    // Tracks the integration number so mark_consumed() can form global split indices.
    uint64_t consumer_integ_{0};

    // One event per ring slot: fires when that slot's H2D copy is complete.
    // Used to defer release_slot() until the DMA engine has finished reading.
    std::unique_ptr<cu::Event[]> h2d_done_;

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
    TccSplitRing           *split_ring      = nullptr;
    std::unique_ptr<TensorCrossCorrelator> cross_correlator;

    // Absolute packet counter tracking for integration/split mapping
    size_t   reference_counter  = 0;
    uint32_t rollover_counter   = 0;
    uint32_t pkts_per_integ_    = 0; // nof_samples / samples_in_packet (set on first packet)
    uint32_t nof_splits_per_integ_ = 0; // (nof_samples / 16) / split_m_ (precomputed)

    // Channel-transition tracking. The SPEAD heap counter restarts per channel, so the
    // per-channel reference/rollover are reset on a channel change while global_split_base_
    // advances by the previous channel's integration count. This keeps global_split
    // monotonic and contiguous across channels (no false 2^24 rollover, no backward jump).
    int      last_channel_id_   = -1; // -1 until the first packet
    uint64_t global_split_base_ = 0;  // added to every global_split; bumped per channel
    uint32_t max_local_integ_   = 0;  // highest in-channel integ_idx seen this channel

    // Data setup
    uint16_t nof_antennas = 0;
    uint8_t  nof_pols     = 0;
    uint16_t nof_tiles    = 0;
    uint16_t nof_channels = 0;
    uint32_t nof_samples  = 0;
    uint32_t split_m_     = 0; // M-blocks per split (copy from correlator for processPacket)
};

// Expose class factory for birales
extern "C" DataConsumer *tensorcorrelator() { return new TensorCorrelatorData; }

#endif // AAVS_DAQ_CORRELATOR_H
