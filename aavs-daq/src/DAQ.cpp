//
// Created by Alessio Magro on 30/04/2018.
//

#include "DAQ.h"

#include <dlfcn.h>
#include <map>
#include <cstring>

// --------------------------- DEFINE GLOBALS ------------------------------

// The global consumers map, which keeps track of the initialised and running consumers
// Only one instance per consumer type can be initialised
map<std::string, DataConsumer *> consumers;

// Global network daq_backend instance
NetworkReceiver *receiver = nullptr;

//--------------------------------------------------------------------------

//----------------------------------- LOGGING ------------------------------
Logger receiver_logger = nullptr;

// Print function to be used within library
void LOG(LOG_LEVEL level, const char *fmt, ...)
{
    // Generate string from arguments
    auto temp = std::vector<char> {};
    auto length = std::size_t {150};
    std::va_list args;
    while (temp.size() <= length)
    {
        temp.resize(length + 1);
        va_start(args, fmt);
        std::vsnprintf(temp.data(), temp.size(), fmt, args);
        va_end(args);
    }

    // The message
    std::string message = temp.data();

    // If this is an error, get errno message as well
    if (level <= 1 && errno != 0)  {
        std::string error = strerror(errno);
        message += ": ";
        message.append(error);
    }

    // if logger is defined, pass arguments
    if (receiver_logger != nullptr)
        receiver_logger(level, message.c_str());
    else
    {
        // Otherwise, use fprintf
        if (level >= 4)
            fprintf(stdout, "%s\n", message.c_str());
        else
            fprintf(stderr, "%s\n", message.c_str());

        if (level == 1)
	    exit(-1);
    }
}

// Attach logging callback
void attachLogger(Logger logger)
{
    receiver_logger = logger;
}

//--------------------------------------------------------------------------

// Start network daq_backend
RESULT startReceiver(const char *interface, const char *ip, unsigned frame_size,
                     unsigned frames_per_block, unsigned nof_blocks)
{
    return startReceiverThreaded(interface, ip, frame_size, frames_per_block, nof_blocks, 1);
}

RESULT startReceiverThreaded(const char *interface, const char *ip, unsigned frame_size,
                     unsigned frames_per_block, unsigned nof_blocks, unsigned nof_threads)
{
    // Create network thread instance
    struct recv_params params;
    params.frame_size       = frame_size;
    params.frames_per_block = frames_per_block;
    params.nof_blocks       = nof_blocks;
    params.nof_threads      = nof_threads;

    // Copy interface name
    auto *hw_interface = (char *) malloc(16);
    strcpy(hw_interface, interface);

    // Copy the IP
    auto ip_address = (char *) malloc(16);
    strcpy(ip_address, ip);

    // Create and initialise network daq_backend;
    try {
        receiver = new NetworkReceiver(hw_interface, ip_address, params);
        receiver -> startThread(false);
        free(hw_interface);
        free(ip_address);
    }
    catch (const std::exception& e)  {
        free(hw_interface);
        free(ip_address);
        LOG(ERROR, "Could not start daq_backend, %s", e.what());
        return FAILURE;
    }

    return SUCCESS;
}

// Stop network daq_backend
RESULT stopReceiver()
{
    if (receiver != nullptr)
    {
        try {
            receiver -> stop();
            delete receiver;
            receiver = nullptr;
        }
        catch (const std::exception& e)
        {
            LOG(ERROR, "Could not stop daq_backend, %s", e.what());
            return FAILURE;
        }
    }

    return SUCCESS;
}

// Add daq_backend port
RESULT addReceiverPort(unsigned short port)
{
    if (receiver != nullptr)
    {
        receiver->addPort(port);
        return SUCCESS;
    }
    else {
        return RECEIVER_UNINITIALISED;
    }
}

// --------------------------- CONSUMERS ----------------------------------

// Load specified consumer from shared library
 RESULT loadConsumer(const char* module, const char* consumer) {

    // Check if consumer is already loaded
    map<std::string, DataConsumer *>::iterator it;
    it = consumers.find(consumer);
    if (it != consumers.end())
        return CONSUMER_ALREADY_INITIALISED;

    try {
        // Try loading the shared library
        void *lib = dlopen(module, RTLD_NOW);
        if (!lib) {
            LOG(FATAL, "Cannot load library: %s", dlerror());
            return FAILURE;
        }

        // Reset errors
        dlerror();

        // Get pointer to consumer instance creator
        auto *consumer_instance = (consumer_creator *) dlsym(lib, consumer);
        const char *error = dlerror();
        if (error) {
            LOG(FATAL, "Cannot load symbol: %s", error);
            return FAILURE;
        }

        // Successfully loaded consumer, try to create it and add it to map
        consumers[consumer] = consumer_instance();
    }
    catch (const std::exception& e)  {
        LOG(ERROR, "Could not load consumer %s, %s", consumer, e.what());
        return FAILURE;
    }

    return SUCCESS;
}

// Initialise and start specified consumer
RESULT initialiseConsumer(const char* consumer, const char* json_string) {

    // Check if daq_backend is initialised
    if (receiver == nullptr)
        return RECEIVER_UNINITIALISED;

    // Check if consumer is available
    map<std::string, DataConsumer *>::iterator it;
    it = consumers.find(consumer);
    if (it == consumers.end())
        return CONSUMER_NOT_INITIALISED;

    // De-serialise JSON string
    json configuration;
    try {
        configuration = json::parse(json_string);
    }
    catch (const std::exception& e)  {
        LOG(ERROR, "Error in parsing JSON configuration for %s, %s", consumer, e.what());
        return FAILURE;
    }

    // Call consumer with parsed json
    try {
        if (consumers[consumer] -> initialiseConsumer(configuration))
            return SUCCESS;
        else
            return FAILURE;
    }
    catch (const std::exception& e) {
        LOG(ERROR, "Could not initialise consumer %s, %s", consumer, e.what());
        return FAILURE;
    }
}

RESULT startConsumerGeneric(const char* consumer,
                            DataCallback callback_static= nullptr,
                            DataCallbackDynamic callback_dynamic=nullptr,
                            DiagnosticCallback diagnostic_callback = nullptr) {

    // Check if daq_backend is initialised
    if (receiver == nullptr)
        return RECEIVER_UNINITIALISED;

    // Check if consumer is available
    map<std::string, DataConsumer *>::iterator it;
    it = consumers.find(consumer);
    if (it == consumers.end())
        return CONSUMER_NOT_INITIALISED;

    // If consumer is available, check if is already running
    if (consumers[consumer] -> getIsRunning())
        return CONSUMER_ALREADY_INITIALISED;

    // Otherwise, start consumer
    try {
        consumers[consumer] -> setReceiver(receiver);

        if (callback_dynamic == nullptr)
            consumers[consumer]->setCallback(callback_static);
        else
            consumers[consumer]->setCallback(callback_dynamic);
        
        // Set diagnostic callback if specified
        if (diagnostic_callback != nullptr)
            consumers[consumer]->setDiagnosticCallback(diagnostic_callback);

        consumers[consumer] -> startThread();
        consumers[consumer] -> setIsRunning(true);
    }
    catch (const std::exception& e) {
        LOG(ERROR, "Could not start consumer %s, %s", consumer, e.what());
        return FAILURE;
    }

    // All done
    return SUCCESS;

}

// Start consumer, assigning callback if specified
RESULT startConsumer(const char* consumer, DataCallback callback, DiagnosticCallback diagnostic_callback) {
    return startConsumerGeneric(consumer, callback, nullptr, diagnostic_callback);
}

// Start consumer, assigning callback if specified (same as above but with different callback type)
RESULT startConsumerDynamic(const char* consumer, DataCallbackDynamic callback, DiagnosticCallback diagnostic_callback) {
    return startConsumerGeneric(consumer, nullptr, callback, diagnostic_callback);
}

// Start consumer, assigning callback if specified
RESULT stopConsumer(const char* consumer) {

    // Check if consumer is available
    map<std::string, DataConsumer *>::iterator it;
    it = consumers.find(consumer);

    if (it == consumers.end())
        return CONSUMER_NOT_INITIALISED;

    // If consumer is available, check if is already running
    if (!consumers[consumer] -> getIsRunning())
        return CONSUMER_NOT_INITIALISED;

    try {
        // Stop consumer
        consumers[consumer]->stopConsumer();

        // Delete consumer
        delete consumers[consumer];

        // Remove object from vector
        consumers.erase(it);
    }
    catch (const std::exception& e)     {
        LOG(ERROR, "Could not stop consumer %s, %s", consumer, e.what());
        return FAILURE;
    }

    // All done
    return SUCCESS;
}
