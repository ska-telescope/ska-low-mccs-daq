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

struct ChannelMetadata
{
    uint8_t tile_id;
    uint32_t cont_channel_id;
    uint64_t nof_packets = 0;
    uint32_t packet_counter[2048];
    uint64_t payload_length;
    uint64_t sync_time;
    uint64_t timestamp[2048];
    uint16_t start_channel_id[2048];
    uint16_t start_antenna_id[2048];
    uint16_t nof_included_channels;
    uint16_t nof_included_antennas;
    uint16_t station_id;
    uint8_t  fpga_id[2048];
    uint32_t payload_offset;
};

// ----------------------- Channelised Data Container and Helpers ---------------------------------

// Class which will hold the channel data
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
        metadata = (ChannelMetadata *) malloc(nof_tiles * sizeof(ChannelMetadata));
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
        free(metadata);
    }

public:

    void set_metadata(uint64_t timestamp, uint32_t packet_counter, uint64_t sync_time, 
                    uint16_t station_id, uint32_t payload_offset, unsigned int tile_index, uint8_t fpga_id, 
                    uint16_t start_channel_id, uint32_t payload_length, uint16_t start_antenna_id,  
                    uint16_t nof_included_channels, uint16_t nof_included_antennas)
    {
        unsigned int i = metadata[tile_index].nof_packets % 2048;
        //The line above stops the DAQ from failing when it receives more than 2048 packets. 
        //In the case of a capture larger than 2048 packets,
        //the metadata is overwritten on a first-in first-out basis. 
        //The nof_packets field in the metadata should be helpful in finding out which
        //packet was received last in the case that nof_packets>2048.
        metadata[tile_index].packet_counter[i] = packet_counter;
        metadata[tile_index].cont_channel_id = this->cont_channel_id;
        metadata[tile_index].payload_length = payload_length;
        metadata[tile_index].sync_time = sync_time;
        metadata[tile_index].nof_included_channels = nof_included_channels;
        metadata[tile_index].nof_included_antennas =nof_included_antennas;
        metadata[tile_index].station_id = station_id;
        metadata[tile_index].payload_offset = payload_offset;
        metadata[tile_index].start_channel_id[i] = start_channel_id;
        metadata[tile_index].start_antenna_id[i] = start_antenna_id;
        metadata[tile_index].fpga_id[i] = fpga_id;
        metadata[tile_index].timestamp[i] = timestamp;
    }

    // Set callback function
    void setCallback(DataCallbackDynamic callback)
    {
        this->callback = callback;
    }

    // Add data to buffer
    void add_data(uint64_t timestamp_field, uint32_t packet_counter, uint64_t sync_time, uint16_t station_id, uint32_t payload_offset, 
                  uint8_t tile, uint8_t fpga_id, uint16_t channel, uint32_t start_sample_index, uint32_t samples,
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
            metadata[tile_index].tile_id = tile;
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

        set_metadata(timestamp_field, packet_counter, sync_time, station_id, 
                    payload_offset, tile_index, fpga_id, channel, samples*32, 
                    start_antenna_id, included_channels, nof_included_antennas);

        // Update number of packets in container
        this->nof_packets++;
        // Update number of packets in metadata
        metadata[tile_index].nof_packets++;
    }

    //  Clear buffer and channel information
    void clear()
    {
        // Clear buffer, set all content to 0
        for(unsigned i = 0; i < nof_tiles; i++) {
            metadata[i].nof_packets=0;
            memset(channel_data[i].data, 0, nof_channels * nof_samples * nof_antennas * nof_pols * sizeof(T));
        }

        // Clear number of packets
        this->timestamp = DBL_MAX;
        this->nof_packets = 0;
    }

    // Save data to disk
    void persist_container()
    {
        // If a callback is defined, call it and return
        if (this->callback != NULL)
        {
            // Call callback for every tile (if buffer has some content)
            for (unsigned i = 0; i < nof_tiles; i++)
            {
                if (metadata[i].nof_packets!=0)
                    callback((uint32_t *)channel_data[i].data, this->timestamp,
                            static_cast<void *>(&metadata[i]));
            }
            clear();
            return;
        }

        clear();
        LOG(WARN, "No callback for channel data defined");
    }

public:
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
    ChannelMetadata *metadata;

    // Callback function
    DataCallbackDynamic callback = nullptr;
};

// This class is responsible for consuming channel SPEAD packets coming out of TPMs
class ChannelisedData : public DataConsumer
{

public:

    // Override setDataCallback
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

    // Channel data container object
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

    // Channel data container object
    ChannelDataContainer<uint16_t> **containers_16bit = nullptr;
    ChannelDataContainer<uint32_t> **containers_32bit = nullptr;
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
    uint32_t bitwidth = 16;           // Number of bits per sample
    double sampling_time = 1.08e-6;   // Sampling time

};

// This class is responsible for consuming integrated channel SPEAD packets coming out of TPMs
class IntegratedChannelisedData : public DataConsumer
{
public:

    // Override setDataCallback
    void setCallback(DataCallbackDynamic callback) override;

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

    // Channel Data container object
    ChannelDataContainer<uint16_t> *container_16bit;
    ChannelDataContainer<uint32_t> *container_32bit;
    uint32_t num_packets = 0;

    // Data setup
    uint16_t nof_antennas = 0;        // Number of antennas per tile
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t nof_tiles = 0;           // Number of tiles
    uint16_t nof_channels = 0;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples
    uint16_t bitwidth = 16;           // Sample bitwidth
    double sampling_time = 1.08e-6;   // Sampling time

};

// Expose class factory for ChannelisedData
extern "C" DataConsumer *burstchannel() { return new ChannelisedData; }
extern "C" DataConsumer *continuouschannel() { return new ContinuousChannelisedData; }
extern "C" DataConsumer *integratedchannel() { return new IntegratedChannelisedData; }

#endif //AAVS_DAQ_CHANNELISEDDATA_H
