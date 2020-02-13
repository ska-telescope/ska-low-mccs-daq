//
// Created by Alessio Magro on 14/05/2018.
//

#include "BeamformedData.h"
#include "SPEAD.h"

// Initialise beam data consumer
bool BeamformedData::initialiseConsumer(json configuration)
{
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_tiles")) &&
        (key_in_json(configuration, "nof_channels")) &&
        (key_in_json(configuration, "nof_samples")) &&
        (key_in_json(configuration, "nof_pols")) &&
        (key_in_json(configuration, "max_packet_size"))) {
        LOG(FATAL, "Missing configuration item for PharosBeamformedData consumer. Requires "
                "nof_tiles, nof_channels, nof_samples, nof_pols and max_packet_size");
        return false;
    }

    // Set local values
    this -> nof_tiles          = configuration["nof_tiles"];
    this -> nof_channels       = configuration["nof_channels"];
    this -> nof_samples        = configuration["nof_samples"];
    this -> nof_pols           = configuration["nof_pols"];
    this -> packet_size        = configuration["max_packet_size"];

    // Create ring buffer
    initialiseRingBuffer(packet_size, nof_samples * 16);

    // Create channel container
    container = new BurstBeamDataContainer<uint32_t>(nof_tiles, nof_samples, nof_channels, nof_pols);

    // All done
    return true;
}

// Set callback
void BeamformedData::setCallback(DataCallback callback)
{
    this -> container -> setCallback(callback);
}

// Function called when a burst stream capture has finished
void BeamformedData::onStreamEnd()
{
    // Persist current data
    container->persist_container();
}

// Packet filter
bool BeamformedData::packetFilter(unsigned char *udp_packet)
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

    // Check whether the SPEAD packet contains burst beam data
    uint64_t mode = SPEAD_ITEM_ADDR(SPEAD_ITEM(udp_packet, 5));
    return mode == 0x8;
}

// Get and process packet
bool BeamformedData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer -> pull_timeout(&packet, 0.2);

    // Check if the request timed out
    if (packet_size == SIZE_MAX)
        // Request timed out
        return false;

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);

    uint64_t packet_counter = 0;
    uint64_t payload_length = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint16_t beam_id = 0;
    uint16_t frequency_id = 0;
    uint16_t tile_id = 0;
    uint16_t station_id = 0;
    uint16_t nof_contributing_antennas = 0;
    uint32_t payload_offset = 0;
    uint16_t start_channel_id = 0;
    uint16_t nof_included_channels = 0;

    // Get the number of items and get a pointer to the packet payload
    auto nofitems = (unsigned short) SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nofitems * SPEAD_ITEMLEN;

    // Loop over items to extract values
    for(unsigned i = 1; i <= nofitems; i++)
    {
        uint64_t item = SPEAD_ITEM(packet, i);
        switch (SPEAD_ITEM_ID(item))
        {
            case 0x0001:  // Heap counter
            {
                packet_counter = SPEAD_ITEM_ADDR(item) & 0xFFFFFF;
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
            case 0x2005: // Antenna and Channel information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                beam_id               = (uint8_t) ((val >> 32) & 0xFF);
                start_channel_id      = (uint16_t) ((val >> 16) & 0xFFFF);
                nof_included_channels = (uint16_t) ((val) & 0xFFFF);
                break;
            }
            case 0x2003: // Tile and Station information (LMC data)
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                tile_id    = (uint16_t) ((val >> 32) & 0xFF);
                station_id = (uint16_t) ((val >> 16) & 0xFFFF);
                nof_contributing_antennas = (uint16_t) (val & 0xFFFF);
                break;
            }
            case 0x3300: // Payload offset
            {
                payload_offset = (uint32_t) SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x2004:
                break;
            default:
                LOG(INFO, "Unknown item %#010x (%d of %d) \n", SPEAD_ITEM_ID(item), i, nofitems);
        }
    }

    // TEMPORARY: Timestamp_scale maybe will disappear, so it's hardcoded for now
    double packet_time = sync_time + timestamp * 1.08e-6; // timestamp_scale;

    // Increment number of received packets
    this -> received_packets++;

    // Add data to container
    container->add_data(tile_id, packet_counter * payload_length, start_channel_id, payload_length / 4,
                        (uint32_t *) (payload + payload_offset), packet_time);

    // Ready from packet
    ring_buffer -> pull_ready();

    // All done, return
    return true;
}

// --------------------------------------------------------------------------------------------------

// Initialise beam data consumer
bool IntegratedBeamformedData::initialiseConsumer(json configuration)
{
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_tiles")) &&
        (key_in_json(configuration, "nof_beams")) &&
        (key_in_json(configuration, "nof_channels")) &&
        (key_in_json(configuration, "nof_samples")) &&
        (key_in_json(configuration, "nof_pols")) &&
        (key_in_json(configuration, "max_packet_size"))) {
        LOG(FATAL, "Missing configuration item for IntegratedBeamformedData consumer. Requires "
                "nof_tiles, nof_beams, nof_channels, nof_samples, nof_pols and max_packet_size");
        return false;
    }

    // Set local values
    this -> nof_tiles          = configuration["nof_tiles"];
    this -> nof_beams          = configuration["nof_beams"];
    this -> nof_channels       = configuration["nof_channels"];
    this -> nof_samples        = configuration["nof_samples"];
    this -> nof_pols           = configuration["nof_pols"];
    this -> packet_size        = configuration["max_packet_size"];

    // Create ring buffer
    initialiseRingBuffer(packet_size, this->nof_samples * 16);

    // Create channel container
    container = new IntegratedBeamDataContainer<uint32_t>(nof_tiles, nof_beams, nof_samples,
                                                          nof_channels, nof_pols);

    // All done
    return true;
}

// Set callback
void IntegratedBeamformedData::setCallback(DataCallback callback)
{
    this -> container -> setCallback(callback);
}

// Packet filter
bool IntegratedBeamformedData::packetFilter(unsigned char *udp_packet)
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

    // Check whether the SPEAD packet contains integrated beam data
    uint64_t mode = SPEAD_ITEM_ADDR(SPEAD_ITEM(udp_packet, 5));
    return mode == 0x9 || mode == 0x11;
}

// Get and process packet
bool IntegratedBeamformedData::processPacket()
{
    // Get next packet to process
    // If number of samples is -1 then we are grabbing integrated beam data, where a single spectrum
    // per polarisation is sent for an integration period
    size_t packet_size;
    packet_size = ring_buffer -> pull_timeout(&packet, 1);

    // Check if the request timed out
    if (packet_size == SIZE_MAX)
        // Request timed out
        return false;

    // Get SPEAD header
    uint64_t hdr = SPEAD_HEADER(packet);

    uint32_t packet_index = 0;
    uint32_t packet_counter = 0;
    uint64_t payload_length = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint16_t beam_id = 0;
    uint16_t frequency_id = 0;
    uint16_t tile_id = 0;
    uint16_t station_id = 0;
    uint16_t nof_contributing_antennas = 0;
    uint32_t payload_offset = 0;
    uint16_t nof_included_channels = 0;
    uint16_t start_channel_id = 0;

    // Get the number of items and get a pointer to the packet payload
    auto nofitems = (unsigned short) SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nofitems * SPEAD_ITEMLEN;

    // Loop over items to extract values
    for(unsigned i = 1; i <= nofitems; i++)
    {
        uint64_t item = SPEAD_ITEM(packet, i);
        switch (SPEAD_ITEM_ID(item))
        {
            case 0x0001:  // Heap counter
            {
                packet_counter  = (uint32_t) (SPEAD_ITEM_ADDR(item) & 0xFFFFFF);       // 24-bits
                packet_index    = (uint32_t) ((SPEAD_ITEM_ADDR(item) >> 24) & 0xFFFF); // 16-bits
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
            }
            case 0x2005: // Antenna and Channel information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                beam_id               = (uint8_t) ((val >> 32) & 0xFF);
                start_channel_id      = (uint16_t) ((val >> 16) & 0xFFFF);
                nof_included_channels = (uint16_t) ((val) & 0xFFFF);
                break;
            }
            case 0x2003: // Tile and Station information (LMC data)
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                tile_id    = (uint16_t) ((val >> 32) & 0xFF);
                station_id = (uint16_t) ((val >> 16) & 0xFFFF);
                nof_contributing_antennas = (uint16_t) (val & 0xFFFF);
                break;
            }
            case 0x3300: // Payload offset
            {
                payload_offset = (uint32_t) SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x2004:
                break;
            default:
                LOG(INFO, "Unknown item %#010x (%d of %d) \n", SPEAD_ITEM_ID(item), i, nofitems);
        }
    }

    // TEMPORARY: Timestamp_scale maybe will disappear, so it's hardcoded for now
    double packet_time = sync_time + timestamp * 1.08e-6; // timestamp_scale;

    // Keep track of packet counter
    if (this->saved_packet_counter == 0)
        this->saved_packet_counter = packet_counter;

    // Check whether we have already filled up the buffer, in which case persist container
    if (this -> received_packets == this->nof_pols * this->nof_tiles * this->nof_samples * this->nof_beams ||
        packet_counter - this->saved_packet_counter == nof_samples)
    {
        container->persist_container();
        this->saved_packet_counter = packet_counter;
        this->received_packets = 0;
    }

    // We have processed the packet items, now comes the data
    container -> add_data(tile_id, beam_id, start_channel_id, nof_included_channels, packet_counter - this->saved_packet_counter, 1,
                          (uint32_t *) (payload + payload_offset), packet_time);

    // Increment number of received packets
    this -> received_packets++;

    // Ready from packet
    ring_buffer -> pull_ready();

    // All done, return
    return true;
}
