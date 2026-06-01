//
// Created by Tom Moynihan on 22/08/2025.
//
#include "TccSplitRing.h"
#include "DAQ.h" // LOG macro

#include <algorithm>
#include <cassert>

TccSplitRing::TccSplitRing(uint16_t nof_antennas, uint32_t split_m, uint8_t nof_pols,
                             uint16_t nof_active_antennas, uint32_t ring_size)
    : nof_antennas_(nof_antennas),
      nof_active_antennas_(nof_active_antennas),
      split_m_(split_m),
      nof_pols_(nof_pols),
      ring_size_(ring_size)
{
    cu::init();

    const size_t bytes_per_slot =
        (size_t)split_m_ * nof_antennas_ * nof_pols_ * kTimesPerBlock * sizeof(uint16_t);

    // unique_ptr<[]> uses array-new which only needs default-constructible;
    // std::vector requires move-constructible which std::atomic does not satisfy.
    slots_ = std::make_unique<SplitSlot[]>(ring_size_);
    pinned_.reserve(ring_size_);

    for (uint32_t i = 0; i < ring_size_; ++i)
    {
        auto mem = std::make_unique<cu::HostMemory>(bytes_per_slot, CU_MEMHOSTALLOC_WRITECOMBINED);
        slots_[i].data = static_cast<uint16_t *>((void *)*mem);
        pinned_.push_back(std::move(mem));
    }

    // Value-initialise all watermarks to 0
    antenna_hi_ = std::make_unique<std::atomic<uint32_t>[]>((size_t)ring_size_ * nof_antennas_);
}

bool TccSplitRing::write_data(uint32_t split_idx,
                               uint16_t start_antenna, uint16_t nof_included,
                               uint32_t m_local, uint32_t blocks,
                               const uint16_t *data_ptr, double timestamp, int channel)
{
    const uint32_t slot_idx = split_idx % ring_size_;
    SplitSlot     &slot     = slots_[slot_idx];

    SlotState cur = slot.state.load(std::memory_order_acquire);

    if (cur == SlotState::EMPTY)
    {
        // Initialise metadata and watermarks BEFORE publishing FILLING.
        // The release on the CAS below acts as the publication fence: any
        // concurrent reader that observes FILLING via acquire sees clean state.
        for (uint16_t r = 0; r < nof_antennas_; ++r)
            antenna_hi_[slot_idx * nof_antennas_ + r].store(0, std::memory_order_relaxed);
        slot.ref_time.store(timestamp, std::memory_order_relaxed);
        slot.nof_packets.store(0, std::memory_order_relaxed);
        slot.read_samples.store(0, std::memory_order_relaxed);
        slot.split_idx = split_idx;
        slot.channel   = channel;

        SlotState expected = SlotState::EMPTY;
        if (!slot.state.compare_exchange_strong(expected, SlotState::FILLING,
                                                std::memory_order_release,
                                                std::memory_order_relaxed))
        {
            cur = slot.state.load(std::memory_order_acquire);
            if (cur != SlotState::FILLING)
                return false; // unexpected — drop
        }
    }
    else if (cur != SlotState::FILLING)
    {
        // READY or PROCESSING — consumer has not freed this slot yet; drop packet
        LOG(WARN, "TccSplitRing: slot %u not free (state=%u) for split %u — dropping packet",
            slot_idx, (unsigned)cur, split_idx);
        return false;
    }

    // -----------------------------------------------------------------------
    // Scatter-write into [M][R][P][T] layout (same as TccDoubleBuffer::copy_data)
    // -----------------------------------------------------------------------
    const size_t   m_stride   = (size_t)nof_antennas_ * nof_pols_ * kTimesPerBlock;
    const uint32_t r_stride   = nof_pols_ * kTimesPerBlock;
    const uint32_t src_stride = nof_included * nof_pols_;

    uint16_t *base = slot.data;

    for (uint32_t b = 0; b < blocks; ++b)
    {
        uint16_t *base_m = base + (m_local + b) * m_stride;

        for (uint16_t j = 0; j < nof_included; ++j)
        {
            const uint32_t r  = (uint32_t)start_antenna + j;
            uint16_t      *d0 = base_m + r * r_stride;
            uint16_t      *d1 = d0 + kTimesPerBlock;

            const uint16_t *s0 = data_ptr + j * nof_pols_;
            const uint16_t *s1 = s0 + 1;

            for (uint32_t t = 0; t < kTimesPerBlock; ++t)
            {
                d0[t] = *s0;
                d1[t] = *s1;
                s0 += src_stride;
                s1 += src_stride;
            }
        }
        data_ptr += (size_t)kTimesPerBlock * src_stride;
    }

    // Advance per-antenna watermarks atomically (atomic-max via CAS loop)
    const uint32_t final_m = m_local + blocks;
    for (uint16_t j = 0; j < nof_included; ++j)
    {
        auto &hi = antenna_hi_[slot_idx * nof_antennas_ + start_antenna + j];
        uint32_t old = hi.load(std::memory_order_relaxed);
        while (final_m > old &&
               !hi.compare_exchange_weak(old, final_m,
                                         std::memory_order_release,
                                         std::memory_order_relaxed))
            ;
    }

    // Update slot metadata
    if (start_antenna == 0)
        slot.read_samples.fetch_add(blocks * kTimesPerBlock, std::memory_order_relaxed);
    slot.nof_packets.fetch_add(1, std::memory_order_relaxed);

    // Atomic min for ref_time (CAS loop)
    double old_rt = slot.ref_time.load(std::memory_order_relaxed);
    while ((timestamp < old_rt || old_rt == 0.0) &&
           !slot.ref_time.compare_exchange_weak(old_rt, timestamp,
                                                std::memory_order_relaxed,
                                                std::memory_order_relaxed))
        ;

    // Mark READY when every active antenna has written every M-block
    if (safe_m(slot_idx) == split_m_)
    {
        SlotState expected2 = SlotState::FILLING;
        slot.state.compare_exchange_strong(expected2, SlotState::READY,
                                           std::memory_order_release,
                                           std::memory_order_relaxed);
    }

    return true;
}

uint32_t TccSplitRing::safe_m(uint32_t slot_idx) const
{
    uint32_t min_m = antenna_hi_[slot_idx * nof_antennas_].load(std::memory_order_acquire);
    for (uint16_t r = 1; r < nof_active_antennas_; ++r)
    {
        uint32_t v = antenna_hi_[slot_idx * nof_antennas_ + r].load(std::memory_order_acquire);
        if (v < min_m) min_m = v;
    }
    return min_m;
}

void TccSplitRing::release_slot(uint32_t split_idx)
{
    const uint32_t slot_idx = split_idx % ring_size_;
    slots_[slot_idx].state.store(SlotState::EMPTY, std::memory_order_release);
}
