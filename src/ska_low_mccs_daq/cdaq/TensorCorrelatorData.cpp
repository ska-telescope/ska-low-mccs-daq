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
    uint32_t ring_size = configuration.count("nbuffers") ? (uint32_t)configuration["nbuffers"] : 64;
    if (ring_size < 2)
    {
        LOG(FATAL, "nbuffers (%u) must be >= 2", ring_size);
        return false;
    }

    uint16_t nof_splits;
    if (configuration.count("nof_splits"))
    {
        nof_splits = (uint16_t)configuration["nof_splits"];
    }
    else
    {
        // Each split should be at least one DMA batch (~4 MiB) so H2D streaming
        // overlaps meaningfully with kernel execution.
        const size_t m_stride = (size_t)nof_tiles * nof_antennas * nof_pols * 16 * sizeof(uint16_t);
        const size_t batch_m = std::max(size_t(1), (4UL * 1024 * 1024) / m_stride);
        const size_t total_m = this->nof_samples / 16;
        nof_splits = (uint16_t)std::max(size_t(1), total_m / batch_m);
        LOG(INFO, "nof_splits not specified: auto-selected %u (batch_m=%zu, total_m=%zu)",
            (unsigned)nof_splits, batch_m, total_m);
    }

    if (this->nof_channels != 1)
    {
        LOG(FATAL, "TCC correlator only supports nof_channels=1 (got %u)", (unsigned)this->nof_channels);
        return false;
    }

    if (nof_active_tiles == 0 || nof_active_tiles > this->nof_tiles)
    {
        LOG(FATAL, "nof_active_tiles (%u) must be in [1, nof_tiles=%u]", (unsigned)nof_active_tiles, (unsigned)this->nof_tiles);
        return false;
    }

    if (nof_splits == 0)
    {
        LOG(FATAL, "nof_splits must be >= 1");
        return false;
    }

    {
        uint32_t aligned_ring = ring_size;
        while (aligned_ring >= 2 && (nof_splits % aligned_ring) != 0)
            --aligned_ring;
        if (aligned_ring < 2)
        {
            LOG(WARN, "ring_size=%u has no divisor of nof_splits=%u in [2, ring_size]; "
                      "leaving ring unaligned",
                ring_size, (unsigned)nof_splits);
        }
        else if (aligned_ring != ring_size)
        {
            LOG(INFO, "Adjusted ring_size %u -> %u so it divides nof_splits=%u "
                      "(integration-aligned)",
                ring_size, aligned_ring, (unsigned)nof_splits);
            ring_size = aligned_ring;
        }
    }

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t)32768 * this->nof_tiles);

    // Create cross-correlator and start
    cross_correlator = std::make_unique<TensorCrossCorrelator>(nof_fine_channels,
                                                               nof_tiles * nof_antennas, nof_samples, nof_pols,
                                                               nof_active_tiles * nof_antennas, nof_splits, ring_size);

    split_ring = cross_correlator->split_ring.get();
    split_m_ = (uint32_t)cross_correlator->split_ring->split_m();
    nof_splits_per_integ_ = (this->nof_samples / 16) / split_m_;

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
    split_ring = nullptr;
    cross_correlator.reset();
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
        // Request timed out, reset integration tracking
        rollover_counter = 0;
        reference_counter = 0;
        pkts_per_integ_ = 0;
        // Flush the ring so the consumer can drain the current partial integration
        // and reset its counters at the next integration boundary.
        if (split_ring != nullptr)
            split_ring->flush();
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

    // Cache packets-per-integration on first real packet
    if (pkts_per_integ_ == 0)
        pkts_per_integ_ = nof_samples / samples_in_packet;

    // Compute split and local M-block index from absolute packet position
    const uint64_t relative = (uint64_t)(packet_counter - reference_counter);
    const uint32_t integ_idx = (uint32_t)(relative / pkts_per_integ_);
    const uint32_t pkt_in_integ = (uint32_t)(relative % pkts_per_integ_);

    const uint32_t blocks_in_pkt = samples_in_packet / 16;
    const uint32_t m_in_integ = pkt_in_integ * blocks_in_pkt;
    const uint32_t split_idx = m_in_integ / split_m_;
    const uint32_t m_local = m_in_integ % split_m_;
    const uint64_t global_split = (uint64_t)integ_idx * nof_splits_per_integ_ + split_idx;

    // Write packet data to split ring (silently dropped if already consumed)
    split_ring->write_data(global_split, tile_id * nof_antennas + start_antenna_id,
                           nof_included_antennas, m_local, blocks_in_pkt,
                           reinterpret_cast<const uint16_t *>(payload + payload_offset),
                           packet_time, (int)start_channel_id);

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
                                             uint16_t nof_splits,
                                             uint32_t ring_size)
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

    m_stride_bytes_ = (size_t)nof_antennas * nof_pols * 16 * sizeof(SampleT);
    split_m_ = (nof_samples / 16) / nof_splits;
    batch_m_ = std::min(std::max(size_t(1), (4UL * 1024 * 1024) / m_stride_bytes_), split_m_);

    split_ring = std::make_unique<TccSplitRing>(nof_antennas, split_m_, nof_pols, nof_active_antennas, ring_size);
    h2d_done_ = std::make_unique<cu::Event[]>(ring_size);
}

// Class destructor
TensorCrossCorrelator::~TensorCrossCorrelator()
{
    // The CUDA context was made current in the correlator thread.  This
    // destructor runs in the calling (main) thread, which has never called
    // setCurrent().  Re-establish the context here so all subsequent member
    // destructors (DeviceMemory, HostMemory, Stream, Events, Correlator) can
    // call into the CUDA driver successfully.
    context_.setCurrent();

    // split_ring is declared before context_, so in implicit member-destruction
    // order it would be torn down *after* context_ (cuCtxDestroy) has run.  It
    // owns pinned cu::HostMemory, and freeing that after the context is gone
    // throws cu::Error (invalid argument).  Release it explicitly now, while the
    // context is still alive and current.
    split_ring.reset();
}

void TensorCrossCorrelator::copy_tail(const uint8_t *host_base, size_t split_start,
                                      size_t from, size_t to)
{
    if (from >= to)
        return;
    stream_.memcpyHtoDAsync(
        (CUdeviceptr)devSamples_ + from * m_stride_bytes_,
        host_base + (split_start + from) * m_stride_bytes_,
        (to - from) * m_stride_bytes_);
}

void TensorCrossCorrelator::try_stream_partial(uint64_t global_split, size_t &split_streamed)
{
    const uint32_t slot_idx = (uint32_t)(global_split % split_ring->ring_size());
    SplitSlot &sl = split_ring->get_slot(slot_idx);

    SlotState s = sl.state.load(std::memory_order_acquire);
    if (s != SlotState::FILLING && s != SlotState::READY)
        return;

    const size_t slot_available = std::min((size_t)split_ring->safe_m(slot_idx), split_m_);

    if (slot_available > split_streamed &&
        (slot_available - split_streamed >= batch_m_ || slot_available == split_m_))
    {
        const uint8_t *host_base =
            reinterpret_cast<const uint8_t *>(sl.data);
        copy_tail(host_base, /*split_start=*/0, split_streamed, slot_available);
        split_streamed = slot_available;
    }
}

// Main event loop
void TensorCrossCorrelator::threadEntry()
{
    context_.setCurrent();
    cu::Event eH2D0, eH2D1;
    cu::Event eK0, eK1;
    cu::Event eD2H0, eD2H1;

    struct timespec poll_tim = {0, 1000}; // 1 µs

    while (!this->stop_thread)
    {
        uint32_t total_read_samples = 0;
        uint32_t total_nof_packets = 0;
        double first_timestamp = 0.0;
        int channel = -1;
        const size_t vis_bytes = sizeof(VisT) * visExt_.size;

        clock_gettime(CLOCK_MONOTONIC, &tic);

        for (uint32_t split = 0; split < nof_splits_; ++split)
        {
            const uint32_t slot_idx = (uint32_t)((consumer_integ_ * (uint64_t)nof_splits_ + split) % split_ring->ring_size());
            const uint64_t global_split = consumer_integ_ * nof_splits_ + split;
            size_t split_streamed = 0;

            // Release the PREVIOUS split's slot now that its H2D is confirmed done.
            // Releasing one split later (not ring_size later) keeps PROCESSING time
            // to ~2ms instead of ~280ms, eliminating the window where incoming packets
            // for the next use of that slot hit PROCESSING and get dropped.
            if (split > 0)
            {
                const uint32_t prev_slot = (uint32_t)((global_split - 1) % split_ring->ring_size());
                h2d_done_[prev_slot].synchronize();
                split_ring->release_slot(global_split - 1);
            }

            // Poll until this split's slot is READY, streaming early while waiting
            do
            {
                if (this->stop_thread)
                    return;
                try_stream_partial(global_split, split_streamed);
                nanosleep(&poll_tim, nullptr);
            } while (split_ring->get_slot(slot_idx).state.load(std::memory_order_acquire) != SlotState::READY);

            SplitSlot &sl = split_ring->get_slot(slot_idx);
            sl.state.store(SlotState::PROCESSING, std::memory_order_release);

            // Mark this split consumed before H2D so any late-arriving packets
            // for it are permanently dropped rather than landing in a future slot.
            split_ring->mark_consumed(global_split);

            if (split == 0)
            {
                first_timestamp = sl.ref_time.load(std::memory_order_relaxed);
                channel = sl.channel;
            }
            total_read_samples += sl.read_samples.load(std::memory_order_relaxed);
            total_nof_packets += sl.nof_packets.load(std::memory_order_relaxed);

            const auto *data = reinterpret_cast<const uint8_t *>(sl.data);

            // Record only the tail copy (after packets finished) for H2D timing
            stream_.record(eH2D0);
            copy_tail(data, /*split_start=*/0, split_streamed, split_m_);
            stream_.record(eH2D1);
            h2d_done_[slot_idx].record(stream_); // fires when DMA for this slot is done

            stream_.record(eK0);
            correlator_->launchAsync(stream_, devVis_, devSamples_, split > 0);
            stream_.record(eK1);
        }

        // Release the final split's slot (all others were released one split later
        // in the loop above; the last one has no subsequent split to trigger it).
        const uint64_t last_global_split = consumer_integ_ * (uint64_t)nof_splits_ + (nof_splits_ - 1);
        const uint32_t last_slot_idx = (uint32_t)(last_global_split % split_ring->ring_size());
        h2d_done_[last_slot_idx].synchronize();
        split_ring->release_slot(last_global_split);

        stream_.record(eD2H0);
        stream_.memcpyDtoHAsync(hostVis_, devVis_, vis_bytes);
        stream_.record(eD2H1);

        stream_.synchronize();

        if (split_ring->check_and_reset())
            consumer_integ_ = 0;
        else
            ++consumer_integ_;

        // eH2D1/eK0/eK1 reflect the last split; eH2D0 is before all tail work
        float h2d_ms = eH2D1.elapsedTime(eH2D0);
        float kern_ms = eK1.elapsedTime(eK0);
        float d2h_ms = eD2H1.elapsedTime(eD2H0);

        clock_gettime(CLOCK_MONOTONIC, &toc);
        if (callback != nullptr)
        {
            TensorCorrelatorMetadata metadata = {
                .channel_id = static_cast<unsigned int>(channel),
                .time_taken = ELAPSED_MS(tic, toc),
                .h2d_time = h2d_ms,
                .kern_time = kern_ms,
                .d2h_time = d2h_ms,
                .nof_samples = total_read_samples,
                .nof_packets = total_nof_packets,
            };
            callback(static_cast<void *>(hostVis_), first_timestamp, static_cast<void *>(&metadata));
        }

        LOG(INFO,
            "TCC ch=%d | tail-H2D=%.3f ms | last-kern=%.3f ms | D2H=%.3f ms "
            "(samples=%u, packets=%u, splits=%u)",
            channel, h2d_ms, kern_ms, d2h_ms,
            total_read_samples, total_nof_packets, (unsigned)nof_splits_);
    }
}
