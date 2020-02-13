//
// Created by Alessio Magro on 04/09/2015.
//

#ifndef _DOUBLEBUFFER_H
#define _DOUBLEBUFFER_H

#include "../daq_backend/Utils.h"

#include <cstdint>
#include <cstddef>
#include <ctime>
#include <mutex>

/* This class implements a double buffering system between the channel_data thread, which reads SPEAD packets
 * from the ring buffer and the xGPU thread, which perform cross-correlation on the GPU. Locks are only required
 * at the buffer level, since writes are guaranteed to be non-conflicting (data is partitioned across packets)
 * and read will read in the entire buffer
 */

// Represents a single buffer in the double (or more) buffering system
struct Buffer
{
    double     ref_time;  // The reference time of the second contained in the buffer
    int        index;     // Index to be used to determine buffer boundaries in single channel mode
    int        channel;   // The frequency channel being written to in this buffer
    bool       ready;        // Specifies whether the buffer is ready to be processed
    uint32_t   read_samples; //Number of actual samples in the buffer
    uint32_t   nof_packets; // Number of packets
    uint16_t   *data;         // Pointer to the buffer itself
    uint16_t   nof_antennas;     // Number of antennas in buffer
    uint32_t   nof_samples;     // Number of samples in buffer
    uint8_t    nof_pols;      // Number of polarisations in buffer
    std::mutex *mutex;    // Mutex lock for this buffer
};

class DoubleBuffer
{

public:
    // Default constructor
    DoubleBuffer(uint16_t nof_antennas, uint32_t nof_samples,
                 uint8_t nof_pols, uint8_t nbuffers = 4);

    // Class destructor
    ~DoubleBuffer();

    // Write data to buffer
    void write_data(uint16_t start_antenna, uint16_t nof_included_antennas, uint16_t channel,
                    uint32_t start_sample_index, uint32_t samples,
                    uint16_t *data_ptr, double timestamp);

    // Write data to buffer (use when processing a single channel continuously
    void write_data_single_channel(uint16_t start_antenna, uint16_t nof_included_antennas, uint16_t channel, uint32_t packet_index,
                    uint32_t samples,
                    uint16_t *data_ptr, double timestamp);

    // Finish write
    void finish_write();

    // Read buffer
    Buffer* read_buffer();

    // Get buffer pointer
    Buffer *get_buffer_pointer(int index);

    // Get number of buffers
    int get_number_of_buffers() { return nbuffers; }

    // Ready from buffer, mark as processed
    void release_buffer();

    // Clear double buffer
    void clear();

private:

    inline void copy_data(uint32_t producer_index, uint16_t start_antenna, uint16_t nof_included_antennas,
                          uint64_t start_sample_index, uint32_t samples, uint16_t *data_ptr, double timestamp);

private:
    // The data structure which will hold the buffer elements
    Buffer *double_buffer;

    // Double buffer parameters
    uint16_t nof_antennas;   // Total number of antennas (or stations)
    uint32_t nof_samples;   // Total number of samples
    uint8_t  nof_pols;    // Total number of polarisation
    uint8_t  nbuffers; // Number of buffers in buffering system

    // Producer and consumer pointers, specifying which buffer index to use
    // These are declared as volatile so tha they are not optimsed into registers
    volatile int producer;
    volatile int consumer;

    // Timing variables
    struct timespec tim, tim2;
};


#endif // _DOUBLEBUFFER_H
