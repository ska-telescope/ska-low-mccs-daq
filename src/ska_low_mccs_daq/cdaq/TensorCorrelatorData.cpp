//
// Created by Tom Moynihan on 22/08/2025.
//

#include "TensorCorrelatorData.h"
#include "SPEAD.h"
#include "libtcc/Correlator.h"

// Initialise correlator data consumer
bool TensorCorrelatorData::initialiseConsumer(json configuration)
{
    cu::init();
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_antennas") &&
          key_in_json(configuration, "nof_channels") &&
          key_in_json(configuration, "nof_fine_channels") &&
          key_in_json(configuration, "nof_tiles") &&
          key_in_json(configuration, "nof_active_tiles") &&
          key_in_json(configuration, "nof_samples") &&
          key_in_json(configuration, "nof_pols") &&
          key_in_json(configuration, "max_packet_size")))
    {
        LOG(FATAL, "Missing configuration item for TensorCorrelatorData consumer. Requires "
                   "nof_antennas, nof_samples, nof_tiles, nof_active_tiles, nof_pols, nof_channels, "
                   "nof_fine_channels and max_packet_size");
        return false;
    }

    // Set local values
    this->nof_channels = configuration["nof_channels"];
    this->nof_tiles = configuration["nof_tiles"];
    this->nof_samples = configuration["nof_samples"];
    this->nof_antennas = configuration["nof_antennas"];
    this->nof_pols = configuration["nof_pols"];
    this->packet_size = configuration["max_packet_size"];
    uint32_t nof_fine_channels = configuration["nof_fine_channels"];
    uint16_t nof_active_tiles = configuration["nof_active_tiles"];
    uint8_t nof_splits = configuration.contains("nof_splits") ? (uint8_t)configuration["nof_splits"] : 1;

    if (nof_active_tiles > this->nof_tiles)
    {
        LOG(FATAL, "nof_active_tiles (%u) > nof_tiles (%u)", (unsigned)nof_active_tiles, (unsigned)this->nof_tiles);
        return false;
    }

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t)32768 * this->nof_tiles);

    // Create cross-correlator and start
    cross_correlator = new TensorCrossCorrelator(nof_fine_channels,
                                                 nof_tiles * nof_antennas, nof_samples, nof_pols,
                                                 nof_active_tiles * nof_antennas, nof_splits);

    double_buffer = cross_correlator->double_buffer;

    // Start cross-correlator
    cross_correlator->startThread();

    // All done
    return true;
}

// Cleanup function
void TensorCorrelatorData::cleanUp()
{
    // Stop cross correlator thread
    cross_correlator->stop();

    // Destroy instances
    delete cross_correlator;
}

// Set callback
void TensorCorrelatorData::setCallback(DataCallbackDynamic callback)
{
    this->cross_correlator->setCallback(callback);
}

// Packet filter
bool TensorCorrelatorData::packetFilter(unsigned char *udp_packet)
{
    // Unpack SPEAD Header (or try to)
    uint64_t hdr = SPEAD_HEADER(udp_packet);

    // Check that this is in fact a SPEAD packet and that the correct
    // version is being used
    if ((SPEAD_GET_MAGIC(hdr) != SPEAD_MAGIC) ||
        (SPEAD_GET_VERSION(hdr) != SPEAD_VERSION) ||
        (SPEAD_GET_ITEMSIZE(hdr) != SPEAD_ITEM_PTR_WIDTH) ||
        (SPEAD_GET_ADDRSIZE(hdr) != SPEAD_HEAP_ADDR_WIDTH))
        return false;

    // Check whether the SPEAD packet contains burst channel data
    uint64_t mode = SPEAD_ITEM_ADDR(SPEAD_ITEM(udp_packet, 5));
    return (mode == 0x4 || mode == 0x5 || mode == 0x7);
}

// Get and process packet
bool TensorCorrelatorData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer->pull_timeout(&packet, 1);

    // Check if the request timed out
    if (packet_size == SIZE_MAX)
    {
        // Request timed out, finish any pending writes
        double_buffer->finish_write();

        // Reset rollover counters
        rollover_counter = 0;
        reference_counter = 0;
        return false;
    }

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);

    uint32_t packet_index = 0;
    uint32_t packet_counter = 0;
    uint64_t payload_length = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint16_t start_channel_id = 0;
    uint16_t start_antenna_id = 0;
    uint16_t nof_included_channels = 0;
    uint16_t nof_included_antennas = 0;
    uint16_t tile_id = 0;
    uint16_t station_id = 0;
    uint8_t pol_id = 0;
    uint32_t payload_offset = 0;

    // Get the number of items and get a pointer to the packet payload
    auto nofitems = (unsigned short)SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nofitems * SPEAD_ITEMLEN;

    // Loop over items to extract values
    for (unsigned i = 1; i <= nofitems; i++)
    {
        uint64_t item = SPEAD_ITEM(packet, i);
        switch (SPEAD_ITEM_ID(item))
        {
        case 0x0001: // Heap counter
        {
            packet_counter = (uint32_t)(SPEAD_ITEM_ADDR(item) & 0xFFFFFF);     // 24-bits
            packet_index = (uint32_t)((SPEAD_ITEM_ADDR(item) >> 24) & 0xFFFF); // 16-bits
            break;
        }
        case 0x0004: // Payload length
        {
            payload_length = SPEAD_ITEM_ADDR(item);
            break;
        }
        case 0x1027: // Sync time
        {
            sync_time = SPEAD_ITEM_ADDR(item);
            break;
        }
        case 0x1600: // Timestamp
        {
            timestamp = SPEAD_ITEM_ADDR(item);
            break;
        }
        case 0x2002: // Antenna and Channel information
        {
            uint64_t val = SPEAD_ITEM_ADDR(item);
            start_channel_id = (uint16_t)((val >> 24) & 0xFFFF);
            nof_included_channels = (uint16_t)((val >> 16) & 0xFF);
            start_antenna_id = (uint16_t)((val >> 8) & 0xFF);
            nof_included_antennas = (uint16_t)(val & 0xFF);
            break;
        }
        case 0x2001: // Tile information
        {
            uint64_t val = SPEAD_ITEM_ADDR(item);
            station_id = (uint16_t)((val >> 16) & 0xFFFF);
            tile_id = (uint16_t)((val >> 32) & 0xFF);
            pol_id = (uint8_t)(val & 0xFF);
            break;
        }
        case 0x3300: // Payload offset
        {
            payload_offset = (uint32_t)SPEAD_ITEM_ADDR(item);
            break;
        }
        case 0x2004:
            break;
        default:
            LOG(INFO, "Unknown item %#010x (%d of %d)", SPEAD_ITEM_ID(item), i, nofitems);
        }
    }

    // TEMPORARY: Timestamp_scale maybe will disappear, so it's hardcoded for now
    double packet_time = sync_time + timestamp * 1.08e-6; // timestamp_scale;

    // Calculate number of samples in packet
    uint32_t samples_in_packet;

    samples_in_packet = (uint32_t)((payload_length - payload_offset) /
                                   (nof_included_antennas * nof_pols * nof_included_channels * sizeof(uint16_t)));

    // Check whether packet counter has rolled over
    if (packet_counter == 0 && pol_id == 0)
        rollover_counter += 1;

    // Multiply packet_counter by rollover counts
    packet_counter += rollover_counter << 24;

    // Update packet index
    if (reference_counter == 0)
        reference_counter = packet_counter;

    // Assigned correct packet index
    packet_index = static_cast<uint32_t>((packet_counter - reference_counter) % (this->nof_samples / samples_in_packet));

    if (this->nof_channels == 1)
        // Write packet data to double buffer
        double_buffer->write_data_single_channel(tile_id * nof_antennas + start_antenna_id,
                                                 nof_included_antennas, start_channel_id,
                                                 packet_index,
                                                 samples_in_packet,
                                                 (uint16_t *)(payload + payload_offset),
                                                 packet_time);

    else
        // We have processed the packet items, send data to packet counter
        double_buffer->write_data(tile_id * nof_antennas + start_antenna_id,
                                  nof_included_antennas, start_channel_id,
                                  packet_index,
                                  samples_in_packet,
                                  (uint16_t *)(payload + payload_offset),
                                  packet_time);

    // Ready from packet
    ring_buffer->pull_ready();

    // All done, return
    return true;
}

// ------------------------- CROSS CORRELATOR ----------------------------------

// Class constructor
TensorCrossCorrelator::TensorCrossCorrelator(uint32_t nof_fine_channels,
                                             uint16_t nof_antennas,
                                             uint32_t nof_samples,
                                             uint8_t nof_pols,
                                             uint16_t nof_active_antennas,
                                             uint8_t nof_splits,
                                             uint8_t nbuffers)
    : device_(0),
      context_(0, device_),
      stream_(),
      nof_splits_(nof_splits),
      samplesExt_(multi_array::extents[1][nof_samples / nof_splits / 16][nof_antennas][nof_pols][16]),
      visExt_(multi_array::extents[1][(nof_antennas * (nof_antennas + 1)) / 2][nof_pols][nof_pols]),
      hostVis_(sizeof(VisT) * visExt_.size, 0),
      devSamples_(sizeof(SampleT) * samplesExt_.size), devVis_(sizeof(VisT) * visExt_.size),
      nof_channels(nof_fine_channels),
      nof_antennas(nof_antennas),
      nof_samples(nof_samples),
      nof_pols(nof_pols)
{
    context_.setCurrent();

    double_buffer = new TccDoubleBuffer(nof_antennas, nof_samples, nof_pols, nof_active_antennas, nbuffers);

    constexpr tcc::Format fmt = tcc::Format::i8;
    const uint32_t samples_per_split = nof_samples / nof_splits;
    if (nof_samples % nof_splits != 0)
        LOG(FATAL, "nof_samples (%u) must be divisible by nof_splits (%u)", nof_samples, (unsigned)nof_splits);
    if (samples_per_split % 16 != 0)
        LOG(FATAL, "nof_samples/nof_splits (%u) must be divisible by 16", samples_per_split);

    correlator_ = std::make_unique<tcc::Correlator>(
        device_, fmt,
        /*nrReceivers*/ nof_antennas,
        /*nrChannels*/ 1,
        /*nrSamplesPerChannel*/ samples_per_split,
        /*nrPolarizations*/ nof_pols);
}

// Class destructor
TensorCrossCorrelator::~TensorCrossCorrelator()
{
    delete double_buffer;
}

// Main event loop
void TensorCrossCorrelator::threadEntry()
{
    context_.setCurrent();
    cu::Event eH2D0, eH2D1;
    cu::Event eK0,   eK1;
    cu::Event eD2H0, eD2H1;

    const size_t total_m = nof_samples / 16;
    const size_t split_m = total_m / nof_splits_;
    const size_t m_stride_bytes = (size_t)nof_antennas * nof_pols * 16 * sizeof(SampleT);
    const size_t batch_m = std::max(size_t(1), (4UL * 1024 * 1024) / m_stride_bytes);

    while (!this->stop_thread)
    {
        Buffer *buffer;
        uint8_t split = 0;
        size_t split_streamed = 0; // M-blocks H2D'd for the current split

        // Stream completed M-blocks into the current split's device region while
        // the host buffer is still filling. When a non-final split is fully loaded,
        // fire its kernel immediately and move on to the next split.
        do
        {
            buffer = double_buffer->read_buffer();
            if (this->stop_thread)
                return;

            if (buffer == nullptr)
            {
                const int slot = double_buffer->get_consumer();
                const size_t global_safe = double_buffer->safe_m(slot);
                const size_t split_start = (size_t)split * split_m;
                const size_t split_available = (global_safe > split_start)
                    ? std::min(global_safe - split_start, split_m)
                    : 0;

                if (split_available >= split_streamed + batch_m)
                {
                    const uint8_t *host_base =
                        reinterpret_cast<const uint8_t *>(double_buffer->get_buffer_pointer(slot)->data);
                    stream_.memcpyHtoDAsync(
                        (CUdeviceptr)devSamples_ + split_streamed * m_stride_bytes,
                        host_base + (split_start + split_streamed) * m_stride_bytes,
                        (split_available - split_streamed) * m_stride_bytes);
                    split_streamed = split_available;
                }

                // Non-final split fully streamed: correlate and advance
                if (split_streamed == split_m && split + 1 < nof_splits_)
                {
                    correlator_->launchAsync(stream_, devVis_, devSamples_, split > 0);
                    split++;
                    split_streamed = 0;
                }
            }
        } while (buffer == nullptr);

        clock_gettime(CLOCK_MONOTONIC, &tic);

        const double timestamp = buffer->ref_time;
        const int channel = buffer->channel;
        const unsigned read_samples = buffer->read_samples;
        const unsigned nof_packets = buffer->nof_packets;
        const size_t vis_bytes = sizeof(VisT) * visExt_.size;

        // Buffer is ready: drain remaining splits. Each iteration copies the tail
        // not yet streamed for that split, fires the kernel, then the loop advances.
        stream_.record(eH2D0);
        for (; split < nof_splits_; split++)
        {
            const size_t split_start = (size_t)split * split_m;
            if (split_streamed < split_m)
            {
                stream_.memcpyHtoDAsync(
                    (CUdeviceptr)devSamples_ + split_streamed * m_stride_bytes,
                    reinterpret_cast<const uint8_t *>(buffer->data) + (split_start + split_streamed) * m_stride_bytes,
                    (split_m - split_streamed) * m_stride_bytes);
            }
            stream_.record(eH2D1);

            stream_.record(eK0);
            correlator_->launchAsync(stream_, devVis_, devSamples_, split > 0);
            stream_.record(eK1);

            split_streamed = 0;
        }

        stream_.record(eD2H0);
        stream_.memcpyDtoHAsync(hostVis_, devVis_, vis_bytes);
        stream_.record(eD2H1);

        stream_.synchronize();

        // eH2D1/eK0/eK1 reflect the last split; eH2D0 is before all tail work
        float h2d_ms = eH2D1.elapsedTime(eH2D0);
        float kern_ms = eK1.elapsedTime(eK0);
        float d2h_ms = eD2H1.elapsedTime(eD2H0);

        double_buffer->release_buffer();

        clock_gettime(CLOCK_MONOTONIC, &toc);
        if (callback != nullptr)
        {
            TensorCorrelatorMetadata metadata = {
                .channel_id  = static_cast<unsigned int>(channel),
                .time_taken  = ELAPSED_MS(tic, toc),
                .h2d_time = h2d_ms,
                .kern_time = kern_ms,
                .d2h_time = d2h_ms,
                .nof_samples = read_samples,
                .nof_packets = nof_packets,
            };
            callback(static_cast<void *>(hostVis_), timestamp, static_cast<void *>(&metadata));
        }

        LOG(INFO,
            "TCC ch=%d | tail-H2D=%.3f ms | last-kern=%.3f ms | D2H=%.3f ms "
            "(samples=%u, packets=%u, splits=%u)",
            channel, h2d_ms, kern_ms, d2h_ms,
            read_samples, nof_packets, (unsigned)nof_splits_);
    }
}
