//
// Created by Alessio Magro on 26/08/2015.
/*
 * struct tpacket_req is defined in /usr/include/linux/if_packet.h and establishes a
 * circular buffer (ring) of unswappable memory. Being mapped in the capture process allows
 * reading the captured frames and related meta-information like timestamps without requiring a system call.
 *
 * Frames are grouped in blocks. Each block is a physically contiguous region of memory and holds
 * tp_block_size/tp_frame_size frames. The total number of blocks is tp_block_nr. Note that
 * tp_frame_nr is a redundant parameter because
 *     frames_per_block = tp_block_size/tp_frame_size
 * indeed, packet_set_ring checks that the following condition is true
 *     frames_per_block * tp_block_nr == tp_frame_nr
 *
 * Example
 *   tp_block_size= 4096
 *   tp_frame_size= 2048
 *   tp_block_nr  = 4
 *   tp_frame_nr  = 8
 * we will get the following buffer structure:
 *
 *        block #1                 block #2
 * +---------+---------+    +---------+---------+
 * | frame 1 | frame 2 |    | frame 3 | frame 4 |
 * +---------+---------+    +---------+---------+
 *
 * block #3                 block #4
 * +---------+---------+    +---------+---------+
 * | frame 5 | frame 6 |    | frame 7 | frame 8 |
 * +---------+---------+    +---------+---------+
 *
 * A frame can be of any size with the only condition it can fit in a block. A block can only hold an
 * integer number of frames, or in other words, a frame cannot be spawned across two blocks, so
 * there are some details you have to take into account when choosing the frame_size.
*/

/* For better performance, adjust ring buffer sizes on interface:
 * ethtool -G eth1 rx 4096 tx 4096
 * ethtool -g eth1
 *
 * Disable Ethernet flow control
 * sudo ethtool -A eth2 autoneg off rx off tx off
 *
 * Disable irqbalance
 * sudo service irqbalance stop
*/

// Project includes
#include "NetworkReceiver.h"
#include "DAQ.h"
#include "SPEAD.h"

// System includes
#include <arpa/inet.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <net/if.h>
#include <linux/ip.h>
#include <linux/udp.h>
#include <sys/poll.h>
#include <regex>

// #define STATISTICS

using namespace std::chrono_literals;

// Network Receiver constructor
NetworkReceiver::NetworkReceiver(const char *interface, const char *ip_address, struct recv_params params)
{
    // Copy parameters to local variables
    strcpy(this->interface, interface);

    // Convert IP to unsigned int
    struct sockaddr_in sa{};
    inet_pton(AF_INET, ip_address, &(sa.sin_addr));
    this -> ip = htonl(sa.sin_addr.s_addr);

    // Copy parameters
    this->params = params;
    this->num_ports = 0;

    // Initialise consumer-related variables
    nof_consumers = 0;

    // Initialise random number generator
    srand(time(nullptr));

    processed_bytes = 0;
    processed_frames = 0;
    lost_packets = 0;

    // If STATISTICS is defined, create a diagnostics thread to monitor the receiver
#ifdef STATISTICS
    diagnostic_thread = new std::thread(&NetworkReceiver::print_diagnostic, this);
    diagnostic_thread -> detach();
#endif
}

// Network Receiver main event loop
void NetworkReceiver::threadEntry()
{
    // Create required number of threads
    std::thread *threads[params.nof_threads];
    for(unsigned i = 0; i < params.nof_threads; i++)
        threads[i] = new std::thread(&NetworkReceiver::receive_loop, this, i + 1);

    // Then wait for thread to finish
    for(unsigned i = 0; i < params.nof_threads; i++)
        threads[i]->join();
}

// Per-thread de-allocation
void NetworkReceiver::tearDown(const int *sock, struct ring *ring)
{
    // Close socket
    close(*sock);

    // Free ring data structures
    munmap(ring->map, ring->req.tp_block_size * ring->req.tp_block_nr);
    munmap(ring->rd, ring->req.tp_block_nr * sizeof(*ring->rd));
}

// Initialise network daq_backend
void NetworkReceiver::initialise(int *interface_socket, struct ring *ring)
{
    // Define socket
    int sock;

    // Create raw socket
    if ((sock = socket(AF_PACKET, SOCK_RAW, htons(ETH_P_IP))) < 0)
    {
        LOG(FATAL, "Could not create socket [requires root]");
        exit(-1);
    }

    // Set socket buffer size to 512 MB if possible
    int n = 1024 * 1024 * 512;
    if (setsockopt(sock, SOL_SOCKET, SO_RCVBUF, &n, sizeof(n)) == -1)
        LOG(FATAL, "Could not set UDP buffer size for socket");

    // Disable checksum
    int disable = 1;
    if (setsockopt(sock, SOL_SOCKET, SO_NO_CHECK, (void*)&disable, sizeof(disable)) < 0) {
        LOG(FATAL, "Failed to disable checksum checking");
    }

    // Set socket packet version to use TPACKET_V3
    int v = TPACKET_V3;
    if (setsockopt(sock, SOL_PACKET, PACKET_VERSION, &v, sizeof(v)))
    {
        LOG(FATAL, "Could not set socket option for packet version");
        exit(-1);
    }

    // Copy the interface name to ifreq structure
    struct ifreq s_ifr{};
    strncpy(s_ifr.ifr_name, interface, sizeof(s_ifr.ifr_name));

    // Get interface index
    if (ioctl(sock, SIOCGIFINDEX, &s_ifr) < 0)
    {
        LOG(FATAL, "Couldn't get interface ID");
        exit(-1);
    }

    // Enable eBPF filter
    enable_bpf(sock);

    // Make sure frame size is a multiple of 128 bytes
    long min_frame_size = 256;

    // Set up PACKET_MMAP capturing mode. Parameters are set by caller
    memset(&ring->req, 0, sizeof(ring->req));
    ring->req.tp_frame_size = (unsigned int) ((unsigned int) ceil(params.frame_size / (double) min_frame_size) * min_frame_size);
    ring->req.tp_block_size = params.frames_per_block * ring->req.tp_frame_size;
    ring->req.tp_block_nr = params.nof_blocks;
    ring->req.tp_frame_nr =  params.frames_per_block * params.nof_blocks;
    ring->req.tp_retire_blk_tov = 60; // Timeout
    ring->req.tp_feature_req_word = TP_FT_REQ_FILL_RXHASH;

    if (params.nof_frames == 0)
        params.nof_frames = ring->req.tp_frame_nr;

    // Set ring buffer on socket
    if (setsockopt(sock, SOL_PACKET, PACKET_RX_RING, &ring->req, sizeof(ring->req)) < 0)
    {
        close(sock);
        LOG(FATAL, "Could not set socket options");
        exit(-1);
    }

    // Map kernel buffer to user space using mmap
    ring->map = (uint8_t*) mmap(nullptr, ring->req.tp_block_nr * ring->req.tp_block_size,
                                PROT_READ | PROT_WRITE, MAP_SHARED | MAP_LOCKED | MAP_NORESERVE, sock, 0);

    if (ring->map == MAP_FAILED)
    {
        close(sock);
        LOG(FATAL, "Could not memory map kernel ring buffer");
        exit(-1);
    }

    // Allocate ring buffer using mmap (try to use huge pages)
    ring->rd = (iovec *) mmap(nullptr, ring->req.tp_block_nr * sizeof(*ring->rd),
                              PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB, -1, 0);

    // If using huge pages failed, use normal pages
    if (ring->rd == MAP_FAILED) {
        LOG(DEBUG, "NetworkReceiver: Could not use huge pages, using normal pages");
        ring->rd = (iovec *) mmap(nullptr, ring->req.tp_block_nr * sizeof(*ring->rd),
                                  PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    }

    // Initialise ring buffer
    for (unsigned i = 0; i < ring->req.tp_block_nr; ++i) {
        ring->rd[i].iov_base = ring->map + (i * ring->req.tp_block_size);
        ring->rd[i].iov_len = ring->req.tp_block_size;
    }

    // Fill sockaddr_ll struct to prepare for binding
    struct sockaddr_ll address{};
    memset(&address, 0, sizeof(address));
    address.sll_family   = AF_PACKET;
    address.sll_protocol = htons(ETH_P_IP);
    address.sll_ifindex  = s_ifr.ifr_ifindex;
    address.sll_hatype   = 0;
    address.sll_pkttype  = 0;
    address.sll_halen    = 0;

    // Bind socket to interface
    if(bind(sock, (struct sockaddr *) &address, sizeof(struct sockaddr_ll)) < 0)
    {
        LOG(FATAL, "Could not bind to address");
        exit(-1);
    }

    /* Set FANOUT option (only if number of threads is more than 1)
     * PACKET_FANOUT_HASH: schedule to socket by skb's packet hash
     * PACKET_FANOUT_LB: schedule to socket by round-robin
     * PACKET_FANOUT_CPU: schedule to socket by CPU packet arrives on
     * PACKET_FANOUT_RND: schedule to socket by random selection
     * PACKET_FANOUT_ROLLOVER: if one socket is full, rollover to another
     * PACKET_FANOUT_QM: schedule to socket by skbs recorded queue_mapping */
    if (this->params.nof_threads > 1) {
        int fanout_arg = ((getpid() & 0xFFFF) | (PACKET_FANOUT_CPU << 16));
        if (setsockopt(sock, SOL_PACKET, PACKET_FANOUT, &fanout_arg, sizeof(fanout_arg)) < 0) {
            LOG(ERROR, "Can't configure packet_mmap fanout.\n");
            exit(-1);
        }
    }

    // We are ready to start receiving data...
    *interface_socket = sock;
}

// Set receiver thread CPU affinity
void NetworkReceiver::set_receiver_thread_affinity(int cpu)
{
    // Create CPU mask
    cpu_set_t cpuset{};
    CPU_ZERO(&cpuset);
    CPU_SET(cpu, &cpuset);

    // Apply CPU set
    if (pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset) != 0)
        LOG(WARN, "Cannot set pthread affinity for receiver thread");
}

// Initialise daq_backend
void NetworkReceiver::receive_loop(unsigned int thread_number)
{
    // Initialise receiver thread
    struct ring ring = {};
    int sock;
    this->initialise(&sock, &ring);

    // Cache value of cache alignments
    long cache_alignment = CACHE_ALIGNMENT;

    unsigned i = 0;
    struct pollfd pfd = {};
    memset(&pfd, 0, sizeof(pfd));

    pfd.fd = sock;
    pfd.events = POLLIN | POLLERR;
    pfd.revents = 0;


    // Run indefinitely
    while (likely(!this->stop_thread))
    {
        // Fetch the next frame and check whether it is available for processing
        volatile struct block_desc *pbd = (struct block_desc *) ring.rd[i].iov_base;

        // Wait until data is available using poll with timeout
        while(((pbd->h1.block_status & TP_STATUS_USER) == 0) && likely(!this->stop_thread))
            poll(&pfd, 1, 100);

	    // Check whether we need to stop
        if (unlikely(this->stop_thread))
            continue;

        // An entire block is ready, so we can process multiple packets
        auto *frame_header = (struct tpacket3_hdr *) ((uint8_t *) pbd + pbd->h1.offset_to_first_pkt);

        // Loop over all packets in block
        for(unsigned p = 0; p < pbd->h1.num_pkts; p++)
        {
             // If no consumers are registered ignore current block
            if (nof_consumers == 0) {
                 frame_header = (struct tpacket3_hdr *) ((uint8_t *) frame_header + frame_header->tp_next_offset);
                 continue;
            }

            // Extract Ethernet Header
            auto *eth_header  = (struct ethhdr *) ((uint8_t *) frame_header + frame_header ->tp_mac);

            // Extract IP Header
            auto *ip_header   = (struct iphdr  *) ((uint8_t *) eth_header + ETH_HLEN);

            // Extract UDP header
            auto *udp_header = (struct udphdr *) ((uint8_t *) ip_header + ip_header->ihl * 4);

#ifdef WITH_BCC
            // We know that this a UDP packet with correct destination IP and port due to filter
            // No need to check this again
#else
            // Check whether this is a UDP packet and whether destination port is correct
            // Additional checks can be performed (eventually)
            unsigned port_index = 0;
            for(port_index = 0; port_index < this->num_ports; port_index++)
                if (ntohs(udp_header->dest) == this->ports[port_index])
                    break;

            if (ip_header->protocol != IPPROTO_UDP || port_index == this->num_ports || ip_header->daddr != ntohl(this->ip))
            {
                // Proceed to next packet in block
                frame_header = (struct tpacket3_hdr *) ((uint8_t *) frame_header + frame_header->tp_next_offset);
                continue;
            }
#endif

            // Packet is UDP and correct destination port. Get UDP packet contents
            uint8_t *udp_packet = ((uint8_t *) udp_header) + sizeof(udphdr);

            // Go through consumers, if any
            bool processed = false;

            for(unsigned c = 0; c < nof_consumers; c++)
            {
                // Check if current consumer has a filtering function specified
                if (filters[c](udp_packet))
                {
                     // Push packet to ring buffer. If this fails after a number of retries
                     // increment number of packets
                     if (unlikely(!ring_buffers[c]->push(udp_packet, ntohs(udp_header->len) - sizeof(udphdr))))
                         lost_packets++;

                    // Set packet as processed
                    processed = true;
                }
            }

#ifdef STATISTICS
            if (processed) {
                processed_frames++;
                processed_bytes += frame_header->tp_len;
            }
#endif
            // Proceed to next packet
            frame_header = (struct tpacket3_hdr *) ((uint8_t *) frame_header + frame_header->tp_next_offset);
        }

        // Tell kernel that the block has been processed and proceed to next block
        pbd->h1.block_status = TP_STATUS_KERNEL;
        i = (i + 1) % params.nof_blocks;

        //std::this_thread::sleep_for(1ns);
    }
}

// Add a consumer to DAQ receiver
// STL bind
int NetworkReceiver::registerConsumer(RingBuffer *ring_buffer, const std::function<bool(unsigned char *)> &filter)
{
    // Lock mutex
    this->mutex_lock.lock();

    // Check if the consumer limit has been reached
    if (nof_consumers >= MAX_CONSUMERS) {
        LOG(WARN, "Maximum number of consumers reached");
        this->mutex_lock.unlock();
        return -1;
    }

    // Otherwise, add ring_buffer and associated filter function to network thread
    ring_buffers.push_back(ring_buffer);
    filters.push_back(filter);
    int consumer_id = nof_consumers;
    consumers.push_back(consumer_id);

    nof_consumers = nof_consumers + 1 ;

    // Unlock mutex
    this->mutex_lock.unlock();

    // All done, return
    return consumer_id;
}

// Remove a consumer from the network daq_backend
bool NetworkReceiver::unregisterConsumer(int consumerID)
{
    // Find consumer in consumers vector
    for(unsigned i = 0; i < nof_consumers; i++)
    {
        if (consumers[i] == consumerID)
        {
            this->mutex_lock.lock();
            ring_buffers.erase(ring_buffers.begin() + i);
            filters.erase(filters.begin() + i);
            consumers.erase(consumers.begin() + i);
            nof_consumers = nof_consumers - 1;
            this->mutex_lock.unlock();
            return true;
        }
    }

    // Nothing found
    LOG(ERROR, "Failed to unregister consumer %d", consumerID);
    return false;
}

// Diagnostic thread for checking
void NetworkReceiver::print_diagnostic()
{
    // Initialise timing
    struct timespec tps{}, tpe{};

    // Loop forever (until receiver is stopped)
    while (!stop_thread) {

        // Reset timing
        clock_gettime(CLOCK_REALTIME, &tps);

        // Sleep for a while
        std::this_thread::sleep_for(5s);

        clock_gettime(CLOCK_REALTIME, &tpe);
        double duration = ((tpe.tv_sec - tps.tv_sec) + (tpe.tv_nsec - tps.tv_nsec) * 1e-9);
        LOG(INFO, "Processed frames: %ld, Frames per second: %.2lfk, data rate: %.2lfGb/s, %ld lost packets", processed_frames * 1,
            (processed_frames * 1e-3) / duration,
            (processed_bytes * 8 * 1e-9) / duration,
            lost_packets.load());

        // Reset statistics
        processed_frames = 0;
        processed_bytes  = 0;
        lost_packets = 0;
    }
}

void NetworkReceiver::enable_bpf(int sock)
{
#ifdef WITH_BCC
#pragma gcc diagnostic ignored "-Wenum-conversion"

    // Create BPF program which only filter through packets which:
    // - are UDP packet
    // - have a valid destination IP
    // - have a registered destination port

    // First we need to create the appropraite check to include all valid ports
    std::string PORT_FILTER;
    for (unsigned i = 0; i < this->num_ports; i++) {
        // Add new condition with port placeholder;
        PORT_FILTER += "\nif(udp->dport != ###) { goto DROP; }\n";

        // Replace placeholder with actual port
        PORT_FILTER = std::regex_replace(PORT_FILTER, std::regex("###"), std::to_string(this->ports[i]));
    }

    std::string BPF_FILTER = R"(
    #include <net/sock.h>
    #include <bcc/proto.h>

    int packet_filter(struct __sk_buff *skb) {

	u8 *cursor = 0;

	struct ethernet_t *ethernet = cursor_advance(cursor, sizeof(*ethernet));

	// Filter IP packets (ethernet type = 0x0800)
	if (!(ethernet->type == 0x0800)) {
		goto DROP;
	}

	struct ip_t *ip = cursor_advance(cursor, sizeof(*ip));

	// Filter UDP packets (IP next protocol = 17)
	if (ip->nextp != 17) {
		goto DROP;
	}

    // Check that destination IP is valid
    if (ip->dst != ##IP##)
        goto DROP;

	// Go to UDP header
	struct udp_t *udp = cursor_advance(cursor, sizeof(*udp));

	// Check that destination port is valid
	##UDP_FILTER##

	goto KEEP;

	// Keep the packet and send it to userspace returning -1
	KEEP:
	return -1;

	//drop the packet returning 0
	DROP:
	return 0;
    } )";

    // Add port checks to BFP filter
    BPF_FILTER = std::regex_replace(BPF_FILTER, std::regex("##UDP_FILTER##"), PORT_FILTER);

    // Insert IP check to BFP filter
    BPF_FILTER = std::regex_replace(BPF_FILTER, std::regex("##IP##"), std::to_string(this->ip));

    // Initialise filter
    auto res = bpf.init(BPF_FILTER);
    if (res.code() != 0)
    {
        LOG(FATAL, "Could not initialize BPF filter");
        exit(-1);
    }

    // Load BPF program
    int packet_filter_fd;
    res = bpf.load_func("packet_filter", BPF_PROG_TYPE_SOCKET_FILTER, packet_filter_fd);
    if (res.code() != 0)
    {
        LOG(FATAL, "Could not load packet filter function");
        exit(-1);
    }

    // Attach packet filter to created socket
    if (setsockopt(sock, SOL_SOCKET, SO_ATTACH_BPF, &packet_filter_fd, sizeof(packet_filter_fd)) < 0)
    {
        LOG(FATAL, "Could not attach packet filter\n");
        exit(-1);
    }
#endif
}
