//
// Created by lessju on 24/11/17.
//

#ifndef AAVS_DAQ_STATIONDATA_H
#define AAVS_DAQ_STATIONDATA_H

// ----------------------- Station Data Container and Helpers ---------------------------------

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <unordered_map>
#include <mutex>

#include "Utils.h"
#include "DAQ.h"

/* This class implements a double buffering system */

// Represents a single buffer in the double (or more) buffering system
struct StationBuffer
{
    double     ref_time;      // The reference time of the second contained in the buffer
    uint64_t   index;         // Index to be used to determine buffer boundaries
    bool       ready;         // Specifies whether the buffer is ready to be processed
    uint32_t   nof_packets;   // Number of packets
    uint32_t   nof_saturations;   // Number of packets
    uint16_t   nof_channels;  // Number of channels in buffer
    uint32_t   nof_samples;   // Number of samples in buffer
    uint32_t   *read_samples;  //Number of actual samples per channel in the buffer
    double     *integrators;  // Integrators
    std::mutex *mutex;        // Mutex lock for this buffer
};

class StationDoubleBuffer
{
    // Structure of station data format
    typedef struct _complex8_t
    {
        char real;
        char imag;
    } complex8_t;

public:
    // Default constructor
    StationDoubleBuffer(uint16_t nof_channels, uint32_t nof_samples, uint8_t nof_pols, uint8_t nbuffers = 6);

    // Class destructor
    ~StationDoubleBuffer();

    // Write data to buffer
    void write_data(uint16_t channel_id, uint32_t samples, uint64_t packet_counter,
                    uint16_t *data_ptr, double timestamp);

    // Read buffer
    StationBuffer* read_buffer();

    // Ready from buffer, mark as processed
    void release_buffer();

    // Clear double buffer
    void clear();

private:

    inline void process_data(int producer_index, uint16_t channel, uint32_t samples,
                             uint16_t *data_ptr, double timestamp);
    uint32_t get_abs(char value);

private:
    // The data structure which will hold the buffer elements
    StationBuffer *double_buffer;

    // Double buffer parameters
    uint32_t nof_samples;   // Total number of samples
    uint16_t nof_channels;  // Total number of channels
    uint8_t nof_pols;      // Number of polarisations
    uint8_t  nof_buffers; // Number of buffers in buffering system
    double inv_nof_samples;  // Inverse of number of samples

    // Producer and consumer pointers, specifying which buffer index to use
    // These are declared as volatile so tha they are not optimsed into registers
    volatile int producer;
    volatile int consumer;

    // Timing variables
    struct timespec tim, tim2;
};

// -----------------------------------------------------------------------------

// Class which implements a separate thread for persisting station data
class StationPersister: public RealTimeThread
{

public:
    // Class constructor
    explicit StationPersister(StationDoubleBuffer *double_buffer)
    { this -> double_buffer = double_buffer; }

    // Set callback (provided by CorrelatorData)
    void setCallback(DataCallback callback)
    {
        this -> callback = callback;
    }

protected:

    // Main thread event loop
    void threadEntry() override;

private:
    // Pointer to double buffer
    StationDoubleBuffer *double_buffer;

    // Callback
    DataCallback callback = nullptr;
};

// -----------------------------------------------------------------------------

// This class is responsible for consuming station beam SPEAD packets coming out of TPMs
class StationData: public DataConsumer
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

    // Pointer to Double Buffer
    StationDoubleBuffer *double_buffer = nullptr;

    // Pointer to station persister
    StationPersister *persister = nullptr;

    // Internal book keeping
    unsigned long rollover_counter = 0;
    unsigned long timestamp_rollover = 0;

    // Data setup
    uint16_t nof_antennas = 0;        // Number of antennas per tile
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t nof_tiles = 0;           // Number of tiles
    uint16_t nof_channels = 0;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples

};

// Expose class factory for birales
extern "C" DataConsumer *stationdata() { return new StationData; }

#endif //AAVS_DAQ_STATIONDATA_H
