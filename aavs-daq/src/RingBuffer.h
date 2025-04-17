//
// Created by Alessio Magro on 27/08/2015.
//

/* This class is meant to be used as a mediator between a producer thread and a consumer thread.
 * Only one producer and one consumer are supported (at the moment). Priority is given to the
 * producer, such that if the consumer does not manage to consume the data at the rate which they're
 * being generated, the producer will overwrite data cells.
 *
 * This class is meant to provide a high performance ring buffer. The use of mutual exclusion locks
 * is avoided in favour of atomic operations.
 */

#ifndef _RINGBUFFER_H
#define _RINGBUFFER_H

#include <cstdint>
#include <cstddef>
#include <ctime>
#include <unistd.h>

#include <mutex>
#include <atomic>
#include <random>
#include <thread>
#include <chrono>
#include <iostream>

#define INLINE   inline __attribute__((__always_inline__))

using namespace std::chrono_literals;

// --------------------------------- Exponential Spin Lock ---------------------------------
class ExponentialSpinLock
{
public:
    INLINE void Enter(std::atomic_bool *lock)
    {
        size_t curMaxDelay = MIN_BACKOFF_ITERS;

        while (true)
        {
            WaitUntilLockIsFree(lock);

            if (lock->exchange(true, std::memory_order_acquire))
                BackoffExp(curMaxDelay);
            else
                break;
        }
    }

    INLINE void Leave(std::atomic_bool *lock)
    {
        lock->store(false, std::memory_order_release);
    }

private:
    INLINE void WaitUntilLockIsFree(std::atomic_bool *lock) const
    {
        size_t numIters = 0;

        while (lock->load(std::memory_order_relaxed))
        {
            if (numIters < MAX_WAIT_ITERS)
            {
                numIters++;
                __asm volatile ("pause":: : "memory");
            }
            else
            {
               std::this_thread::sleep_for(500us);
             }
        }
    }
    
    INLINE void BackoffExp(size_t &curMaxIters)
    {
        static const size_t MAX_BACKOFF_ITERS = 1024;
        thread_local std::uniform_int_distribution<size_t> dist;
        thread_local std::minstd_rand gen(std::random_device{}());
        
        const size_t spinIters = dist(gen, decltype(dist)::param_type{0, curMaxIters});
        curMaxIters = std::min(2*curMaxIters, MAX_BACKOFF_ITERS);
    
        for (size_t i=0; i<spinIters; i++)
            __asm volatile ("pause":: : "memory");
    }

private:
    static const size_t MAX_WAIT_ITERS    = 0x10000;
    static const size_t MIN_BACKOFF_ITERS = 32;
};

// --------------------------------- Structure Definitions -----------------------------------

// Represents a single cell in the ring buffer.
struct cell
{
    size_t             size;    // Size of data portion of cell
    std::atomic_bool   lock;    // Cell read-write lock
};

// --------------------------------- Ring Buffer Class ---------------------------------------

class RingBuffer
{
public:
    // Class constructor
    RingBuffer(size_t cell_size, size_t nofcells);

    // Class destructor
    ~RingBuffer();

    // Consume an item from the ring buffer
    size_t pull(uint8_t** data);

    // Consume an item from the ring buffer with timeout
    size_t pull_timeout(uint8_t** data, double timeout_seconds);

    // Notify ring buffer that pull has finised
    void pull_ready();

    // Insert a new item into the ring buffer
    bool push(uint8_t* data, size_t data_size);

    // Print statistics and debugging information
    void print_stats();

private:
    // Diagnostic method
    void print_diagnostic();
      
private:
    // The data structure which will hold the data elements.
    uint8_t  *memory;
    cell     *ring_buffer;
    uint8_t  **cell_data;

    // Ring buffer parameters
    size_t  cell_size;
    size_t  nof_cells;

    // Producer and consumer pointers
    // These are declared as volatile so that they are not optimised into registers
    volatile std::atomic<size_t> producer;
    volatile std::atomic<size_t> consumer;

    // Locking handler
    ExponentialSpinLock spinlock;

    // Multi-producer lock
    std::atomic_bool producer_mutex;

    // Diagnostics
    bool stop_thread = false;
    std::thread *diagnostic_thread;
    std::atomic<size_t> full_cells;
    std::atomic<size_t> lost;
};


#endif //_RINGBUFFER_H
