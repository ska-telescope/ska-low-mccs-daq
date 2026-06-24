//
// Created by Tom Moynihan on 22/08/2025.
//
#pragma once

#include <atomic>
#include <cstdint>
#include <ctime>
#include <memory>
#include <vector>

#include <cudawrappers/cu.hpp>

// ---------------------------------------------------------------------------
// Slot state machine: EMPTY → FILLING → READY → PROCESSING → EMPTY
// ---------------------------------------------------------------------------
enum class SlotState : uint32_t
{
    EMPTY      = 0,
    FILLING    = 1,
    READY      = 2,
    PROCESSING = 3,
};

struct SplitSlot
{
    uint16_t              *data;         // alias into pinned HostMemory owned by TccSplitRing
    std::atomic<SlotState> state{SlotState::EMPTY};
    std::atomic<double>    ref_time{0.0};
    std::atomic<uint32_t>  nof_packets{0};
    std::atomic<uint32_t>  read_samples{0};
    int                    channel      = -1; // written before FILLING published; read after READY
};

// ---------------------------------------------------------------------------
// TccSplitRing
//
// A circular ring of N pinned host-memory slots, each holding one split's
// worth of sample data in the [M][R][P][T] layout expected by libtcc.
//
// The producer (packet thread) maps each incoming packet to a slot via
//   slot_idx = (m_global_in_integration / split_m) % ring_size
// and writes the transposed data directly.  Once every active antenna has
// written all split_m M-blocks the slot transitions to READY.
//
// The consumer (correlator thread) waits for READY, submits an H2D copy,
// and immediately releases the slot (PROCESSING → EMPTY) so the ring slot
// can be reused ~1 integration later.
// ---------------------------------------------------------------------------
class TccSplitRing
{
public:
    TccSplitRing(uint16_t nof_antennas, uint32_t split_m, uint8_t nof_pols,
                 uint16_t nof_active_antennas, uint32_t ring_size);
    ~TccSplitRing() = default;

    // Producer: write a block of samples from a single packet into the ring.
    // global_split: monotonically increasing split index (integ * nof_splits + split_in_integ).
    // m_local: M-block index within the split [0, split_m).
    // blocks:  number of complete 16-sample M-blocks in this call.
    // Returns false and drops the write if the slot is not yet free or already consumed.
    bool write_data(uint64_t global_split, uint16_t start_antenna, uint16_t nof_included,
                    uint32_t m_local, uint32_t blocks,
                    const uint16_t *data_ptr, double timestamp, int channel);

    // Consumer: permanently discard all packets at or below global_split.
    // Called immediately after the consumer commits to processing a split, so
    // any late-arriving packets for that split are dropped rather than written
    // into a slot belonging to a future integration.
    void mark_consumed(uint64_t global_split);

    // Consumer: minimum M-block watermark across active antennas for slot_idx.
    uint32_t safe_m(uint32_t slot_idx) const;

    // Consumer: direct slot access for early-streaming host pointer.
    SplitSlot &slot(uint32_t slot_idx) { return slots_[slot_idx]; }

    // Consumer: release slot after H2D has been submitted to the CUDA stream.
    void release_slot(uint32_t split_idx);

    // Producer: called on packet-stream timeout. Forces any FILLING slots to
    // READY so the consumer can drain the current (partial) integration and
    // complete cleanly. Also sets a flag that the consumer checks at the next
    // integration boundary to reset consumed_up_to_ and consumer_integ_.
    void flush();

    // Consumer: call at each integration boundary (after ++consumer_integ_).
    // If a flush() is pending, resets consumed_up_to_ to 0 and returns true
    // so the caller can also reset consumer_integ_ to 0.
    bool check_and_reset();

    uint32_t ring_size()  const { return ring_size_; }
    uint32_t split_m()    const { return split_m_; }

private:
    uint16_t nof_antennas_;
    uint16_t nof_active_antennas_;
    uint32_t split_m_;
    uint8_t  nof_pols_;
    uint32_t ring_size_;
    static constexpr uint8_t kTimesPerBlock = 16; // fixed by TCC for complex int8

    std::vector<std::unique_ptr<cu::HostMemory>> pinned_;
    std::unique_ptr<SplitSlot[]>                 slots_;

    // Flat: antenna_hi_[slot_idx * nof_antennas_ + r] = highest M-block
    // written for antenna r in slot slot_idx.  Reset to 0 on each new fill.
    std::unique_ptr<std::atomic<uint32_t>[]> antenna_hi_;

    // Monotonically increasing watermark: every global_split < consumed_up_to_
    // has been committed to the consumer; late packets for those splits are dropped.
    std::atomic<uint64_t> consumed_up_to_{0};

    // Set by flush() when the packet stream has stopped; cleared by check_and_reset()
    // at the next integration boundary so both counters reset safely.
    std::atomic<bool> reset_pending_{false};
};
