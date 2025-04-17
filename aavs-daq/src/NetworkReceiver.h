//
// Created by Alessio Magro on 26/08/2015.
//

#ifndef _NETWORKRECEIVER_H
#define _NETWORKRECEIVER_H

// Definitions to control network daq_backend execution
// #define DEBUG 1
#define MAX_CONSUMERS 6

#ifdef WITH_BCC
    // Third party includes
    #include "BPF.h"
#endif

// Project includes
#include "RealTimeThread.h"
#include "RingBuffer.h"

// System includes
#include <linux/if_packet.h>
#include <linux/if_ether.h>

// C++ includes
#include <functional>
#include <vector>
#include <algorithm>
#include <mutex>

using namespace std;

// ---------------------------------- Structure Definitions ---------------------------------

struct recv_params
{
    // These sizing fields should be initialized by the caller
    unsigned int frame_size = 0;
    unsigned int frames_per_block = 0;
    unsigned int nof_blocks = 0;
    unsigned int nof_frames = 0;
    unsigned int nof_threads = 1 ;
};

struct ring
{
    struct iovec        *rd;
    uint8_t             *map;
    struct tpacket_req3 req;
};

struct block_desc
{
    uint32_t              version;
    uint32_t              offset_to_priv;
    struct tpacket_hdr_v1 h1;
};

// -------------------------------- Network Receiver Class ----------------------------------

class NetworkReceiver: public RealTimeThread
{
    public:
        // Default Network Receiver constructor
        // interface refers to the ethernet adapter to bind to
        // port specifies the port number to process packets from
        NetworkReceiver(const char *interface, const char *ip, struct recv_params params);

        // Per-thread teardown
        static void tearDown(const int *sock, struct ring *ring);

        // Add a data consumer to the network daq_backend, together with a filtering function
        // which selects which packet to be pushed to the consumer (via an intermediary ring buffer)
        int registerConsumer(RingBuffer *ring_buffer, const std::function<bool(unsigned char *)> &filter);

        // Remove a data consumer from the daq_backend thread
        bool unregisterConsumer(int consumerID);

        // Add a new port to receive from
        void addPort(unsigned short port) { this->ports[num_ports] = port; num_ports++; }

    protected:

        // Main thread event loop
        void threadEntry() override;

    private:
        // Initialise network receiver
        void initialise(int *interface_socket, struct ring *ring);

        // Initialise daq_backend
        void receive_loop(unsigned int thread_number);

        // Set eBPF filter
        void enable_bpf(int sock);

        // Set thread affinity
        static void set_receiver_thread_affinity(int cpu);

        // Diagnostic method
        void print_diagnostic();

    private:
        char               interface[16];    // Interface string name
        uint32_t           ip    ;          // IP to consider
        unsigned short     ports[16];       // Receive ports
        unsigned short     num_ports;       // Number of receive ports

        // Consumer variables (limited to 6 for now)
        volatile int nof_consumers;
        std::vector<RingBuffer *>ring_buffers;
        std::vector<std::function<bool(unsigned char *)>> filters;
        std::vector<int > consumers;

        // Private definitions for packet_mmap
        struct recv_params params; // PACKET_MMAP parameters

        // Statistics-related objects
        std::atomic<long> processed_frames;
        std::atomic<long> processed_bytes;
        std::atomic<long> lost_packets;

        // Thread synchronisation
        std::mutex mutex_lock;

        // Diagnostics
        std::thread *diagnostic_thread;

#ifdef WITH_BCC
        // BPF handle
        ebpf::BPF bpf;
#endif
};

#endif // _NETWORKRECEIVER_H
