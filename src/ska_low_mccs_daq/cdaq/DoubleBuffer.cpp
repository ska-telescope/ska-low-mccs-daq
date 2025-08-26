//
// Created by Alessio Magro on 04/09/2015.
//

#include <stdlib.h>
#include <math.h>
#include <sys/mman.h>
#include <cstdio>
#include <cstring>
#include <float.h>

#include "DoubleBuffer.h"
#include "DAQ.h"

// Default double buffer constructor
DoubleBuffer::DoubleBuffer(uint16_t nof_antennas, uint32_t nof_samples,
                           uint8_t nof_pols, uint8_t nbuffers, AllocPolicy policy) :
                            nof_antennas(nof_antennas), nof_samples(nof_samples), nof_pols(nof_pols),
                            nbuffers(nbuffers)
{
    // Make sure that nbuffers is a power of 2
    nbuffers = (uint8_t) pow(2, ceil(log2(nbuffers)));

    // Allocate the double buffer
    allocate_aligned((void **) &double_buffer, (size_t) CACHE_ALIGNMENT, nbuffers * sizeof(Buffer));

    // Initialise and allocate buffers in each struct instance
    for(unsigned i = 0; i < nbuffers; i++)
    {
        double_buffer[i].ref_time = 0;
        double_buffer[i].ready    = false;
        double_buffer[i].channel  = -1;
        double_buffer[i].index = -1;
        double_buffer[i].read_samples = 0;
        double_buffer[i].nof_packets = 0;
        double_buffer[i].nof_antennas  = nof_antennas;
        double_buffer[i].nof_samples = nof_samples;
        double_buffer[i].nof_pols  = nof_pols;
        double_buffer[i].mutex = new std::mutex;
        if (policy == AllocPolicy::Default) {
            allocate_aligned((void **) &(double_buffer[i].data), (size_t) CACHE_ALIGNMENT,
                            nof_samples * nof_antennas * nof_pols * sizeof(uint16_t));

            // Lock memory
            if (mlock(double_buffer[i].data, nof_antennas * nof_pols * nof_samples * sizeof(uint16_t)) == -1)
                perror("Could not lock memory");
            double_buffer[i].owned_by_base = true;
        } else {
            double_buffer[i].data = nullptr;
            double_buffer[i].owned_by_base = false;
        }
    }

    // Initialise producer and consumer
    producer = 0;
    consumer = 0;

    // Set up timing variables
    tim.tv_sec  = 0;
    tim.tv_nsec = 1000;
}

// Class destructor
DoubleBuffer::~DoubleBuffer()
{
    for(unsigned i = 0; i < nbuffers; i++)
    {
        if (double_buffer[i].owned_by_base) {
            free(double_buffer[i].data);
        }
        delete double_buffer[i].mutex;
    }
    free(double_buffer);
}


// Write data to buffer
void DoubleBuffer::write_data(uint16_t start_antenna, uint16_t nof_included_antennas, uint16_t channel,
                              uint32_t start_sample_index, uint32_t samples,
                              uint16_t *data_ptr, double timestamp)
{
    // Check if we are receiving a packet from a previous channel, if so place in previous buffer
    if (this -> double_buffer[this->producer].channel > channel)
    {
        int local_producer = (this -> producer == 0) ? this->nbuffers - 1 : (this->producer - 1);
        this->copy_data(local_producer, start_antenna, nof_included_antennas, (uint64_t) start_sample_index * samples, 
                        samples, data_ptr, timestamp);
        return;
    }

    // Check whether the current consumer buffer is empty
    else if (this -> double_buffer[this->producer].channel == -1)
    {
        // Set channel of this buffer
        this -> double_buffer[this->producer].channel = channel;
    }

    // Check if current buffer's channel and data channel match
    else if (this -> double_buffer[this->producer].channel != channel)
    {
        // We have received a packet from a different channel, mark
        // previous buffer as ready and switch to next one
        int local_producer = (this -> producer == 0) ? this->nbuffers - 1 : (this->producer - 1);
        if (this->double_buffer[local_producer].channel != -1)
            this -> double_buffer[local_producer].ready = true;

        // Update producer pointer
        this -> producer = (this -> producer + 1) % this -> nbuffers;

        // Wait for next buffer to become available
        unsigned int index = 0;
        while (index * tim.tv_nsec < 1e9)
        {
            if (this->double_buffer[this->producer].channel != -1) {
                nanosleep(&tim, &tim2);
                index++;
            }
            else
                break;
        }

        if (index * tim.tv_nsec >= 1e6 )
            LOG(WARN, "Warning: Overwriting buffer!!\n");

        // Start using new buffer
        this -> double_buffer[this -> producer].channel = channel;
        this -> double_buffer[this -> producer].read_samples = 0;
    }

    // Copy data to buffer
    this->copy_data(producer, start_antenna, nof_included_antennas, (uint64_t) start_sample_index * samples, 
                    samples, data_ptr, timestamp);
}

// Write data to buffer
void DoubleBuffer::write_data_single_channel(uint16_t start_antenna, uint16_t nof_included_antennas, uint16_t channel,
                                             uint32_t packet_index, uint32_t samples,
                              uint16_t *data_ptr, double timestamp)
{
    // Adding to previous buffer
    if (this -> double_buffer[this->producer].ref_time > timestamp)
    {
        int local_producer = (this -> producer == 0) ? this->nbuffers - 1 : (this->producer - 1);
        this->copy_data(local_producer, start_antenna, nof_included_antennas,
                        (uint64_t) packet_index * samples, samples, data_ptr,  timestamp);
        this->double_buffer[local_producer].index = packet_index;
        return;
    }

    // Check whether the current consumer buffer is empty
    else if (this -> double_buffer[this->producer].channel == -1)
    {
        // Set channel of this buffer
        this -> double_buffer[this->producer].channel = channel;
        this -> double_buffer[this->producer].index = packet_index;
    }

    // Check if current buffer's channel and data channel match
    else if (packet_index == 0 && timestamp >= this -> double_buffer[this->producer].ref_time + (nof_samples - 1) * 1.08e-6)
    {
        // We have skipped buffer borders, mark
        // previous buffer as ready and switch to next one

        uint32_t packets = this -> double_buffer[this->producer].nof_packets, samples = this -> double_buffer[this->producer].read_samples;

        int local_producer = (this -> producer == 0) ? this->nbuffers - 1 : (this->producer - 1);
        if (this->double_buffer[local_producer].index != -1)
            this -> double_buffer[local_producer].ready = true;

        // Update producer pointer
        this -> producer = (this -> producer + 1) % this -> nbuffers;

        // Wait for next buffer to become available
        unsigned int index = 0;
        while (index * tim.tv_nsec < 1e6)
        {
            if (this->double_buffer[this->producer].index != -1) {
                nanosleep(&tim, &tim2);
                index++;
            }
            else
                break;
        }

        if (index * tim.tv_nsec >= 1e6 )
            LOG(WARN, "Warning: Overwriting buffer [%d]!", this ->producer);

        // Start using new buffer
        this->double_buffer[this -> producer].mutex -> lock();
        this->double_buffer[this -> producer].channel = channel;
        this->double_buffer[this -> producer].index = packet_index;
        this->double_buffer[this -> producer].ready = false;
        this->double_buffer[this -> producer].ref_time = DBL_MAX;
        this->double_buffer[this -> producer].read_samples = 0;
        this->double_buffer[this -> producer].nof_packets = 0;
        this->double_buffer[this -> producer].mutex -> unlock();
    }

    // Copy data to buffer
    this->copy_data(producer, start_antenna, nof_included_antennas, (uint64_t) packet_index * samples, samples, data_ptr, timestamp);
}

inline void DoubleBuffer::copy_data(uint32_t producer_index, uint16_t start_antenna, uint16_t nof_included_antennas,
                                    uint64_t start_sample_index, uint32_t samples, uint16_t *data_ptr, double timestamp)
{
    // Data will be stored in sample/antenna/pol
    uint16_t *ptr = double_buffer[producer_index].data + (start_sample_index * nof_antennas + start_antenna) * nof_pols;
    for(unsigned i = 0; i < samples; i++)
    {
        for (unsigned j = 0; j < nof_included_antennas; j++)
        {
            *ptr++ = *data_ptr++;
            *ptr++ = *data_ptr++;
        }
        ptr += (nof_antennas - nof_included_antennas) * nof_pols;
    }

    // Update number of samples in the current buffer
    if (start_antenna == 0)
        this -> double_buffer[producer_index].read_samples += samples;
    this->double_buffer[producer_index].nof_packets++;

    // Update timings
    if (this->double_buffer[producer_index].ref_time > timestamp || this->double_buffer[producer_index].ref_time == 0)
        this->double_buffer[producer_index].ref_time = timestamp;
}


// In case where the data stream is terminated or has stopped, finish current buffer
void DoubleBuffer::finish_write()
{
    // If a buffer is being written to, finalize it
    int local_producer = (this -> producer == 0) ? this->nbuffers - 1 : (this->producer - 1);
    if (this -> double_buffer[local_producer].channel != -1)
        this->double_buffer[local_producer].ready = true;

    if (this -> double_buffer[this -> producer].channel != -1)
    {
        this->double_buffer[this->producer].ready = true;
        this->producer = (this->producer + 1) % this->nbuffers;
    }
}

// Read buffer
Buffer* DoubleBuffer::read_buffer()
{
    // Wait for buffer to become available
    while(!(this->double_buffer[this->consumer].ready)) {
        nanosleep(&tim, &tim2); // Wait using nanosleep
        return nullptr;
    }

    // Buffer is ready to be processed, return pointer and buffer info
    return &(this->double_buffer[this->consumer]);
}

// Get empty buffer pointer
Buffer* DoubleBuffer::get_buffer_pointer(int index)
{
    if (index <= nbuffers)
        return &(this->double_buffer[index]);

    return nullptr;
}

// Ready from buffer, mark as processed
void DoubleBuffer::release_buffer()
{
    // Set buffer as processed
    this->double_buffer[this->consumer].mutex -> lock();
    this->double_buffer[this->consumer].channel = -1;
    this->double_buffer[this->consumer].index = -1;
    this->double_buffer[this->consumer].ready = false;
    this->double_buffer[this->consumer].ref_time = DBL_MAX;
    this->double_buffer[this->consumer].read_samples = 0;
    this->double_buffer[this->consumer].nof_packets = 0;
    this->double_buffer[this->consumer].mutex -> unlock();

    // Move consumer pointer
    this->consumer = (this->consumer + 1) % nbuffers;
}

// Clear double buffer
void DoubleBuffer::clear()
{
  // Initialise and allocate buffers in each struct instance
  for(unsigned i = 0; i < nbuffers; i++)
  {
      double_buffer[i].ref_time = DBL_MAX;
      double_buffer[i].ready    = false;
      double_buffer[i].channel  = -1;
      double_buffer[i].nof_antennas  = nof_antennas;
      double_buffer[i].nof_samples = nof_samples;
      double_buffer[i].nof_pols  = nof_pols;
      memset(double_buffer[i].data, 0, nof_samples * nof_antennas *
             nof_pols * sizeof(uint16_t));
  }
}
