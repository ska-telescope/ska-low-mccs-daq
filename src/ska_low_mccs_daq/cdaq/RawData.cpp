//
// Created by Alessio Magro on 14/05/2018.
//

#include "RawData.h"
#include "SPEAD.h"

// Initialise raw data consumer
bool RawData::initialiseConsumer(json configuration)
{
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_antennas")) &&
        (key_in_json(configuration, "samples_per_buffer")) &&
        (key_in_json(configuration, "nof_tiles")) &&
        (key_in_json(configuration, "nof_pols")) &&
        (key_in_json(configuration, "max_packet_size"))) {
        LOG(FATAL, "Missing configuration item for RawData consumer. Requires "
                "nof_antennas, samples_per_buffer, nof_tiles, nof_pols and max_packet_size");
        return false;
    }

    // Set local values
    this -> nof_antennas       = configuration["nof_antennas"];
    this -> samples_per_buffer = configuration["samples_per_buffer"];
    this -> nof_tiles          = configuration["nof_tiles"];
    this -> nof_pols           = configuration["nof_pols"];
    this -> packet_size        = configuration["max_packet_size"];

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t) 4096 * nof_tiles);

    // Create antenna container
    container = new AntennaDataContainer<uint8_t>(nof_tiles, nof_antennas, samples_per_buffer, nof_pols);

    // Calculate total number of required samples per buffer
    nof_required_samples = nof_tiles * nof_antennas * samples_per_buffer;

    // All done
    return true;
}

// Set callback
void RawData::setCallback(DataCallback callback)
{
    this -> container -> setCallback(callback);
}

// Function called when a burst stream capture has finished
void RawData::onStreamEnd()
{
    // If there are no samples to persist, don't do anything
    if (nof_received_samples == 0)
        return;

    // Persist container
    container->persist_container();

    // Clear number of received samples
    nof_received_samples = 0;
}

void RawData::cleanUp() {
    delete container;
}

// Packet filter
bool RawData::packetFilter(unsigned char *udp_packet)
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

    // Check whether the SPEAD packet contains antenna data
    // Header must contain capture mode ID and its value 
    // must be 0 or 1
    //
    for (unsigned short i = 0; i < SPEAD_GET_NITEMS(hdr); i++) {
        uint64_t item = SPEAD_ITEM(udp_packet, i);
        if (SPEAD_ITEM_ID(item) == 0x2004) {
	    uint64_t mode = SPEAD_ITEM_ADDR(item);
            return mode == 0x0 || mode == 0x1;
	    }
    }
    return false;
}

// Receive packet
bool RawData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer -> pull_timeout(&packet, 0.1);
    
    // Check if the request timed out
    if (packet_size == SIZE_MAX) {
        // Request timed out
        return false;
    }

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);

    uint32_t packet_index   = 0;
    uint32_t packet_counter = 0;
    uint64_t payload_length = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint16_t start_antenna_id = 0;
    uint16_t nof_antennas = 0;
    uint16_t tile_id = 0;
    uint16_t station_id = 0;
    uint8_t  pol_id     = 0;
    uint32_t payload_offset = 0;

    // Get the number of items and get a pointer to the packet payload
    auto nof_spead_items = (unsigned short) SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nof_spead_items * SPEAD_ITEMLEN;

    // Loop over items to extract values
    for(unsigned i = 1; i <= nof_spead_items; i++)
    {
        uint64_t item = SPEAD_ITEM(packet, i);
        switch (SPEAD_ITEM_ID(item))
        {
            case 0x0001:  // Heap counter
            {
                packet_counter = (uint32_t) (SPEAD_ITEM_ADDR(item) & 0xFFFFFF);       // 24-bits
                packet_index   = (uint32_t) ((SPEAD_ITEM_ADDR(item) >> 24) & 0xFFFF); // 16-bits
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
            case 0x2000: // Antenna information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                start_antenna_id = (uint16_t) ((val >> 8) & 0xFF);
                nof_antennas     = (uint16_t) (val & 0xFF);
                break;
            }
            case 0x2001: // Tile information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                station_id = (uint16_t) ((val >> 16) & 0xFFFF);
                tile_id    = (uint16_t) ((val >> 32) & 0xFF);
                pol_id     = (uint8_t)   (val & 0xFF);
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
                LOG(INFO, "Unknown item 0x%#08x (%d of %d) \n", SPEAD_ITEM_ID(item), i, nof_spead_items);
        }
    }

    // Read timestamp scale value
    double timestamp_scale = 1.08e-6;

    // Calculate number of samples in packet
    uint32_t nof_samples = (uint32_t) (payload_length - payload_offset) / (nof_antennas * nof_pols);

    // Update number of received samples
    nof_received_samples += nof_samples;

    // We have processed the packet items, now comes the data
    uint32_t index = (packet_counter * nof_samples) % samples_per_buffer;
    container -> add_data(tile_id, start_antenna_id, index, nof_samples,
                          nof_antennas, payload + payload_offset, sync_time + timestamp * timestamp_scale);

    // Ready from packet
    ring_buffer -> pull_ready();

    // If the number of received samples match a full buffer's worth, persist it
    if (nof_received_samples == nof_required_samples)
        onStreamEnd();

    this->nof_packets++;
    // All done, return
    return true;
}
