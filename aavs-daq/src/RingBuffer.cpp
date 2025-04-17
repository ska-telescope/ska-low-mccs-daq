//
// Created by Alessio Magro on 27/08/2015.
//

#include <cstdlib>
#include <unistd.h>
#include <sys/mman.h>
#include <cmath>
#include <cstring>

#include "Utils.h"
#include "RingBuffer.h"
#include "DAQ.h"

#define STATISTICS

// RingBuffer constructor
RingBuffer::RingBuffer(size_t cell_size, size_t nofcells)
{
    // Initialise producer and consumer
    this->producer = 0;
    this->consumer = 0;

    // Clear producer mutex lock
    this->producer_mutex = false;

    // The cell_size arguments refers to the data content of each cell.
    // Make sure that it's a multiple of cacheline_size
    this->cell_size = (size_t) (ceil(cell_size / (double) CACHE_ALIGNMENT) * CACHE_ALIGNMENT);

    // Make sure that nof_cells is a power of 2
    this->nof_cells = (size_t) pow(2, ceil(log2(nofcells)));

    // Allocate memory using mmap (try using huge pages first)
    this->memory = (uint8_t *) mmap(nullptr,  this->cell_size * this->nof_cells * sizeof(uint8_t),
                                    PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB, -1, 0);

    // If failed to use huge pages, use normal pages
    if (this->memory == MAP_FAILED) {
        LOG(DEBUG, "RingBuffer: Could not use huge pages, using normal pages");
        this->memory = (uint8_t *) mmap(nullptr, this->cell_size * this->nof_cells * sizeof(uint8_t),
                                        PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);

        // If huge pages are not used, then they can be swapped to disk. Use mlock?
    }

    // Allocate cell data pointers
    allocate_aligned((void **) &cell_data, (size_t) CACHE_ALIGNMENT, this->nof_cells * sizeof(uint8_t*));

    // Allocate ring buffer cell pointers
    allocate_aligned((void **) &(this->ring_buffer), (size_t) CACHE_ALIGNMENT, this->nof_cells * sizeof(cell));

    // Partition allocated memory into cells and update ring buffer cell pointers
    for(unsigned c = 0; c < this->nof_cells; c++)
    {
        ring_buffer[c].size = 0;
        ring_buffer[c].lock = false;
        cell_data[c] = (uint8_t *) __builtin_assume_aligned(this->memory + c * this->cell_size * sizeof(uint8_t), PAGE_ALIGNMENT);
    }

    // Create diagnostic thread if required
    full_cells = 0;
#ifdef STATISTICS
    diagnostic_thread = new std::thread(&RingBuffer::print_diagnostic, this);
#endif
}

// RingBuffer destructor
RingBuffer::~RingBuffer()
{
    // Kill diagnostic thread and join
    stop_thread = true;
    diagnostic_thread->join();

#ifdef STATISTICS
    delete diagnostic_thread;
#endif

    // Free used memory
    munmap(this->memory, this->cell_size * this->nof_cells * sizeof(uint8_t));
    free(this->cell_data);
    free(this->ring_buffer);
}

bool RingBuffer::push(uint8_t *data, size_t data_size)
{
    // In a multi-producer system, the producer index may be adjusted by one producer instance
    // whilst another producer instance is using a cache version of the original. Grab a snapshot
    // of the current producer index. The cell's lock will ensure that only one producer may fill
    // it.
    size_t local_producer;
    while (true) {

        if (full_cells == nof_cells) {
            lost++;
            return false;
        }

        local_producer = producer.load();

        // If producer and consumer are pointing to the same cell, we have to wait
        // for the consumer to finish reading the cell
        spinlock.Enter(&ring_buffer[local_producer].lock);

        // If the consumer is slow to consume data (or has a temporary spike in compute), then
        // it could be the case that the producer can acquire the lock to the next cell before
        // the consumer, thus overwriting data. In this scenario, the packet is dropped due
        // to slow consumption of data
        if (ring_buffer[local_producer].size > 0) {
            spinlock.Leave(&ring_buffer[local_producer].lock);

            // Advance producer
            spinlock.Enter(&producer_mutex);
            producer = (producer + 1) & (nof_cells - 1);
            spinlock.Leave(&producer_mutex);
        }

        else
            break;
    }

    // Copy to buffer
    std::memcpy(cell_data[local_producer], data, data_size);

    // Done writing data, assign size
    ring_buffer[local_producer].size = data_size;

    // Increases number of pushes
    full_cells++;

    // Finished processing cell, increment producer
    spinlock.Enter(&producer_mutex);
    producer = (producer + 1) & (nof_cells - 1);
    spinlock.Leave(&producer_mutex);

    // Unlock cell
    spinlock.Leave(&ring_buffer[local_producer].lock);

    // Data pushed onto cell
    return true;
}

size_t RingBuffer::pull_timeout(uint8_t **data, double timeout_seconds)
{
    // Start timing
    auto start = std::chrono::high_resolution_clock::now();
    while (true)
    {
        // Acquire lock
        spinlock.Enter(&ring_buffer[consumer].lock);

        // Check if cell size is > 0
        if (ring_buffer[consumer].size == 0)
        {
            // No data to process, release lock and wait for a bit
            spinlock.Leave(&ring_buffer[consumer].lock);

            // Check whether timeout has been reached
            auto end = std::chrono::high_resolution_clock::now();
            std::chrono::duration<double, std::milli> elapsed = end-start;
            if (elapsed.count() * 1e-3 > timeout_seconds)
                return SIZE_MAX;

            // For explanation see pull comment
            if (full_cells == 0)
                std::this_thread::sleep_for(100us);
            else
                consumer = (consumer + 1) & (nof_cells - 1);
        }
        else
          // Otherwise, we can process data
          break;
    }

    // Take note of size
    size_t data_size = ring_buffer[consumer].size;

    // Set packet pointer to cell data
    *data = cell_data[consumer];

    // Return data size
    return data_size;
}

// Consumer an item from the ring buffer
size_t RingBuffer::pull(uint8_t **data)
{
    while (true)
    {
        // Acquire lock
        spinlock.Enter(&ring_buffer[consumer].lock);

        // Check if cell size is > 0
        if (ring_buffer[consumer].size == 0)
        {
            // No data to process, release lock and wait for a bit
            spinlock.Leave(&ring_buffer[consumer].lock);

            // If there are no full cells available, sleep for a bit, otherwise increment
            // consumer and try again. Gaps in the ring buffer may arise through a particular
            // interleaving of multiple producer and consumer trying to access the same group
            // of cells. This mitigates this issue
            if (full_cells == 0)
                std::this_thread::sleep_for(100us);
            else
                consumer = (consumer + 1) & (nof_cells - 1);
        }
        else
          // Otherwise, we can process data
          break;
    }

    // Take note of size and set size to SIZE_MAX, signifying that the data is being copied
    size_t data_size = ring_buffer[consumer].size;

    // Set packet pointer to cell data
    *data = cell_data[consumer];

    // Return data size
    return data_size;
}

// Notify ring buffer that pull is ready
void RingBuffer::pull_ready()
{
    // Finished reading, reset cell size
    ring_buffer[consumer].size = 0;

    // Unlock cell
    spinlock.Leave(&ring_buffer[consumer].lock);

    // All done, increment consumer
    consumer = (consumer + 1) & (nof_cells - 1);

    // Increment number of full cells
    full_cells--;
}

// Diagnostic thread for checking
void RingBuffer::print_diagnostic()
{
    // Loop until instructed to stop
    while (!stop_thread) {
        // Sleep for a while. Sleep in a loop so that a stop command does not take
        // too long to execute
        for(unsigned i = 0; i < 10; i++)
            if(stop_thread) {
                return;
            }
            std::this_thread::sleep_for(0.5s);

        // Print out rate
        if (full_cells > 0) {
            double occupancy = ((float) full_cells / (float) nof_cells) * 100;
            if (occupancy > 75)
                LOG(WARN, "Ring buffer occupancy: %.2f%% (%d %ld)", occupancy, (unsigned) full_cells, nof_cells);
        }
    }
}

// Print statistics and debugging information
void RingBuffer::print_stats() {
    std::cout << std::endl <<
              "Ring Buffer Stats" << std::endl <<
              "-----------------" << std::endl <<
              "- Full Cells : " << this->full_cells.load() << std::endl <<
              "- Lost Pushes : " << this->lost.load() << std::endl <<
              "- Producer : " << this->producer.load() << std::endl <<
              "- Consumer : " << this->consumer.load() << std::endl;

    std::cout << "- Cell Status" << std::endl <<
                 "  -- Producer : " << ring_buffer[this->producer].size << std::endl <<
                 "  -- Consumer : " << ring_buffer[this->consumer].size << std::endl;
}
