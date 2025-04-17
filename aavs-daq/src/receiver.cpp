//
// Created by Alessio Magro on 08/11/2018.
//

#include "DAQ.h"

class DummyConsumer:  public DataConsumer
{
public:

    // Initialise consumer
    bool initialiseConsumer(json configuration) override
    {
        // Create ring buffer
        initialiseRingBuffer(configuration["packet_size"], (size_t) configuration["nof_cells"]);

        return true;
    }

protected:
    // Packet filtering function to be passed to network thread
    inline bool packetFilter(unsigned char* udp_packet) override
    {
        return true;
    }

    // Grab SPEAD packet from buffer and process
    bool processPacket() override
    {
        // Get next packet to process
        size_t packet_size = ring_buffer -> pull(&packet);

        // Check if the request timed out
        if (packet_size == SIZE_MAX)
            // Request timed out
            return true;

        // Ready from packet
        ring_buffer -> pull_ready();

        return true;
    }
};

int main(int argc, char *argv[])
{
    // Define and process arguments
    std::string interface = "lo";
    std::string ip = "127.0.0.1";
    unsigned int nof_threads = 1;
    unsigned int frame_size = 9000;
    unsigned int frames_per_block = 32;
    unsigned int nof_blocks = 64;

    int opt;
    while ((opt = getopt(argc, argv, "t:i:p:f:b:n:")) != -1) {
        switch (opt) {
            case 't':
                nof_threads = (uint32_t) atoi(optarg);
                break;
            case 'i':
                interface = std::string(optarg);
                break;
            case 'p':
                ip = std::string(optarg);
                break;
            case 'f':
                frame_size = (uint32_t) atoi(optarg);
                break;
            case 'b':
                frames_per_block = (uint32_t) atoi(optarg);
                break;
            case 'n':
                nof_blocks = (uint32_t) atoi(optarg);
                break;
            default: /* '?' */
                std::cerr << "Usage: " << argv[0] << " <option(s)>\n"
                          << "Options:\n"
                          << "\t-t Number of threads\n"
                          << "\t-i Network interface to use\n"
                          << "\t-p IP Interface IP\n"
                          << "\t-f Frame size\n"
                          << "\t-b Frames per block\n"
                          << "\t-n Number of blocks\n"
                          << std::endl;
                exit(EXIT_FAILURE);
        }
    }

    LOG(INFO, "Benchmarking receiver with %d threads on %s (%s)", nof_threads, interface.c_str(), ip.c_str());

    // Set consumer parameters
    json j = {
            {"packet_size", frame_size},
            {"nof_cells", 32768}
    };

    // Create network thread instance
    struct recv_params params;
    params.frame_size        = frame_size;
    params.frames_per_block  = frames_per_block;
    params.nof_blocks        = nof_blocks;
    params.nof_threads       = nof_threads;

    auto *receiver = new NetworkReceiver(interface.c_str(), ip.c_str(), params);

    // Add receiver port
    receiver -> addPort(4660);
    receiver -> startThread(false);

    // Create dummy consumer and initialise
    auto *dummy = new DummyConsumer();
    dummy -> initialiseConsumer(j);

    // Start consumer
    dummy -> setReceiver(receiver);
    dummy -> startThread(false);
    dummy -> setIsRunning(true);

    sleep(1000);

    // Stop consumer
    dummy -> stopConsumer();

    // Stop receiver
    receiver -> stop();
}
