//
// Created by lessju on 24/11/17.
//

#ifndef AAVS_DAQ_STATIONDATARAW_H
#define AAVS_DAQ_STATIONDATARAW_H

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
struct StationRawBuffer
{
    double     ref_time;      // The reference time of the second contained in the buffer
    int        sample_index;  // Index to be used to determine buffer boundaries
    bool       ready;         // Specifies whether the buffer is ready to be processed
    uint32_t   sample_offset; // Sample offset from beginning of buffer
    uint32_t   nof_packets;   // Number of packets
    uint32_t   nof_samples;   // Number of samples in buffer
    uint32_t   seq_number;    // Sequential number identifying the buffer within the stream
    uint32_t   frequency;     // Smallest frequency in buffer
    uint16_t   *data;         // Data
    std::mutex *mutex;        // Mutex lock for this buffer
};

// Callback data structure
typedef struct raw_station_metadata {
    unsigned frequency;        // Start channel frequency
    unsigned nof_packets;      // Number of packets in buffer
    unsigned buffer_counter;   // Buffer number
    unsigned start_sample_index; // Start sample from beginning of buffer
} RawStationMetadata;

class StationRawDoubleBuffer {

public:
    // Default constructor
    StationRawDoubleBuffer(uint16_t start_channel, uint32_t nof_samples, uint32_t nof_channels,
                           uint8_t nof_pols, bool transpose=true, uint8_t nbuffers = 4);

    // Class destructor
    ~StationRawDoubleBuffer();

    // Write data to buffer
    void write_data(uint32_t samples, uint32_t channel, uint64_t packet_counter,
                    uint16_t *data_ptr, double timestamp, uint32_t frequency,
		    unsigned start_sample_offset);

    // Read buffer
    StationRawBuffer* read_buffer();

    // Ready from buffer, mark as processed
    void release_buffer();

    // Clear double buffer
    void clear(int index);

private:

    inline void process_data(int producer_index, uint64_t packet_counter, uint32_t samples,
		             unsigned start_sample_offset,
                             uint32_t channel, uint16_t *data_ptr, double timestamp, uint32_t frequency);

private:
    // The data structure which will hold the buffer elements
    StationRawBuffer *double_buffer;

    // Double buffer parameters
    uint16_t start_channel; // Start channel
    uint32_t nof_samples;   // Total number of samples
    uint32_t nof_channels;  // Number of channels
    uint8_t nof_pols;       // Number of polarisations
    uint8_t  nof_buffers;   // Number of buffers in buffering system
    bool transpose;         // Flag determining whether the data should be transposed

    // Producer and consumer pointers, specifying which buffer index to use
    // These are declared as volatile so that they are not optimized into registers
    volatile int producer;
    volatile int consumer;

    volatile uint32_t buffer_counter = 0; // Counter representing current buffer

    // Timing variables
    struct timespec tim, tim2;
};

// -----------------------------------------------------------------------------

// Class which implements a separate thread for persisting station data
class StationRawPersister: public RealTimeThread
{

public:
    // Class constructor
    explicit StationRawPersister(StationRawDoubleBuffer *double_buffer)
    { this -> double_buffer = double_buffer; }

    // Set callback
    void setCallback(DataCallbackDynamic callback)
    {
        this -> callback = callback;
    }

protected:

    // Main thread event loop
    void threadEntry() override;

private:
    // Pointer to double buffer
    StationRawDoubleBuffer *double_buffer;

    // Callback
    DataCallbackDynamic callback = nullptr;
};

// -----------------------------------------------------------------------------

// This class is responsible for consuming station beam SPEAD packets coming out of TPMs
class StationRawData: public DataConsumer
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

    // Pointer to Double Buffer
    StationRawDoubleBuffer *double_buffer = nullptr;

    // Pointer to station persister
    StationRawPersister *persister = nullptr;

    // Internal bookkeeping
    unsigned long rollover_counter = 0;
    unsigned long timestamp_rollover = 0;

    // Data setup
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t start_channel = 0;       // Channel to save
    uint16_t nof_channels = 1;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples
    bool transpose = true;            // Transpose samples when writing to buffer
    double capture_start_time = -1;      // Capture start time in Unix epoch time

};

// Expose class factory for raw station data
extern "C" DataConsumer *stationdataraw() { return new StationRawData; }

#endif //AAVS_DAQ_STATIONDATARAW_H
