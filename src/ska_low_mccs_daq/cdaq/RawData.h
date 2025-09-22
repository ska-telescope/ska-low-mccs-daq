//
// Created by Alessio Magro on 14/05/2018.
//

#ifndef AAVS_DAQ_RAWDATA_H
#define AAVS_DAQ_RAWDATA_H

#include <cstdint>
#include <unordered_map>

#include "DAQ.h"

// ----------------------- Antenna Data Container and Helpers ---------------------------------

// Class which will hold the raw antenna data
template <class T> class AntennaDataContainer
{
public:

    struct AntennaStructure
    {
        double   timestamp;
        uint32_t first_sample_index;
        T*       data;
        uint16_t tile;
    };

    struct AdcMetadata {
        uint64_t nof_packets=0;
        uint32_t packet_counter[128];
        uint64_t payload_length;
        uint64_t sync_time[128];
        uint64_t timestamp[128];
        uint8_t start_antenna_id[128];
        uint8_t nof_antennas;
        uint8_t tile_id;
        uint16_t station_id;
        uint8_t  fpga_id[128];
        uint64_t payload_offset;
    };

    // Class constructor
    AntennaDataContainer(uint16_t nof_tiles, uint16_t nof_antennas,
                         uint32_t nof_samples, uint8_t nof_pols):
            nof_tiles(nof_tiles), nof_samples(nof_samples),
            nof_antennas(nof_antennas), nof_pols(nof_pols)
    {
        // Allocate buffers
        antenna_data = (AntennaStructure *) malloc(nof_tiles * sizeof(AntennaStructure));
        metadata = (AdcMetadata *) malloc(nof_tiles * sizeof(AdcMetadata));
        for (unsigned i = 0; i < nof_tiles; i++)
            antenna_data[i].data = (T *) malloc(nof_antennas * nof_samples * nof_pols * sizeof(T));

        // Reset antenna data and information
        clear();

        // Reserve required number of bucket in map
        tile_map.reserve(nof_tiles);
    }

    // Class destructor
    ~AntennaDataContainer()
    {
        for(unsigned i = 0; i < nof_tiles; i++)
            free(antenna_data[i].data);
        free(antenna_data);
        free(metadata);
    }

public:
    // Set callback function
    void setCallback(DataCallbackDynamic callback)
    {
        this -> callback = callback;
    }

    void set_metadata(unsigned int tile_index, uint32_t packet_counter, uint64_t payload_length, uint64_t sync_time, 
        uint64_t timestamp, uint16_t station_id, uint8_t  fpga_id, uint64_t payload_offset, 
        uint8_t tile_id, uint8_t start_antenna_id, uint8_t nof_included_antennas){
            unsigned int packet_index = metadata[tile_index].nof_packets % 128;
            metadata[tile_index].packet_counter[packet_index] = packet_counter;
            metadata[tile_index].payload_length = payload_length;
            metadata[tile_index].sync_time[packet_index] = sync_time;
            metadata[tile_index].timestamp[packet_index] = timestamp;
            metadata[tile_index].station_id = station_id;
            metadata[tile_index].fpga_id[packet_index] = fpga_id;
            metadata[tile_index].payload_offset = payload_offset;
            metadata[tile_index].tile_id = tile_id;
            metadata[tile_index].start_antenna_id[packet_index] = start_antenna_id;
            metadata[tile_index].nof_antennas = nof_included_antennas;
        }

    // Add data to buffer
    void add_data(uint32_t packet_counter, uint64_t payload_length, uint64_t sync_time, 
        uint64_t timestamp_field, uint16_t station_id, uint8_t fpga_id, uint64_t payload_offset, 
        uint8_t tile, uint8_t start_antenna, uint32_t start_sample_index, uint32_t nsamp, 
        uint8_t nof_included_antennas, T *data_ptr, double timestamp)
    {
        // Get current tile index
        unsigned int tile_index = 0;
        if (tile_map.find(tile) != tile_map.end())
            tile_index = tile_map[tile];
        else {
            tile_index = (unsigned int) tile_map.size();

            if (tile_index == nof_tiles) {
                fprintf(stderr, "Cannot process tile %d, antenna consumer configured for %d tiles\n", tile, nof_tiles);
                return;
            }

            tile_map[tile] = tile_index;
            antenna_data[tile_index].tile = tile;
            
        }
        // Burst raw data
        if (nof_included_antennas == 1)
        {
            // Get pointer to buffer location where data will be placed
            T* ptr = antenna_data[tile_index].data + start_antenna * nof_samples * nof_pols +
                     start_sample_index * nof_pols;

            for (unsigned i = 0; i < nsamp * nof_pols; i++)
            {
                *ptr = *data_ptr;
                ptr++;
                data_ptr++;
            }
        }
        else
        {
            // Synchronised raw data
            for(unsigned a = 0; a < nof_included_antennas; a++)
            {
                T* ptr = antenna_data[tile_index].data + (start_antenna + a) * nof_samples * nof_pols +
                         start_sample_index * nof_pols;

                for(unsigned i = 0; i < nsamp ; i++)
                {
                    *ptr = data_ptr[i * nof_included_antennas * nof_pols + a * nof_pols];
                    ptr++;
                    *ptr = data_ptr[i * nof_included_antennas * nof_pols + a * nof_pols + 1];
                    ptr++;
                }

            }
        }

        // Update timing
        if (antenna_data[tile_index].first_sample_index > start_sample_index)
        {
            antenna_data[tile_index].timestamp = timestamp;
            antenna_data[tile_index].first_sample_index = start_sample_index;
        }

        set_metadata(tile_index, packet_counter, payload_length, sync_time, timestamp_field, 
        station_id, fpga_id, payload_offset, tile, start_antenna, nof_included_antennas);

        metadata[tile_index].nof_packets++;
    }

    //  Clear buffer and antenna information
    void clear()
    {
        // Clear buffer, set all content to 0
        for(unsigned i = 0; i < nof_tiles; i++) {
            memset(antenna_data[i].data, 0, nof_antennas * nof_samples * nof_pols * sizeof(T));
            metadata[i].nof_packets=0;
            // Clear AntennaStructure
            antenna_data[i].first_sample_index = UINT32_MAX;
            antenna_data[i].timestamp = 0;
        }
    }

    // Save data to disk
    void persist_container()
    {
        // If a callback is defined, call it and return
        if (this->callback != NULL)
        {
            // Call callback for every tile (if buffer has some content)
            for(unsigned i = 0; i < nof_tiles; i++)
                if (antenna_data[i].first_sample_index != UINT32_MAX)
                    callback((int8_t *) antenna_data[i].data, antenna_data[i].timestamp,
                            static_cast<void *>(&metadata[i]));
                            
            // Clear buffer
            clear();
            return;
        }

        clear();
        LOG(WARN, "No callback for antenna data defined\n");
    }


private:
    // Parameters
    uint16_t nof_tiles;
    uint16_t nof_antennas;
    uint32_t nof_samples;
    uint8_t  nof_pols;

    // Tile map
    std::unordered_map<uint16_t, unsigned int> tile_map;

    // Callback
    DataCallbackDynamic callback = nullptr;

    // Antenna data and info
    AntennaStructure *antenna_data;
    AdcMetadata *metadata;
};

// This class is responsible for consuming raw antenna SPEAD packets coming out of TPMs
class RawData: public DataConsumer {

public:

    // Override setDataCallbackDynamic
    void setCallback(DataCallbackDynamic callback) override;

    // Initialise consumer
    bool initialiseConsumer(json configuration) override;

protected:
    // Packet filtering function to be passed to network thread
    inline bool packetFilter(unsigned char* udp_packet) override;

    // Grab SPEAD packet from buffer and process
    bool processPacket() override;

    // Function called when a burst stream capture has finished
    void onStreamEnd() override;

    // Override clean up method
    void cleanUp() override;

private:

    // AntennaInformation object
    AntennaDataContainer<uint8_t> *container = nullptr;
    unsigned int nof_received_samples = 0;
    unsigned int nof_required_samples = 0;

    // Data setup
    uint16_t nof_antennas = 0;        // Number of antennas per tile
    uint32_t samples_per_buffer = 0;  // Number of samples per buffer
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t nof_tiles = 0;           // Number of tiles
    uint16_t nof_channels = 0;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples

};

// Expose class factory for birales
extern "C" DataConsumer *rawdata() { return new RawData; }

#endif //AAVS_DAQ_RAWDATA_H
