//
// Created by Alessio Magro on 05/05/2022.
//

#include "AntennaBuffer.h"
#include "SPEAD.h"

// Initilise anenna buffer consumer
bool AntennaBuffer::initialiseConsumer(json configuration) {
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_antennas")) &&
        (key_in_json(configuration, "nof_samples")) &&
        (key_in_json(configuration, "nof_tiles")) &&
        (key_in_json(configuration, "max_packet_size"))) {
        LOG(FATAL, "Missing configuration item for AntennaBuffer consumer. Requires "
                   "nof_antennas, nof_samples, nof_tiles, nof_tiles and max_packet_size");
        return false;
    }

    // Set local values
    nof_antennas       = configuration["nof_antennas"];
    nof_tiles          = configuration["nof_tiles"];
    nof_pols           = 2;
    nof_samples        = configuration["nof_samples"];
    packet_size        = configuration["max_packet_size"];

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t) 32768 * nof_tiles);

    // Create antenna containers
    containers = (AntennaBufferDataContainer<uint8_t> **)malloc(nof_containers * sizeof(AntennaBufferDataContainer<uint16_t> *));
    for(unsigned i = 0; i < nof_containers; i++)
        containers[i] = new AntennaBufferDataContainer<uint8_t>(nof_tiles, nof_antennas, nof_samples, nof_pols);

    // All done
    return true;
}

// Set callback
void AntennaBuffer::setCallback(DataCallback callback) {
    for(unsigned i = 0; i < nof_containers; i++)
        this->containers[i]->setCallback(callback);
}

// Function called when the stream capture has finished
void AntennaBuffer::onStreamEnd() {
    // On stream end, move backwards and persist data to disk
    for(unsigned i = 0; i < nof_containers; i++) {
        auto index = (current_container + i + 1) % nof_containers;
        if (containers[index]->nof_packets > 0)
            containers[index]->persist_container();
    }
}

// Clean up objects
void AntennaBuffer::cleanUp() {
    for(unsigned i = 0; i < nof_containers; i++)
        delete containers[i];
    free(containers);
}

// Packet filter
bool AntennaBuffer::packetFilter(unsigned char *udp_packet) {
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
    for (unsigned short i = 0; i < SPEAD_GET_NITEMS(hdr); i++) {
        uint64_t item = SPEAD_ITEM(udp_packet, i);
        if (SPEAD_ITEM_ID(item) == 0x2004) {
	    uint64_t mode = SPEAD_ITEM_ADDR(item);
            return mode == 0xC;
	    }
    }

    return false;
}

// Receive packet
bool AntennaBuffer::processPacket() {
    // Get next packet to process
    size_t packet_size = ring_buffer -> pull_timeout(&packet, 0.1);

    // Check if the request timed out
    if (packet_size == SIZE_MAX) {
        // Request timed out
        return false;
    }

    // Get SPEAD header and declare metadata placeholders
    uint64_t hdr = SPEAD_HEADER(packet);

    uint32_t packet_counter = 0;
    uint64_t payload_length = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint8_t nof_included_antennas = 0;
    uint8_t antenna_0_id = 0, antenna_1_id = 0, antenna_2_id = 0, antenna_3_id = 0;
    uint16_t tile_id = 0;
    uint16_t station_id = 0;
    uint8_t  fpga_id     = 0;
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
                packet_counter = (uint32_t) (SPEAD_ITEM_ADDR(item) & 0xFFFFFF);  // 24-bits
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
            case 0x2006: // Antenna information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                antenna_0_id = (uint8_t) (val & 0xFF);
                antenna_1_id = (uint8_t) ((val >> 8) & 0xFF);
                antenna_2_id = (uint8_t) ((val >> 16) & 0xFF);
                antenna_3_id = (uint8_t) ((val >> 24) & 0xFF);
                nof_included_antennas = (uint8_t) ((val >> 32) & 0xFF);
                break;
            }
            case 0x2001: // Tile information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                station_id = (uint16_t) ((val >> 16) & 0xFFFF);
                tile_id  = (uint16_t) ((val >> 32) & 0xFF);
                fpga_id = (uint8_t)   (val & 0xFF);
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

    // Calculate number of samples in packet
    // TODO: correct the effective number of antennas if the SPEAD firmware 
    // packs differently one or two antennas
    uint8_t nof_effective_antennas = 2;
    uint32_t packet_samples = (uint32_t) (payload_length - payload_offset) / (nof_effective_antennas * nof_pols);

    // Calculate packet time
    const int timestamp_factor = 864 * 256 / 8;    // samples per timestamp unit
    double packet_time = sync_time + (timestamp * timestamp_factor + packet_counter * packet_samples) * timestamp_scale;

    // Assign correct packet index
    auto packet_index = static_cast<uint32_t>(packet_counter % (nof_samples / packet_samples));

    if (current_packet_index < 0)
        current_packet_index = packet_index;

    // If the calculated packet index is much greater than the current packet index, then this
    // means that the packet belongs to the previous buffer (in normal circumstances. under
    // heavy load or extreme packet loss this will not be the case, but the data will be unusable anyway)
    if ((static_cast<int>(packet_index) - current_packet_index) > (32 * nof_tiles)) {
        unsigned index = (current_container - 1) % nof_containers;
        containers[index]->add_data((uint8_t *) (payload + payload_offset),
                                    tile_id, packet_index * packet_samples, packet_samples, timestamp, fpga_id);

        // Ready from packet
        ring_buffer -> pull_ready();
        return true;
    }

    // Check if we skipped buffer boundaries
    if (packet_index == 0 && containers[current_container]->nof_packets >= nof_tiles * 2) {

        // Advance by one container
        current_container = (current_container + 1) % nof_containers;

        // If container is not empty, persist
        if (containers[current_container]->nof_packets > 0)
            containers[current_container]->persist_container();
    }

    // Add packet to current container
    containers[current_container]->add_data((uint8_t *) (payload + payload_offset),
                                            tile_id, packet_index * packet_samples,
                                            packet_samples, packet_time, fpga_id);

    // Ready from packet
    ring_buffer -> pull_ready();

    // Update packet index
    current_packet_index = packet_index;

    // All done, return
    return true;
}
