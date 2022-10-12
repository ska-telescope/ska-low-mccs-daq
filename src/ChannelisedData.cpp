//
// Created by lessju on 14/05/2018.
//

#include "ChannelisedData.h"


#include "ChannelisedData.h"
#include "SPEAD.h"

// Initialise ChannelisedData
bool ChannelisedData::initialiseConsumer(json configuration)
{
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_tiles")) &&
        (key_in_json(configuration, "nof_channels")) &&
        (key_in_json(configuration, "nof_samples")) &&
        (key_in_json(configuration, "nof_antennas")) &&
        (key_in_json(configuration, "nof_pols")) &&
        (key_in_json(configuration, "max_packet_size"))) {
        LOG(FATAL, "Missing configuration item for ChannelisedData consumer. Requires "
                "nof_tiles, nof_channels, nof_samples, nof_antennas, nof_pols and max_packet_size");
        return false;
    }

    // Set local values
    this -> nof_channels = configuration["nof_channels"];
    this -> nof_tiles    = configuration["nof_tiles"];
    this -> nof_samples  = configuration["nof_samples"];
    this -> nof_antennas = configuration["nof_antennas"];
    this -> nof_pols     = configuration["nof_pols"];
    this -> packet_size  = configuration["max_packet_size"];

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t) nof_samples * nof_tiles);

    // Create channel container
    container = new ChannelDataContainer<uint16_t>(this -> nof_tiles, this -> nof_antennas,
                                                   this -> nof_samples, this -> nof_channels,
                                                   this -> nof_pols);

    // All done
    return true;
}

// Set channelised data callback
void ChannelisedData::setCallback(DataCallback callback)
{
    this -> container -> setCallback(callback);
}

// Packet filter
bool ChannelisedData::packetFilter(unsigned char *udp_packet)
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
    return mode == 0x4;
}

// Function called when a burst stream capture has finished
void ChannelisedData::onStreamEnd()
{
    // Persist current data
    num_packets = 0;
    container->persist_container();
}

// Override clean up method
void ChannelisedData::cleanUp() {
    delete container;
}

// Wait for packet and process it
bool ChannelisedData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer -> pull_timeout(&packet, 1);

    // Check if the request timed out
    if (packet_size == SIZE_MAX)
        // Request timed out
        return false;

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);

    uint32_t packet_index   = 0;
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
    uint8_t  pol_id     = 0;
    uint32_t payload_offset = 0;

    // Get the number of items and get a pointer to the packet payload
    auto nof_items = (unsigned short) SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nof_items * SPEAD_ITEMLEN;

    // Loop over items to extract values
    for(unsigned i = 1; i <= nof_items; i++)
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
            case 0x2002: // Antenna and Channel information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                start_channel_id      = (uint16_t) ((val >> 24) & 0xFFFF);
                nof_included_channels = (uint16_t) ((val >> 16) & 0xFF);
                start_antenna_id      = (uint16_t) ((val >> 8) & 0xFF);
                nof_included_antennas = (uint16_t) (val & 0xFF);
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
                LOG(INFO, "Unknown item %#010x (%d of %d) \n", SPEAD_ITEM_ID(item), i, nof_items);
        }
    }

    // Calculate number of samples in packet
    uint32_t samples_in_packet;

    samples_in_packet = (uint32_t) ((payload_length - payload_offset) /
                                    (nof_included_antennas * nof_pols * nof_included_channels * sizeof(uint16_t)));

    // TEMPORARY: Timestamp_scale maybe will disappear, so it's hardcoded for now
    double packet_time = sync_time + timestamp * 1.08e-6;// timestamp_scale;

    // We have processed the packet items, now comes the data
    num_packets++;
    int sample_index = packet_counter % (nof_samples / samples_in_packet);
    container -> add_data(tile_id, start_channel_id, sample_index * samples_in_packet, samples_in_packet,
                          start_antenna_id, (uint16_t *) (payload + payload_offset), packet_time,
                          nof_included_channels, nof_included_antennas);


    // Ready from packet
    ring_buffer -> pull_ready();

    // All done, return
    return true;
}

// -------------------------------------------------------------------------------------------

// Class constructor with parameters
bool ContinuousChannelisedData::initialiseConsumer(json configuration)
{

    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_tiles")) &&
        (key_in_json(configuration, "nof_channels")) &&
        (key_in_json(configuration, "nof_samples")) &&
        (key_in_json(configuration, "nof_antennas")) &&
        (key_in_json(configuration, "nof_pols")) &&
        (key_in_json(configuration, "nof_buffer_skips")) &&
        (key_in_json(configuration, "max_packet_size")) &&
        (key_in_json(configuration, "start_time"))) {
        LOG(FATAL, "Missing configuration item for ContinuousChannelisedData consumer. Requires "
                   "nof_tiles, nof_channels, nof_samples, nof_antennas, nof_pols, "
                   "nof_buffer_skips, start_time and max_packet_size");
        return false;
    }

    // Set local values
    nof_channels = configuration["nof_channels"];
    nof_tiles    = configuration["nof_tiles"];
    nof_samples  = configuration["nof_samples"];
    nof_antennas = configuration["nof_antennas"];
    nof_pols     = configuration["nof_pols"];
    packet_size  = configuration["max_packet_size"];
    nof_buffer_skips = configuration["nof_buffer_skips"];

    // Set star time, to the nearest second
    start_time = round((double) configuration["start_time"]);

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t) 131072 * nof_tiles);

    // Create channel container
    containers = (ChannelDataContainer<uint16_t> **) malloc(nof_containers * sizeof(ChannelDataContainer<uint16_t> *));
    for(unsigned i = 0; i < nof_containers; i++)
        containers[i] = new ChannelDataContainer<uint16_t>(nof_tiles, nof_antennas, nof_samples, nof_channels, nof_pols);

    // All done
    return true;
}

// Override clean up method
void ContinuousChannelisedData::cleanUp() {
    // Delete containers
    for(unsigned i = 0; i < nof_containers; i++)
        delete containers[i];
    free(containers);
}

// Set continuous channelised data callback
void ContinuousChannelisedData::setCallback(DataCallback callback)
{
    for(unsigned i = 0; i < nof_containers; i++)
        containers[i] -> setCallback(callback);
}

// Packet filter
bool ContinuousChannelisedData::packetFilter(unsigned char *udp_packet)
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

    // Check whether the SPEAD packet contains continuous channel data
    uint64_t mode = SPEAD_ITEM_ADDR(SPEAD_ITEM(udp_packet, 5));
    return (mode == 0x5 || mode == 0x7);
}

// Get and process packet
bool ContinuousChannelisedData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer -> pull_timeout(&packet, 1);

    // Check if the request timed out
    if (packet_size == SIZE_MAX) {
        // Request timed out
        return false;
    }

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);

    uint32_t packet_index   = 0;
    unsigned long packet_counter = 0;
    uint64_t payload_length = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint16_t start_channel_id = 0;
    uint16_t start_antenna_id = 0;
    uint16_t nof_included_channels = 0;
    uint16_t nof_included_antennas = 0;
    uint16_t tile_id = 0;
    uint16_t station_id = 0;
    uint8_t  pol_id     = 0;
    uint32_t payload_offset = 0;

    // Get the number of items and get a pointer to the packet payload
    auto nof_items = (unsigned short) SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nof_items * SPEAD_ITEMLEN;

    // Loop over items to extract values
    for(unsigned i = 1; i <= nof_items; i++)
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
            case 0x2002: // Antenna and Channel information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                start_channel_id      = (uint16_t) ((val >> 24) & 0xFFFF);
                nof_included_channels = (uint16_t) ((val >> 16) & 0xFF);
                start_antenna_id      = (uint16_t) ((val >> 8) & 0xFF);
                nof_included_antennas = (uint16_t) (val & 0xFF);
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
                LOG(INFO, "Unknown item %#010x (%d of %d) \n", SPEAD_ITEM_ID(item), i, nof_items);
        }
    }

    // Calculate number of samples in packet
    uint32_t samples_in_packet;

    samples_in_packet = (uint32_t) ((payload_length - payload_offset) /
                                    (nof_included_antennas * nof_included_channels * nof_pols * sizeof(uint16_t)));

    // TEMPORARY: Timestamp_scale may disappear, so it's hardcoded for now
    double packet_time = sync_time + timestamp * 1.08e-6; // timestamp_scale;

    // Check whether packet timestamp is past start time
    if (start_time > 0 and packet_time < start_time) {
        ring_buffer -> pull_ready();
        return true;
    }

    
    // Handle packet counter rollover
    // First condition ensures that if DAQ is started before transmission, firs packet with counter 0 are not updates
    if (reference_counter == 0)
        reference_counter = packet_counter;
    else
    {
        if (tile_id == 0 && packet_counter == 0 && pol_id == 0) {
            rollover_counter += 1;
            packet_counter += rollover_counter << 24;
        }
        else if (packet_counter == 0)
            packet_counter += 1 << 24;
        else
            packet_counter += rollover_counter << 24;
    }

    // Assigned correct packet index
    packet_index = static_cast<uint32_t>((packet_counter - reference_counter) % (this->nof_samples / samples_in_packet));

    // Set start channel ID to 1 (otherwise it will mess with buffer indexing)
    auto cont_channel_id = start_channel_id;
    start_channel_id = 0;

    // Check if packet belongs to current buffer
    if (reference_time == 0)
        reference_time = packet_time;

    // If packet time is less than reference time, then this belongs to the previous buffer
    if (packet_time < reference_time)
    {
        // If we are skipping buffer, ignore previous packet
        if (nof_buffer_skips == 0) {

            // We have processed the packet items, now comes the data
            unsigned index = (current_container - 1) % nof_containers;
            containers[index]->add_data(tile_id, start_channel_id, packet_index * samples_in_packet,
                                        samples_in_packet, start_antenna_id,
                                        (uint16_t *) (payload + payload_offset), packet_time,
                                        nof_included_channels, nof_included_antennas, cont_channel_id);
        }

        // Ready from packet
        ring_buffer -> pull_ready();
        return true;
    }

    // Check if we skipped buffer boundaries
    if (packet_index == 0 && packet_time >= reference_time + nof_samples * 1.08e-6 && 
        num_packets > nof_tiles * 2 && tile_id == 0 && pol_id == 0)
    {
        // Increment buffer skip
        if (nof_buffer_skips != 0)
            current_buffer = (current_buffer + 1) % (nof_buffer_skips);
        else
            current_buffer = 0;

        // Only update and persist container when current_buffer == 0
        if (current_buffer == 0) {

            // If we are skipping buffer, then persist previous current container
            if (nof_buffer_skips != 0) {
                if (containers[current_container]->nof_packets > 0)
                    containers[current_container]->persist_container();

                // Update container index
                current_container = (current_container + 1) % nof_containers;
            } else {
                // Update container index
                current_container = (current_container + 1) % nof_containers;

                // If the number of processed packet in this container is greater than 0, persist it
                if (containers[current_container]->nof_packets > 0)
                    containers[current_container]->persist_container();
            }

            // Update timestamp
            reference_time += nof_samples * 1.08e-6;
            num_packets = 0;
        }
    }

    // If we are skipping buffers, and current_buffer != 0, then don't add packet
    if (current_buffer != 0) {
        ring_buffer -> pull_ready();
        return true;
    }

    // Increment number of received packets
    num_packets++;

    // We have processed the packet items, now comes the data
    containers[current_container] -> add_data(tile_id, start_channel_id, packet_index * samples_in_packet, 
                                              samples_in_packet, start_antenna_id,
                                              (uint16_t *) (payload + payload_offset), packet_time, 
                                              nof_included_channels, nof_included_antennas, cont_channel_id);

    // Ready from packet
    ring_buffer -> pull_ready();

    // All done, return
    return true;
}

// -------------------------------------------------------------------------------------------
bool IntegratedChannelisedData::initialiseConsumer(json configuration)
{
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_tiles")) &&
        (key_in_json(configuration, "nof_channels")) &&
        (key_in_json(configuration, "nof_antennas")) &&
        (key_in_json(configuration, "nof_pols")) &&
        (key_in_json(configuration, "max_packet_size"))) {
        LOG(FATAL, "Missing configuration item for IntegratedChannelisedData consumer. Requires "
                "nof_tiles, nof_channels, nof_antennas, nof_pols and max_packet_size");
        return false;
    }

    // Set local values
    this -> nof_channels = configuration["nof_channels"];
    this -> nof_tiles    = configuration["nof_tiles"];
    this -> nof_antennas = configuration["nof_antennas"];
    this -> nof_pols     = configuration["nof_pols"];
    this -> nof_samples  = 1;
    this -> packet_size  = configuration["max_packet_size"];

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t) 1024);

    // Create channel container
    container = new ChannelDataContainer<uint16_t>(this -> nof_tiles, this -> nof_antennas,
                                                   this -> nof_samples, this -> nof_channels,
                                                   this -> nof_pols);

    return true;
}

// Set integrate channel callback
void IntegratedChannelisedData::setCallback(DataCallback callback)
{
    this -> container -> setCallback(callback);
}

void IntegratedChannelisedData::cleanUp() {
//    delete container;
}

// Packet filter
bool IntegratedChannelisedData::packetFilter(unsigned char *udp_packet)
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

    // Check whether the SPEAD packet contains integrated channel data
    uint64_t mode = SPEAD_ITEM_ADDR(SPEAD_ITEM(udp_packet, 5));
    return mode == 0x6;
}

// Get and process packet
bool IntegratedChannelisedData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer -> pull_timeout(&packet, 0.5);

    // Check if the request timed out
    if (packet_size == SIZE_MAX)
        // Request timed out
        return false;

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);

    uint32_t packet_index   = 0;
    uint32_t packet_counter = 0;
    uint64_t heap_offset = 0;
    uint64_t payload_length = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint64_t timestamp_scale_offset = 0;
    uint64_t center_frequency_offset = 0;
    uint16_t start_channel_id = 0;
    uint16_t start_antenna_id = 0;
    uint16_t nof_included_channels = 0;
    uint16_t nof_included_antennas = 0;
    uint16_t tile_id = 0;
    uint16_t station_id = 0;
    uint8_t  pol_id     = 0;
    uint32_t payload_offset = 0;

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
            case 0x2002: // Antenna and Channel information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                start_channel_id      = (uint16_t) ((val >> 24) & 0xFFFF);
                nof_included_channels = (uint16_t) ((val >> 16) & 0xFF);
                start_antenna_id      = (uint16_t) ((val >> 8) & 0xFF);
                nof_included_antennas = (uint16_t) (val & 0xFF);
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
                LOG(INFO, "Unknown item %#010x (%d of %d) \n", SPEAD_ITEM_ID(item), i, nofitems);
        }
    }

    // Note: hardcoded number of samples for integrated data
    uint32_t samples_in_packet = 1;

    // Overwrite number of included channels since this does not fit in header for integrated data
    nof_included_channels = static_cast<uint16_t>((payload_length - payload_offset) /
            (nof_included_antennas * nof_pols * samples_in_packet * sizeof(uint16_t)));

    // TEMPORARY: Timestamp_scale may disappear, so it's hardcoded for now
    double packet_time = sync_time + timestamp * 1.08e-6;

    // Check if we processed all the sample
    if (num_packets == this -> nof_antennas * this -> nof_pols * this -> nof_tiles / nof_included_antennas)
    {
        container -> persist_container();
        num_packets = 0;
    }

    // We have processed the packet items, now comes the data
    num_packets++;
    container -> add_data(tile_id, start_channel_id, 0, samples_in_packet,
                          start_antenna_id, (uint16_t *) (payload + payload_offset), packet_time,
                          nof_included_channels, nof_included_antennas);

    // Ready from packet
    ring_buffer -> pull_ready();

    // All done, return
    return true;
}
