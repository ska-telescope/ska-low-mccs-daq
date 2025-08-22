//
// Created by Alessio Magro on 14/05/2018.
//

#include "TensorCorrelatorData.h"
#include "SPEAD.h"
#include "libtcc/Correlator.h"

// Initialise correlator data consumer
bool TensorCorrelatorData::initialiseConsumer(json configuration)
{
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_antennas")) &&
        (key_in_json(configuration, "nof_channels")) &&
        (key_in_json(configuration, "nof_fine_channels")) &&
        (key_in_json(configuration, "nof_tiles")) &&
        (key_in_json(configuration, "nof_samples")) &&
        (key_in_json(configuration, "nof_pols")) &&
        (key_in_json(configuration, "max_packet_size")))
    {
        LOG(FATAL, "Missing configuration item for TensorCorrelatorData consumer. Requires "
                   "nof_antennas, nof_samples, nof_tiles, nof_pols, nof_channels, "
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

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t)32768 * this->nof_tiles);

    // Create double buffer
    double_buffer = new TccDoubleBuffer(nof_antennas * nof_tiles, nof_samples, nof_pols);

    // Create cross-correlator and start
    cu::init();
    cross_correlator = new TensorCrossCorrelator(double_buffer, nof_fine_channels,
                                                 nof_tiles * nof_antennas, nof_samples, nof_pols);

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
    delete double_buffer;
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
TensorCrossCorrelator::TensorCrossCorrelator(DoubleBuffer *double_buffer,
                                             uint32_t nof_fine_channels,
                                             uint16_t nof_antennas,
                                             uint32_t nof_samples,
                                             uint8_t nof_pols)
    : device_(0) // choose GPU 0
      ,
      context_(0, device_) // primary context on device 0
      ,
      stream_(),
      samplesExt_(multi_array::extents[1][nof_samples / 16][nof_antennas][nof_pols][16]),
      visExt_(multi_array::extents[1][(nof_antennas * (nof_antennas + 1)) / 2][nof_pols][nof_pols]),
      hostSamples_(sizeof(SampleT) * samplesExt_.size, CU_MEMHOSTALLOC_WRITECOMBINED), hostVis_(sizeof(VisT) * visExt_.size, 0),
      devSamples_(sizeof(SampleT) * samplesExt_.size), devVis_(sizeof(VisT) * visExt_.size),
      double_buffer(double_buffer),
      nof_channels(nof_fine_channels),
      nof_antennas(nof_antennas),
      nof_samples(nof_samples),
      nof_pols(nof_pols)

{
    context_.setCurrent();

    constexpr tcc::Format fmt = tcc::Format::i8; // TPMs produce int8 complex
    const int TPB = 16;
    if (nof_samples % TPB != 0)
    {
        LOG(FATAL, "nof_samples (%u) must be divisible by %d", nof_samples, TPB);
    }
    const int receiversPerBlock = 64;

    correlator_ = std::make_unique<tcc::Correlator>(
        device_, fmt,
        /*nrReceivers*/ nof_antennas,
        /*nrChannels*/ 1,
        /*nrTimesPerBlock*/ nof_samples,
        /*nrPolarizations*/ nof_pols,
        /*nrReceiversPerBlock*/ receiversPerBlock);
}

// Class destructor
TensorCrossCorrelator::~TensorCrossCorrelator()
{
}

// Main event loop
void TensorCrossCorrelator::threadEntry()
{
    while (!this->stop_thread)
    {
        Buffer *buffer;
        do
        {
            buffer = double_buffer->read_buffer();
            if (this->stop_thread)
                return;
        } while (buffer == nullptr);

        clock_gettime(CLOCK_MONOTONIC, &tic);

        const double timestamp = buffer->ref_time;
        const int channel = buffer->channel;
        const unsigned read_samples = buffer->read_samples;
        const unsigned nof_packets = buffer->nof_packets;
        const size_t sample_bytes = (size_t)nof_samples * nof_antennas * nof_pols * sizeof(uint16_t);
        const size_t vis_bytes    = sizeof(VisT) * visExt_.size;

        // 1) H->D copy
        stream_.memcpyHtoDAsync(devSamples_, buffer->data, sample_bytes);

        // 2) Correlate
        correlator_->launchAsync(stream_, devVis_, devSamples_, false);

        // 3) D->H visibilities
        stream_.memcpyDtoHAsync(hostVis_, devVis_, vis_bytes);

        // Ensure all GPU work done
        stream_.synchronize();

        // Release buffer back to producer
        double_buffer->release_buffer();

        // Callback
        clock_gettime(CLOCK_MONOTONIC, &toc);
        if (callback != nullptr)
        {
            CorrelatorMetadata metadata = {
                .channel_id = static_cast<unsigned int>(channel),
                .time_taken = ELAPSED_MS(tic, toc),
                .nof_samples = read_samples,
                .nof_packets = nof_packets,
            };
            callback(static_cast<void *>(hostVis_), timestamp, static_cast<void *>(&metadata));
        }

        LOG(INFO, "TCC correlator for channel %d took: %11.6f ms (%u samples, %u packets)",
            channel, ELAPSED_MS(tic, toc), read_samples, nof_packets);
    }
}
