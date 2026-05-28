//
// Created by Tom Moynihan on 22/08/2025.
//
#include "TccDoubleBuffer.h"
#include <cstdio>
#include <cstdlib>

TccDoubleBuffer::TccDoubleBuffer(uint16_t na, uint32_t ns,
                                 uint8_t np, uint8_t nb)
    : DoubleBuffer(na, ns, np, nb, false)
{
    cu::init();
    const size_t bytes = (size_t)nof_samples * nof_antennas * nof_pols * sizeof(uint16_t);
    pinned_.reserve(nbuffers);

    for (unsigned i = 0; i < nbuffers; i++)
    {
        auto mem = std::make_unique<cu::HostMemory>(bytes, CU_MEMHOSTALLOC_WRITECOMBINED);
        double_buffer[i].data = static_cast<uint16_t *>((void *)*mem);
        pinned_.push_back(std::move(mem)); // make sure the memory isn't freed when we leave scope.
    }

    // Value-initialise all watermarks to 0
    antenna_hi_ = std::make_unique<std::atomic<uint32_t>[]>((size_t)nbuffers * nof_antennas);
}

inline void TccDoubleBuffer::copy_data(uint32_t producer_index,
                                uint16_t start_antenna, uint16_t nof_included_antennas,
                                uint64_t start_sample_index, uint32_t samples,
                                uint16_t *data_ptr, double timestamp)
{
    // Target layout: [M][R][P][T], T=16; elements are still uint16_t holding {re_i8, im_i8}
    const uint64_t m_stride = uint64_t(nof_antennas) * nof_pols * times_per_block; // stride per m
    const uint32_t r_stride  = nof_pols * times_per_block;              // stride per r
    const uint32_t src_stride = nof_included_antennas * nof_pols;       // elems per source sample

    uint16_t* base = double_buffer[producer_index].data;
    uint64_t m       = start_sample_index >> 4;
    uint32_t blocks  = samples >> 4;

    for (uint32_t b = 0; b < blocks; ++b, ++m)
    {
        uint16_t* base_m = base + m * m_stride;

        for (uint16_t j = 0; j < nof_included_antennas; ++j)
        {
            const uint32_t r = uint32_t(start_antenna) + j;

            // dst stripes (contiguous along T)
            uint16_t* d0 = base_m + r * r_stride;
            uint16_t* d1 = d0 + times_per_block;

            // src pointers advance by a fixed stride per sample
            uint16_t* s0 = data_ptr + j * nof_pols; // pol 0
            uint16_t* s1 = s0 + 1;                  // pol 1

            for (uint32_t t = 0; t < times_per_block; ++t) {
                d0[t] = *s0;
                d1[t] = *s1;
                s0 += src_stride;
                s1 += src_stride;
            }
        }

        // consumed one 16-sample block from the source
        data_ptr += times_per_block * src_stride;
    }

    // Advance per-antenna watermarks so the consumer can stream completed rows
    const uint32_t final_m = static_cast<uint32_t>(start_sample_index >> 4) + blocks;
    for (uint16_t j = 0; j < nof_included_antennas; ++j)
    {
        auto &hi = antenna_hi_[(size_t)producer_index * nof_antennas + start_antenna + j];
        uint32_t cur = hi.load(std::memory_order_relaxed);
        if (final_m > cur)
            hi.store(final_m, std::memory_order_release);
    }

    if (start_antenna == 0)
        this->double_buffer[producer_index].read_samples += samples;
    this->double_buffer[producer_index].nof_packets++;

    if (this->double_buffer[producer_index].ref_time > timestamp ||
        this->double_buffer[producer_index].ref_time == 0)
        this->double_buffer[producer_index].ref_time = timestamp;
}

void TccDoubleBuffer::release_buffer()
{
    DoubleBuffer::release_buffer(); // advances consumer to the next slot
    // Zero watermarks for the newly-current slot before the consumer thread
    // can call safe_m() and read stale values from the previous fill.
    for (uint16_t r = 0; r < nof_antennas; ++r)
        antenna_hi_[(size_t)consumer * nof_antennas + r].store(0, std::memory_order_relaxed);
}

uint32_t TccDoubleBuffer::safe_m(int buf_idx) const
{
    uint32_t min_m = antenna_hi_[(size_t)buf_idx * nof_antennas].load(std::memory_order_acquire);
    for (uint16_t r = 1; r < nof_antennas; ++r)
    {
        uint32_t val = antenna_hi_[(size_t)buf_idx * nof_antennas + r].load(std::memory_order_acquire);
        if (val < min_m) min_m = val;
    }
    return min_m;
}
