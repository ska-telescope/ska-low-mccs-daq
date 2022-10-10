//
// Created by Alessio Magro on 14/05/2018.
//

#ifndef AAVS_DAQ_CHANNELISEDDATA_H
#define AAVS_DAQ_CHANNELISEDDATA_H

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

// ----------------------- Channelised Data Container and Helpers ---------------------------------

// Class which will hold the raw antenna data
template <class T> class ChannelDataContainer
{
public:

    struct ChannelStructure
    {
        uint16_t tile;
        T*       data;
    };

    // Class constructor
    ChannelDataContainer(uint16_t nof_tiles, uint16_t nof_antennas, uint32_t nof_samples,
                         uint16_t nof_channels, uint8_t nof_pols)
    {
        // Set local variables
        this -> nof_antennas = nof_antennas;
        this -> nof_samples  = nof_samples;
        this -> nof_tiles    = nof_tiles;
        this -> nof_pols     = nof_pols;
        this -> nof_channels = nof_channels;

        size_t malloc_size = nof_channels * nof_antennas * nof_pols * (size_t) nof_samples * sizeof(T);

        // Allocate buffer
        channel_data = (ChannelStructure *) malloc(nof_tiles * sizeof(ChannelStructure));
        for(unsigned i = 0; i < nof_tiles; i++) {
            allocate_aligned((void **) &(channel_data[i].data), (size_t) CACHE_ALIGNMENT, malloc_size);

            // Lock memory
            if (mlock(channel_data[i].data, malloc_size) == -1)
                perror("Could not lock memory");
        }

        // Reset antenna information
        clear();

        // Reserve required number of bucket in map
        tile_map.reserve(nof_tiles);
    }

    // Class Destructor
    ~ChannelDataContainer()
    {
        for(unsigned i = 0; i < nof_tiles; i++)
            free(channel_data[i].data);
        free(channel_data);
    }

public:

    // Set callback function
    void setCallback(DataCallback callback)
    {
        this -> callback = callback;
    }

    // Add data to buffer
    void add_data(uint16_t tile, uint16_t channel, uint32_t start_sample_index, uint32_t samples,
                  uint16_t start_antenna_id, T *data_ptr, double timestamp, uint16_t included_channels,
                  uint16_t nof_included_antennas, uint32_t cont_channel_id = 0)
    {
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
            channel_data[tile_index].tile = tile;
        }

        // Copy packet content to buffer
        T *ptr = channel_data[tile_index].data;
        for (unsigned i = 0; i < included_channels; i++)
            for (unsigned j = 0; j < samples; j++)
                for (unsigned k = 0; k < nof_included_antennas; k++)
                {
                    long dst_index = (channel + i) * nof_samples * nof_antennas * nof_pols +
                                    (start_sample_index + j) * nof_antennas * nof_pols +
                                    (start_antenna_id + k) * nof_pols;

                    long src_index = i * samples * nof_included_antennas * nof_pols +
                                     j * nof_included_antennas * nof_pols +
                                     k * nof_pols;

                    for(unsigned l = 0; l < nof_pols; l++)
                        ptr[dst_index + l] = data_ptr[src_index + l];
                }

        // Update timing
        if (this->timestamp > timestamp) {
            this->timestamp = timestamp;
            this->cont_channel_id = cont_channel_id;
        }

        // Update number of packets in container
        nof_packets++;
    }

    //  Clear buffer and antenna information
    void clear()
    {
        // Clear buffer, set all content to 0
        for(unsigned i = 0; i < nof_tiles; i++) {
            memset(channel_data[i].data, 0, nof_channels * nof_samples * nof_antennas * nof_pols * sizeof(T));
        }

        // Clear number of packets
        this->timestamp = DBL_MAX;
        nof_packets = 0;
    }

    // Save data to disk
    void persist_container()
    {
        // If a callback is defined, call it and return
        if (this->callback != NULL)
        {
            // Call callback for every tile (if buffer has some content)
            for(unsigned i = 0; i < nof_tiles; i++)
                    callback((uint32_t *) channel_data[i].data, this->timestamp,
                             channel_data[i].tile, cont_channel_id);
            clear();
            return;
        }

        clear();
        LOG(WARN, "No callback for channel data defined");
    }

public:
    // Number of process packets
    uint32_t nof_packets = 0;

private:
    // Parameters
    uint16_t nof_tiles;
    uint16_t nof_antennas;
    uint32_t nof_samples;
    uint16_t nof_channels;
    uint8_t  nof_pols;
    uint32_t cont_channel_id = 0;

    // Tile map
    std::unordered_map<uint16_t, unsigned int> tile_map;

    // Timestamp
    double timestamp = DBL_MAX;

    // Data container
    ChannelStructure *channel_data;

    // Callback function
    DataCallback callback = nullptr;
};

// This class is responsible for consuming channel SPEAD packets coming out of TPMs
class ChannelisedData : public DataConsumer
{

public:

    // Override setDataCallback
    void setCallback(DataCallback callback) override;

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
    ChannelDataContainer<uint16_t> *container;
    uint32_t num_packets = 0;

    // Data setup
    uint16_t nof_antennas = 0;        // Number of antennas per tile
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t nof_tiles = 0;           // Number of tiles
    uint16_t nof_channels = 0;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples
};

// This class is responsible for consuming continuous channel SPEAD packets coming out of TPMs
class ContinuousChannelisedData : public DataConsumer
{
public:

    // Override setDataCallback
    void setCallback(DataCallback callback) override;

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
    ChannelDataContainer<uint16_t> **containers = nullptr;
    unsigned int nof_containers = 4;
    unsigned int nof_buffer_skips = 0;
    unsigned int current_container = 0;
    unsigned int current_buffer = 0;

    double reference_time = 0;
    uint32_t reference_counter = 0;
    uint32_t rollover_counter = 0;
    uint32_t num_packets = 0;

    // Data setup
    uint16_t nof_antennas = 0;        // Number of antennas per tile
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t nof_tiles = 0;           // Number of tiles
    uint16_t nof_channels = 0;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples
    double start_time = -1;           // Acquisition start time
};

// This class is responsible for consuming integrated channel SPEAD packets coming out of TPMs
class IntegratedChannelisedData : public DataConsumer
{
public:

    // Override setDataCallback
    void setCallback(DataCallback callback) override;

    // Initialise consumer
    bool initialiseConsumer(json configuration) override;

protected:
    // Packet filtering function to be passed to network thread
    inline bool packetFilter(unsigned char* udp_packet) override;

    // Grab SPEAD packet from buffer and process
    bool processPacket() override;

    // Override clean up method
    void cleanUp() override;

private:

    // AntennaInformation object
    ChannelDataContainer<uint16_t> *container;
    uint32_t num_packets = 0;

    // Data setup
    uint16_t nof_antennas = 0;        // Number of antennas per tile
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t nof_tiles = 0;           // Number of tiles
    uint16_t nof_channels = 0;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples

};

// Expose class factory for ChannelisedData
extern "C" DataConsumer *burstchannel() { return new ChannelisedData; }
extern "C" DataConsumer *continuouschannel() { return new ContinuousChannelisedData; }
extern "C" DataConsumer *integratedchannel() { return new IntegratedChannelisedData; }

#endif //AAVS_DAQ_CHANNELISEDDATA_H
