//
// Created by Alessio Magro on 14/05/2018.
//

#include "RawData.h"
#include "SPEAD.h"

// Expose class factory
extern "C" DataConsumer *rawdata() { return new RawData; }

// Initialise raw data consumer
bool RawData::initialiseConsumer(json configuration)
{
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_antennas") &&
          key_in_json(configuration, "samples_per_buffer") &&
          key_in_json(configuration, "nof_tiles") &&
          key_in_json(configuration, "nof_pols") &&
          key_in_json(configuration, "max_packet_size"))) {
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

    // Optional: sample bitwidth (8 or 16) and SPEAD timestamp tick
    if (key_in_json(configuration, "bitwidth"))
        this -> bitwidth = configuration["bitwidth"];
    if (key_in_json(configuration, "sampling_time"))
        this -> sampling_time = configuration["sampling_time"];

    if (bitwidth != 8 && bitwidth != 16) {
        LOG(FATAL, "Unsupported raw data bitwidth %d, must be 8 or 16", bitwidth);
        return false;
    }

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t) 4096 * nof_tiles);

    // Create antenna container
    if (bitwidth == 16)
        container_16bit = new AntennaDataContainer<int16_t>(nof_tiles, nof_antennas, samples_per_buffer, nof_pols);
    else
        container = new AntennaDataContainer<uint8_t>(nof_tiles, nof_antennas, samples_per_buffer, nof_pols);

    // Calculate total number of required samples per buffer
    nof_required_samples = nof_tiles * nof_antennas * samples_per_buffer;

    // All done
    return true;
}

// Set callback
void RawData::setCallback(DataCallbackDynamic callback)
{
    if (bitwidth == 16)
        container_16bit -> setCallback(callback);
    else
        container -> setCallback(callback);
}

// Function called when a burst stream capture has finished
void RawData::onStreamEnd()
{
    // If there are no samples to persist, don't do anything
    if (nof_received_samples == 0)
        return;

    // Persist container
    if (bitwidth == 16)
        container_16bit -> persist_container();
    else
        container -> persist_container();

    // Clear number of received samples
    nof_received_samples = 0;
}

void RawData::cleanUp() {
    delete container;
    delete container_16bit;
    container = nullptr;
    container_16bit = nullptr;
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

    uint32_t packet_index  = 0;
    uint32_t packet_counter = 0;
    uint64_t payload_length = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint8_t start_antenna_id = 0;
    uint8_t nof_antennas = 0;
    uint8_t tile_id = 0;
    uint16_t station_id = 0;
    uint8_t fpga_id = 0;
    uint64_t payload_offset = 0;

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
            case 0x1028: // Timestamp HI
            {
                timestamp = (SPEAD_ITEM_ADDR(item) & 0x7FF) << 40;
                uint64_t TAI_2000 = 946684768 - 5; // Unix time of TAI 2000, including extra leap seconds
                sync_time = TAI_2000;
                break;
            }
            case 0x1600: // Timestamp
            {
                timestamp += SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x2000: // Antenna information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                start_antenna_id = (uint8_t) ((val >> 8) & 0xFF);
                nof_antennas     = (uint8_t) (val & 0xFF);
                break;
            }
            case 0x2001: // Tile information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                station_id = (uint16_t) ((val >> 16) & 0xFFFF);
                tile_id    = (uint8_t) ((val >> 32) & 0xFF);
                fpga_id     = (uint8_t)   (val & 0xFF);
                break;
            }
            case 0x3300: // Payload offset
            {
                payload_offset = (uint64_t) SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x2004:
                break;
            default:
                LOG(INFO, "Unknown item 0x%#08x (%d of %d) \n", SPEAD_ITEM_ID(item), i, nof_spead_items);
        }
    }

    // Calculate number of samples per antenna in packet
    uint32_t nof_samples = (uint32_t) (payload_length - payload_offset) /
                           (nof_antennas * nof_pols * (bitwidth / 8));

    // We have processed the packet items, now comes the data
    uint32_t index = (packet_counter * nof_samples) % samples_per_buffer;
    double packet_time = sync_time + timestamp * sampling_time;
    bool accepted;
    if (bitwidth == 16)
        accepted = addToContainer(container_16bit, packet_counter, payload_length, sync_time, timestamp,
                                  station_id, fpga_id, payload_offset, tile_id, start_antenna_id, index,
                                  nof_samples, nof_antennas, payload, packet_time);
    else
        accepted = addToContainer(container, packet_counter, payload_length, sync_time, timestamp,
                                  station_id, fpga_id, payload_offset, tile_id, start_antenna_id, index,
                                  nof_samples, nof_antennas, payload, packet_time);

    // Update number of received samples, counted per antenna like nof_required_samples.
    // Packets the container dropped do not count towards a full buffer
    if (accepted)
        nof_received_samples += nof_samples * nof_antennas;

    // Ready from packet
    ring_buffer -> pull_ready();

    // If the number of received samples match a full buffer's worth, persist it
    if (nof_received_samples == nof_required_samples)
        onStreamEnd();

    // All done, return
    return true;
}

// Add a packet's samples to the container of the configured bitwidth
template <class T> bool RawData::addToContainer(AntennaDataContainer<T> *container, uint32_t packet_counter,
    uint64_t payload_length, uint64_t sync_time, uint64_t timestamp, uint16_t station_id,
    uint8_t fpga_id, uint64_t payload_offset, uint8_t tile_id, uint8_t start_antenna_id,
    uint32_t index, uint32_t nof_samples, uint8_t nof_included_antennas, uint8_t *payload,
    double packet_time)
{
    return container -> add_data(packet_counter, payload_length, sync_time, timestamp, station_id, fpga_id,
                                 payload_offset, tile_id, start_antenna_id, index, nof_samples,
                                 nof_included_antennas, reinterpret_cast<T *>(payload + payload_offset), packet_time);
}
