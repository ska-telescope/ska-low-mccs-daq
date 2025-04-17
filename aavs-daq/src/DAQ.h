//
// Created by Alessio Magro on 30/04/2018.
//

#ifndef _RECEIVER_H
#define _RECEIVER_H

#include <cstdarg>
#include <cstddef>
#include <vector>
#include <cstdint>
#include <string>

#include "RealTimeThread.h"
#include "NetworkReceiver.h"
#include "JSON.hpp"
#include "Utils.h"

using namespace std;

// Return type for most of the function calls, specifying whether the call
// succeeded or failed
typedef enum {
    SUCCESS = 0, FAILURE = -1,
    RECEIVER_UNINITIALISED = -2,
    CONSUMER_ALREADY_INITIALISED = -3,
    CONSUMER_NOT_INITIALISED = -4
} RESULT;

// Enumeration for logging levels
typedef enum {
    FATAL = 1,
    ERROR = 2,
    WARN = 3,
    INFO = 4,
    DEBUG = 5,
} LOG_LEVEL;

// Logger callback
typedef void (*Logger)(int level, const char * message);

//------------------------------- DATA CONSUMER --------------------------

// Define function pointer template for callbacks
// First iteration: Fixed number of arguments containing pointer to data, a timestamp and 2 value placeholders
typedef void (*DataCallback)(void * data, double timestamp, unsigned arg1, unsigned arg2);

// Second iteration: Pointer for data, a timestamp, and a pointer to a user-defined data type
typedef void (*DataCallbackDynamic)(void * data, double timestamp, void *userdata);

// Data Consumer abstract class
class DataConsumer: public RealTimeThread
{

public:
    // Default constructor
    DataConsumer()
    {
        // Allocate buffer for incoming packet (size if maximum SPEAD packet length)
        allocate_aligned((void **) &packet, static_cast<size_t>(CACHE_ALIGNMENT), packet_size);
    }

    // Consumer destructor
    ~DataConsumer() override
    {
        // Destroy ring buffer
        // delete ring_buffer;
    }

    // Set network daq_backend
    void setReceiver(NetworkReceiver *receiver) {this -> receiver = receiver;}

protected:

    // Packet filter which to be used to select which packet to place into
    // the ring buffer
    virtual inline bool packetFilter(unsigned char* udp_packet) { return false; }

    // Initialise ring buffer
    void initialiseRingBuffer(size_t packet_size, size_t nofcells)
    {  ring_buffer = new RingBuffer(packet_size, nofcells);  }

    // Grab SPEAD packet from buffer and process
    virtual bool processPacket() = 0;

    // Clean up method, called after stop finishes
    virtual void cleanUp()  { }

    // Thread entry function
    void threadEntry() override
    {
        // Assign filtering function and ring buffer instance to network daq_backend
        // Receiver can be NULL for testing
        if (receiver != nullptr) {
            this->consumerID = receiver->registerConsumer(ring_buffer,
                                                    std::bind(&DataConsumer::packetFilter, this, std::placeholders::_1));
        }

        // Set consumer as started
        stopped = false;

        // Infinite loop: process antenna data whenever it arrives
        while(!stop_consumer)
        {
            bool started_processing = false;

            // Continue processing packets until ring buffer times out
            while (!stop_consumer)
            {
                if (processPacket())
                    started_processing = true;
                else if (started_processing)
                    break;
            }

            // Detected stream end, call onStreamEnd
            if (!stop_consumer)
                onStreamEnd();
        }

        // Set consumer as stopped
        stopped = true;

        // Delete ring buffer
        delete ring_buffer;
    }

    // Function called when a burst stream capture has finished
    virtual void onStreamEnd() { }

public:

    // Initialise consumer using JSON document
    virtual bool initialiseConsumer(json configuration) = 0;

    // Set data callback (does nothing by default)
    virtual void setCallback(DataCallback callback) { }

    // Set data callback (does nothing by default)
    virtual void setCallback(DataCallbackDynamic callback) { }

    // Stop consumer
    void stopConsumer()
    {
        // Unregister consumer from network thread
        receiver->unregisterConsumer(consumerID);

        // Set stopping clause
        stop_consumer = true;

        // Wait for consumer to stop
        while (!stopped)
                __asm volatile ("pause" ::: "memory");

        // Call clean up method
        cleanUp();
    }

    // Check if consumer is running
    bool getIsRunning() { return is_running; }

    // Set consumer state
    void setIsRunning(bool value) { is_running = value; }

protected:
    // Pointer to ring buffer
    RingBuffer *ring_buffer = nullptr;

    // Local packet container
    uint8_t *packet = nullptr;

    // Pointer to network daq_backend
    NetworkReceiver *receiver = nullptr;

    // Consumer ID as assigned by the Network Thread
    int consumerID = 0;

    // Flag specifying whether consumer is running
    bool is_running = false;

    // Stopping clause
    volatile bool stopped = true;
    bool stop_consumer = false;

    // Packet size
    size_t   packet_size = 0;
};

// Types for class factories
typedef DataConsumer* consumer_creator();
typedef void consumer_destructor(DataConsumer*);

extern "C" {

//----------------------------------- LOGGING ------------------------------
// Allow client to attach a method to be called whilst printing to screen. Essentially a log forwarder
void attachLogger(Logger logger);

// Print function to be used within library
void LOG(LOG_LEVEL level, const char *fmt, ...)
__attribute__((format (printf, 2, 3)));

//----------------------------------- Receiver -----------------------------

// Start network daq_backend
RESULT startReceiver(const char *interface,
                     const char *ip,
                     uint32_t frame_size,
                     uint32_t frames_per_block,
                     uint32_t nof_blocks);

// Start network receiver with multiple receive threads
RESULT startReceiverThreaded(const char *interface,
                     const char *ip,
                     uint32_t frame_size,
                     uint32_t frames_per_block,
                     uint32_t nof_blocks,
                     uint32_t nof_threads);

// Stop network daq_backend
RESULT stopReceiver();

// Add destination port to daq_backend thread
RESULT addReceiverPort(unsigned short port);

//---------------------------------- Consumers ----------------------------

// Load specified consumer from shared library
RESULT loadConsumer(const char* module, const char* consumer);

// Initialise and start specified consumer
RESULT initialiseConsumer(const char* consumer, const char* json_string);

// Start consumer, assigning callback if specified
RESULT startConsumer(const char* consumer, DataCallback callback=nullptr);
RESULT startConsumerDynamic(const char* consumer, DataCallbackDynamic callback=nullptr);

// Start consumer, assigning callback if specified
RESULT stopConsumer(const char* consumer);

}

#endif //_RECEIVER_H
