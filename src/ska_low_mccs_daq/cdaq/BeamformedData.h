//
// Created by Alessio Magro on 14/05/2018.
//

#ifndef AAVS_DAQ_BEAMFORMEDDATA_H
#define AAVS_DAQ_BEAMFORMEDDATA_H

#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#include <sstream>
#include <cmath>
#include <netinet/in.h>
#include <unordered_map>

#include "DAQ.h"

// ----------------------- Beam Data Container and Helpers ---------------------------------
// Class which will hold the raw antenna data
template <class T> class IntegratedBeamDataContainer
{
public:

    struct BeamStructure
    {
        double   timestamp;
        uint32_t first_sample_index;
        T*       data;
        uint8_t tile;
    };

    struct BeamMetadata
    {
        uint64_t nof_packets=0;
        uint32_t packet_counter[128]=0;
        uint64_t payload_length;
        uint64_t sync_time[128] = 0;
        uint64_t timestamp[128] = 0;
        uint8_t beam_id[128] = 0;
        uint8_t tile_id;
        uint16_t station_id;
        uint16_t nof_contributing_antennas;
        uint32_t payload_offset;
        uint16_t start_channel_id[128] = 0;
        uint16_t nof_included_channels;
    };

    // Class constructor
    IntegratedBeamDataContainer(uint16_t nof_tiles,
                      uint32_t nof_beams,
                      uint32_t nof_samples,
                      uint16_t nof_channels,
                      uint8_t nof_pols)
    {
        // Set local variables
        this -> nof_samples  = nof_samples;
        this -> nof_tiles    = nof_tiles;
        this -> nof_beams    = nof_beams;
        this -> nof_channels = nof_channels;
        this -> nof_pols     = nof_pols;

        // Allocate buffer
        beam_data = (BeamStructure *) malloc(nof_tiles * sizeof(BeamStructure));
        metadata = (BeamMetadata *) malloc(nof_tiles * sizeof(BeamMetadata));

        for(unsigned i = 0; i < nof_tiles; i++)
            beam_data[i].data = (T *) malloc(nof_beams * nof_pols * nof_samples * nof_channels * sizeof(T));

        // Reset beam data and information
        clear();

        // Reserve required number of bucket in map
        tile_map.reserve(nof_tiles);
    }

    // Class destructor
    ~IntegratedBeamDataContainer()
    {
        for(unsigned i = 0; i < nof_tiles; i++)
            free(beam_data[i].data);
        free(beam_data);
    }

public:
    // Set callback function
    void setCallback(DataCallbackDynamic callback)
    {
        this -> callback = callback;
    }

    void set_metadata(unsigned int tile_index, uint32_t packet_counter, uint64_t payload_length, uint64_t sync_time, 
        uint64_t timestamp, uint16_t station_id, uint8_t beam_id, uint32_t payload_offset, 
        uint16_t start_channel_id, uint16_t nof_included_channels, uint16_t nof_contributing_antennas)
    {
        unsigned int packet_index = metadata[tile_index].nof_packets % 128;
        metadata[tile_index].packet_counter[packet_index] = packet_counter;
        metadata[tile_index].payload_length = payload_length;
        metadata[tile_index].sync_time[packet_index] = sync_time;
        metadata[tile_index].timestamp[packet_index] = timestamp;
        metadata[tile_index].station_id = station_id;
        metadata[tile_index].beam_id[packet_index] = beam_id;
        metadata[tile_index].nof_included_channels = nof_included_channels;
        metadata[tile_index].payload_offset = payload_offset;
        metadata[tile_index].start_channel_id[packet_index] = start_channel_id;
        metadata[tile_index].nof_contributing_antennas = nof_contributing_antennas;
    }

    // Add data to buffer
    void add_data(uint32_t packet_counter, uint64_t payload_length, uint64_t sync_time, 
        uint64_t timestamp_field, uint16_t station_id, uint16_t nof_contributing_antennas, 
        uint32_t payload_offset, uint8_t tile, uint8_t beam_id, uint16_t start_channel_id, 
        uint16_t nof_included_channels, uint32_t start_sample_index, uint32_t samples, 
        T* data_ptr, double timestamp)

    {
        // Get current tile index
        unsigned int tile_index = 0;
        if (tile_map.find(tile) != tile_map.end())
            tile_index = tile_map[tile];
        else {
            tile_index = (unsigned int) tile_map.size();

            if (tile_index == nof_tiles) {
                LOG(WARN, "Cannot process tile %d, beam consumer configured for %d tiles", tile, nof_tiles);
                return;
            }

            tile_map[tile] = tile_index;
            beam_data[tile_index].tile = tile;
            metadata[tile_index].tile_id = tile;
        }

        // Get pointer to buffer location where data will be placed
        T* pol0_ptr = beam_data[tile_index].data + beam_id * nof_channels * nof_samples * nof_pols +
                      start_sample_index * samples * nof_channels;
        T* pol1_ptr = beam_data[tile_index].data + beam_id * nof_channels * nof_samples * nof_pols +
                      start_sample_index * samples * nof_channels + nof_channels * nof_samples;

        // Copy data to buffer
        for(unsigned i = 0; i < samples; i++)
            for(unsigned j = 0; j < nof_included_channels; j++)
            {
                unsigned int index = i  * nof_channels + start_channel_id + 2 * j;
                pol0_ptr[index] = data_ptr[i * nof_included_channels + j * 2];
                pol1_ptr[index] = data_ptr[i * nof_included_channels + j * 2 + 1];
            }

        // Update timing
        if (beam_data[tile_index].first_sample_index > start_sample_index)
        {
            beam_data[tile_index].timestamp = timestamp;
            beam_data[tile_index].first_sample_index = start_sample_index;
        }
        set_metadata(tile_index, packet_counter, payload_length, sync_time, 
            timestamp_field, station_id, beam_id, payload_offset, start_channel_id,
            nof_included_channels, nof_contributing_antennas);
        metadata[tile_index].nof_packets++;
    }

    //  Clear buffer and antenna information
    void clear()
    {
        // Clear buffer, set all content to 0
        for(unsigned i = 0; i < nof_tiles; i++) {
            memset(beam_data[i].data, 0, nof_beams * nof_pols * nof_channels * nof_samples * sizeof(T));

            // Clear BeamStructure
            beam_data[i].first_sample_index = UINT32_MAX;
            beam_data[i].timestamp = 0;
            metadata[i].nof_packets=0;
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
                if (beam_data[i].first_sample_index != UINT32_MAX)
                    callback((uint32_t *) beam_data[i].data, beam_data[i].timestamp,
                            static_cast<void *>(&metadata[i]));
            clear();
            return;
        }

        LOG(WARN, "No callback for beam data defined");
    }


private:
    // Parameters
    uint16_t nof_tiles;
    uint32_t nof_samples;
    uint16_t nof_channels;
    uint32_t nof_beams;
    uint8_t  nof_pols;


    // Tile map
    std::unordered_map<uint16_t, unsigned int> tile_map;

    // Beam data and info
    BeamStructure *beam_data;
    BeamMetadata *metadata;

    // Callback function
    DataCallbackDynamic callback = nullptr;
};

template <class T> class BurstBeamDataContainer
{
public:

    struct BeamStructure
    {
        double   timestamp;
        uint32_t first_sample_index;
        T*       data;
        uint16_t tile;
    };

    struct BeamMetadata
    {
        uint64_t nof_packets=0;
        uint32_t packet_counter[128] = 0;
        uint64_t payload_length;
        uint64_t sync_time[128] = 0;
        uint64_t timestamp[128] = 0;
        uint8_t beam_id[128] = 0;
        uint8_t tile_id;
        uint16_t station_id;
        uint16_t nof_contributing_antennas;
        uint32_t payload_offset;
        uint16_t start_channel_id[128] = 0;
        uint16_t nof_included_channels;
    };

    // Class constructor
    BurstBeamDataContainer(uint16_t nof_tiles,
                           uint32_t nof_samples,
                           uint16_t nof_channels,
                           uint8_t nof_pols)
    {
        // Set local variables
        this -> nof_samples  = nof_samples;
        this -> nof_tiles    = nof_tiles;
        this -> nof_channels = nof_channels;
        this -> nof_pols     = nof_pols;

        // Allocate buffer
        beam_data = (BeamStructure *) malloc(nof_tiles * sizeof(BeamStructure));
        metadata = (BeamMetadata *) malloc(nof_tiles * sizeof(BeamMetadata));

        for(unsigned i = 0; i < nof_tiles; i++)
            beam_data[i].data = (T *) malloc(nof_pols * nof_samples * nof_channels * sizeof(T));

        // Reset beam data and information
        clear();

        // Reserve required number of bucket in map
        tile_map.reserve(nof_tiles);
    }

    // Class destructor
    ~BurstBeamDataContainer()
    {
        for(unsigned i = 0; i < nof_tiles; i++)
            free(beam_data[i].data);
        free(beam_data);
    }

public:
    // Set callback function
    void setCallback(DataCallbackDynamic callback)
    {
        this -> callback = callback;
    }

    void set_metadata(unsigned int tile_index, uint32_t packet_counter, uint64_t payload_length, uint64_t sync_time, 
        uint64_t timestamp, uint16_t station_id, uint8_t beam_id, uint32_t payload_offset, 
        uint16_t start_channel_id, uint16_t nof_included_channels, uint16_t nof_contributing_antennas)
    {
        unsigned int packet_index = metadata[tile_index].nof_packets % 128;
        metadata[tile_index].packet_counter[packet_index] = packet_counter;
        metadata[tile_index].payload_length = payload_length;
        metadata[tile_index].sync_time[packet_index] = sync_time;
        metadata[tile_index].timestamp[packet_index] = timestamp;
        metadata[tile_index].station_id = station_id;
        metadata[tile_index].beam_id[packet_index] = beam_id;
        metadata[tile_index].nof_included_channels = nof_included_channels;
        metadata[tile_index].payload_offset = payload_offset;
        metadata[tile_index].start_channel_id[packet_index] = start_channel_id;
        metadata[tile_index].nof_contributing_antennas = nof_contributing_antennas;
    }

    // Add data to buffer
    void add_data(uint32_t packet_counter, uint64_t payload_length, uint64_t sync_time, uint64_t timestamp_field,
        uint8_t beam_id, uint16_t station_id, uint16_t nof_contributing_antennas, uint32_t payload_offset,
        uint16_t nof_included_channels, uint8_t tile, uint64_t offset, uint16_t start_channel_id, uint64_t size,  
        T* data_ptr, double timestamp)
    {   
        // Get current tile index
        unsigned int tile_index = 0;
        if (tile_map.find(tile) != tile_map.end())
            tile_index = tile_map[tile];
        else {
            tile_index = (unsigned int) tile_map.size();

            if (tile_index == nof_tiles) {
                LOG(WARN, "Cannot process tile %d, beam consumer configured for %d tiles", tile, nof_tiles);
                return;
            }

            tile_map[tile] = tile_index;
            beam_data[tile_index].tile = tile;
            metadata[tile_index].tile_id = tile;
        }

        T* ptr = beam_data[tile_index].data + 2 * offset / sizeof(T);
        for(unsigned i = 0; i < size ; i+=2) {
            ptr[(i + start_channel_id) * nof_pols]  = data_ptr[i];
            ptr[(i + start_channel_id) * nof_pols + 1] = data_ptr[i + 1];
        }

        // Update timing
        if (beam_data[tile_index].timestamp == 0 || beam_data[tile_index].timestamp > timestamp)
        {
            beam_data[tile_index].timestamp = timestamp;
            beam_data[tile_index].first_sample_index = 0;
        }
        set_metadata(tile_index, packet_counter, payload_length, sync_time, 
        timestamp_field, station_id, beam_id, payload_offset, start_channel_id,
        nof_included_channels, nof_contributing_antennas);
        metadata[tile_index].nof_packets++;
    }

    //  Clear buffer and antenna information
    void clear()
    {
        // Clear buffer, set all content to 0
        for(unsigned i = 0; i < nof_tiles; i++) {
            memset(beam_data[i].data, 0, nof_pols * nof_channels * nof_samples * sizeof(T));

            // Clear BeamStructure
            beam_data[i].first_sample_index = UINT32_MAX;
            beam_data[i].timestamp = 0;

            metadata[i].nof_packets=0;
        }
    }

    // Save data to disk
    void persist_container()
    {
        // If a callback is defined, call it and return
        if (this->callback != nullptr)
        {

            T *buffer = (T *) malloc(this->nof_channels * this->nof_samples * this->nof_pols * sizeof(T));

            // Call callback for every tile (if buffer has some content
            for(unsigned i = 0; i < nof_tiles; i++) {

                if (beam_data[i].first_sample_index != UINT32_MAX) {
                    // We need to reorder the buffer
                    for (unsigned s = 0; s < this->nof_samples; s++)
                        for (unsigned c = 0; c < this->nof_channels; c++) {
                            unsigned index = s * nof_channels * nof_pols + c * nof_pols;
                            buffer[s * nof_channels + c] = beam_data[i].data[index];
                            buffer[nof_channels * (nof_samples + s) + c] = beam_data[i].data[index + 1];
                        }

                    callback((uint32_t *) buffer, beam_data[i].timestamp,
                             static_cast<void *>(&metadata[i]));
                    memset(buffer, 0, this->nof_channels * this->nof_samples * this->nof_pols * sizeof(T));
                }
            }

            free(buffer);
            clear();
            return;
        }

        clear();
        LOG(WARN, "No callback for beam data defined");
    }


private:
    // Parameters
    uint16_t nof_tiles;
    uint32_t nof_samples;
    uint16_t nof_channels;
    uint8_t  nof_pols;

    // Tile map
    std::unordered_map<uint16_t, unsigned int> tile_map;

    // Beam data and info
    BeamStructure *beam_data;
    BeamMetadata *metadata;

    // Callback function
    DataCallbackDynamic callback = nullptr;
};


// This class is responsible for consuming beam SPEAD packets coming out of TPMs
class BeamformedData : public DataConsumer
{
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

    // Override cleanup method
    void cleanUp() override;

private:

    // BeamInformation object
    BurstBeamDataContainer<uint32_t> *container;

    // Number of received packets, used for integrate beam data mode
    uint16_t received_packets = 0;

    // Data setup
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t nof_tiles = 0;           // Number of tiles
    uint16_t nof_channels = 0;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples
};


// This class is responsible for consuming integrated beam SPEAD packets coming out of TPMs
class IntegratedBeamformedData : public DataConsumer
{
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

    // Override cleanup method
    void cleanUp() override;

private:

    // AntennaInformation object
    IntegratedBeamDataContainer<uint32_t> *container;

    // Number of received packets, used for integrate beam data mode
    uint16_t received_packets = 0;

    // Keep track of packet counter for buffering
    uint32_t saved_packet_counter = 0;

    // Data setup
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t nof_beams = 0;           // Number of beams
    uint16_t nof_tiles = 0;           // Number of tiles
    uint16_t nof_channels = 0;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples
};

// Expose class factory for ChannelisedData
extern "C" DataConsumer *burstbeam() { return new BeamformedData; }
extern "C" DataConsumer *integratedbeam() { return new IntegratedBeamformedData; }

#endif //AAVS_DAQ_BEAMFORMEDDATA_H
