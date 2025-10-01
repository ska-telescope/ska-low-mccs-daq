//
// Created by Alessio Magro on 05/05/2022.
//

#ifndef AAVS_DAQ_ANTENNABUFFER_H
#define AAVS_DAQ_ANTENNABUFFER_H

#include <cstdlib>
#include <unistd.h>
#include <fcntl.h>
#include <cstring>
#include <cmath>
#include <string>
#include <unordered_map>
#include <sys/mman.h>
#include <cfloat>

#include "DAQ.h"

// ----------------- Antenna Buffer container and helpers -----------------
template <class T> class AntennaBufferDataContainer
{
public:

    struct AntennaBufferMetadata {
        uint64_t nof_packets=0;
        uint32_t packet_counter[2048] = 0;
        uint64_t payload_length;
        uint64_t sync_time[2048] = 0;
        uint64_t timestamp[2048] = 0;
        uint8_t nof_included_antennas;
        uint8_t antenna_0_id; 
        uint8_t antenna_1_id; 
        uint8_t antenna_2_id; 
        uint8_t antenna_3_id;
        uint8_t tile_id;
        uint16_t station_id;
        uint8_t fpga_id[2048] = 0;
        uint32_t payload_offset;
    }; 

    struct AntennaBufferStructure {
        uint16_t tile;
        T* data;
    };

    // Class constructor
    AntennaBufferDataContainer(uint16_t nof_tiles, uint16_t nof_antennas, uint32_t nof_samples, uint8_t nof_pols)
    {
        // Set local variables
        this->nof_antennas = nof_antennas;
        this->nof_samples = nof_samples;
        this->nof_tiles = nof_tiles;
        this->nof_pols = nof_pols;
        antennas_per_fpga = nof_antennas / 2;

        size_t malloc_size = nof_antennas * nof_pols * (size_t) nof_samples * sizeof(T);

        // Allocate buffer
        antenna_buffer_data = (AntennaBufferStructure *) malloc(nof_tiles * sizeof(AntennaBufferStructure));
        metadata = (AntennaBufferMetadata *) malloc(nof_tiles * sizeof(AntennaBufferMetadata));

        for(unsigned i = 0; i < nof_tiles; i++) {
            allocate_aligned((void **) &(antenna_buffer_data[i].data), (size_t) CACHE_ALIGNMENT, malloc_size);

            // Lock memory
            if (mlock(antenna_buffer_data[i].data, malloc_size) == -1)
                perror("Could not lock memory");
        }

        // Reset antenna information
        clear();

        // Reserve required number of buckets in map
        tile_map.reserve(nof_tiles);
    }

    // Class destructor
    ~AntennaBufferDataContainer() {
        for(unsigned i = 0; i < nof_tiles; i++)
            free(antenna_buffer_data[i].data);
        free(antenna_buffer_data);
    }

public:

    // Set callback function
    void setCallback(DataCallbackDynamic callback) {
        this->callback = callback;
    }

    void set_metadata(unsigned int tile_index, uint32_t packet_counter, uint64_t payload_length, uint64_t sync_time, 
                    uint64_t timestamp, uint16_t station_id, uint8_t  fpga_id, uint64_t payload_offset, uint8_t antenna_0_id, 
                    uint8_t antenna_1_id, uint8_t antenna_2_id, uint8_t antenna_3_id, uint8_t nof_included_antennas) {

        unsigned int packet_index = metadata[tile_index].nof_packets % 2048;
        metadata[tile_index].packet_counter[packet_index] = packet_counter;
        metadata[tile_index].payload_length = payload_length;
        metadata[tile_index].sync_time[packet_index] = sync_time;
        metadata[tile_index].timestamp[packet_index] = timestamp;
        metadata[tile_index].station_id = station_id;
        metadata[tile_index].fpga_id[packet_index] = fpga_id;
        metadata[tile_index].payload_offset = payload_offset;
        metadata[tile_index].antenna_0_id = antenna_0_id;
        metadata[tile_index].antenna_1_id = antenna_1_id; 
        metadata[tile_index].antenna_2_id = antenna_2_id; 
        metadata[tile_index].antenna_3_id = antenna_3_id;
        metadata[tile_index].nof_included_antennas = nof_included_antennas;
    }

    // Add data to buffer
    void add_data(uint32_t packet_counter, uint64_t payload_length, uint64_t sync_time, uint64_t timestamp_field, 
                uint16_t station_id, uint64_t payload_offset, uint8_t antenna_0_id, uint8_t antenna_1_id, 
                uint8_t antenna_2_id, uint8_t antenna_3_id, uint8_t nof_included_antennas, T* data_ptr, 
                uint16_t tile, uint32_t start_sample_index, uint32_t samples, double timestamp, uint8_t fpga_id) {

        // Get current tile index
        unsigned int tile_index;
        if (tile_map.find(tile) != tile_map.end())
            tile_index = tile_map[tile];
        else {
            tile_index = (unsigned int) tile_map.size();

            if (tile_index == nof_tiles) {
                LOG(WARN, "Cannot process tile %d, channel consumer configured for %d tiles", tile, nof_tiles);
                return;
            }

            tile_map[tile] = tile_index;
            antenna_buffer_data[tile_index].tile = tile;
            metadata[tile_index].tile_id = tile;
        }

        // Copy packet content to buffer
        // Packet data is in groups of 4 samples, each with nof_pols
        // So antennas have a stride of 4 * nof_pols * sizeof(T), with alternating antennas
        for(unsigned a = 0; a < antennas_per_fpga; a++)
        {
            T* dst_ptr = antenna_buffer_data[tile_index].data +
                    ((antennas_per_fpga * fpga_id + a) * nof_samples + start_sample_index) * nof_pols;

            for(unsigned s = 0; s < samples; s+=4)
            {
                memcpy(dst_ptr,
                       data_ptr + (s * antennas_per_fpga + a * 4) * nof_pols,
                       nof_pols * 4 * sizeof(T));
                dst_ptr += 4 * nof_pols;
            }
        }

        // Update timing
        if (this->timestamp > timestamp)
            this->timestamp = timestamp;

        // Update number of packets in container
        this->nof_packets++;

        set_metadata(tile_index, packet_counter, payload_length, sync_time, 
        timestamp_field, station_id, fpga_id, payload_offset, antenna_0_id, 
        antenna_1_id, antenna_2_id, antenna_3_id, nof_included_antennas);

        metadata[tile_index].nof_packets++;
    }

    // Clear buffer and antenna information
    void clear() {
        // Clear buffer, set all content to 0
        for (unsigned i = 0; i < nof_tiles; i++){
            memset(antenna_buffer_data[i].data, 0, nof_antennas * nof_pols * nof_samples);
            metadata[i].nof_packets = 0;
        }
        
        timestamp = DBL_MAX;
        this->nof_packets=0;

    }

    // Push data to callback
    void persist_container() {

        // If a callback is defined, call it and return
        if (callback == nullptr) {
            clear();
            LOG(WARN, "No callback for antenna buffer data defined");
            return;
        }

        // Call callback for each tile
        for(unsigned i = 0; i < nof_tiles; i++)
            callback((uint32_t *) antenna_buffer_data[i].data, timestamp,
                    static_cast<void *>(&metadata[i]));
        clear();
    }

public:
    uint32_t nof_packets = 0;
private:
    // Parameters
    uint16_t nof_tiles;
    uint16_t nof_antennas;
    uint16_t antennas_per_fpga;
    uint32_t nof_samples;
    uint8_t  nof_pols;

    // Tile map
    std::unordered_map<uint16_t, unsigned int> tile_map;

    // Timestamp
    double timestamp = DBL_MAX;

    // Data container
    AntennaBufferStructure *antenna_buffer_data;
    AntennaBufferMetadata *metadata;

    // Callback function
    DataCallbackDynamic callback = nullptr;

};

// ----------------- Antenna Buffer data consumer -------------------------

class AntennaBuffer: public DataConsumer {

public:
    // Override setDataCallback
    void setCallback(DataCallbackDynamic callback) override;

    // Initialise consumer
    bool initialiseConsumer(json configuration) override;

protected:
    // Packet filtering funtion to be passed to network thread
    inline bool packetFilter(unsigned char* udp_packet) override;

    // Grab SPEAD packet from buffer and process
    bool processPacket() override;

    // Function called when a burst stream capture has finished
    void onStreamEnd() override;

    // Override clean up methode
    void cleanUp() override;

private:
    AntennaBufferDataContainer<uint8_t> **containers = nullptr;
    unsigned nof_containers = 4;
    unsigned current_container = 0;
    unsigned current_buffer = 0;

    int current_packet_index = -1;

    // Antenna information object
    unsigned not_received_samples = 0;
    unsigned nof_required_samples = 0;

    double timestamp_scale = 1 / 800.0e6;

    // Data setup
    uint16_t nof_antennas = 0;
    uint8_t nof_pols = 0;
    uint16_t nof_tiles = 0;
    uint32_t nof_samples = 0;
};

// Expose class factory for AntennaBufferData
extern "C" DataConsumer *antennabuffer() { return new AntennaBuffer; }

#endif //AAVS_DAQ_ANTENNABUFFER_H
