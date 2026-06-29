#include <gtest/gtest.h>
#include "TccSplitRing.h"

// ── Constants ────────────────────────────────────────────────────────────────

static constexpr uint16_t NOF_ANT   = 4;
static constexpr uint16_t ACT_ANT   = 4;
static constexpr uint32_t SPLIT_M   = 8;   // M-blocks per split
static constexpr uint8_t  NOF_POLS  = 2;
static constexpr uint32_t RING_SIZE = 4;
static constexpr uint32_t TIMES     = 16;  // kTimesPerBlock (fixed by TCC)

// Build a packet payload of `blocks` M-blocks for `nof_ant` antennas.
// Source layout expected by write_data is [T][R][P], size = blocks*T*R*P.
static std::vector<uint16_t> make_packet(uint32_t blocks, uint16_t nof_ant,
                                          uint16_t fill_value = 0x0001)
{
    return std::vector<uint16_t>(blocks * TIMES * nof_ant * NOF_POLS, fill_value);
}

// ── Fixture ───────────────────────────────────────────────────────────────────

class SplitRingTest : public ::testing::Test {
protected:
    TccSplitRing ring_{NOF_ANT, SPLIT_M, NOF_POLS, ACT_ANT, RING_SIZE};
};

// ── Initial state ─────────────────────────────────────────────────────────────

TEST_F(SplitRingTest, InitialSlotStateIsEmpty)
{
    for (uint32_t i = 0; i < RING_SIZE; ++i)
        EXPECT_EQ(ring_.slot(i).state.load(), SlotState::EMPTY);
}

TEST_F(SplitRingTest, RingSizeAndSplitMAccessors)
{
    EXPECT_EQ(ring_.ring_size(), RING_SIZE);
    EXPECT_EQ(ring_.split_m(),   SPLIT_M);
}

// ── State machine: EMPTY to FILLING to READY ───────────────────────────────────

TEST_F(SplitRingTest, FirstWriteTransitionsEmptyToFilling)
{
    auto pkt = make_packet(1, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, 1, pkt.data(), 1.0, 1));
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::FILLING);
}

TEST_F(SplitRingTest, AllBlocksWrittenTransitionsFillingToReady)
{
    auto pkt = make_packet(SPLIT_M, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, SPLIT_M, pkt.data(), 1.0, 1));
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::READY);
}

TEST_F(SplitRingTest, PartialWriteKeepsSlotInFilling)
{
    auto pkt = make_packet(SPLIT_M / 2, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, SPLIT_M / 2, pkt.data(), 1.0, 1));
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::FILLING);
}

TEST_F(SplitRingTest, WriteReturnsTrueOnSuccess)
{
    auto pkt = make_packet(1, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, 1, pkt.data(), 1.0, 1));
}

// ── Slot index: modular mapping ───────────────────────────────────────────────

TEST_F(SplitRingTest, SlotIndexIsGlobalSplitModRingSize)
{
    // Two distinct global_splits that map to the same ring slot.
    // We fill the first, release it, then fill via the second split.
    auto pkt = make_packet(SPLIT_M, NOF_ANT);

    EXPECT_TRUE(ring_.write_data(/*global_split=*/0, 0, NOF_ANT, 0, SPLIT_M, pkt.data(), 1.0, 1));
    ASSERT_EQ(ring_.slot(0).state.load(), SlotState::READY);

    // Transition READY to PROCESSING manually then release so the slot is free.
    ring_.slot(0).state.store(SlotState::PROCESSING);
    ring_.release_slot(0);
    ASSERT_EQ(ring_.slot(0).state.load(), SlotState::EMPTY);

    // global_split == RING_SIZE maps to slot 0 again.
    EXPECT_TRUE(ring_.write_data(/*global_split=*/RING_SIZE, 0, NOF_ANT, 0, 1, pkt.data(), 2.0, 1));
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::FILLING);
}

// ── mark_consumed / late-packet drop ─────────────────────────────────────────

TEST_F(SplitRingTest, LatePacketDroppedAfterMarkConsumed)
{
    ring_.mark_consumed(0);  // consumed_up_to_ becomes 1

    auto pkt = make_packet(1, NOF_ANT);
    EXPECT_FALSE(ring_.write_data(0, 0, NOF_ANT, 0, 1, pkt.data(), 1.0, 1));
}

TEST_F(SplitRingTest, FreshPacketAcceptedAfterMarkConsumed)
{
    ring_.mark_consumed(0);  // consumed_up_to_ = 1; split 0 is gone, split 1 is fine

    auto pkt = make_packet(1, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(1, 0, NOF_ANT, 0, 1, pkt.data(), 2.0, 1));
}

// ── release_slot ─────────────────────────────────────────────────────────────

TEST_F(SplitRingTest, ReleaseSlotResetsProcessingToEmpty)
{
    ring_.slot(0).state.store(SlotState::PROCESSING);
    ring_.release_slot(0);
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::EMPTY);
}

TEST_F(SplitRingTest, ReleaseSlotIgnoresNonProcessingState)
{
    // READY slot should not be cleared by release_slot.
    ring_.slot(0).state.store(SlotState::READY);
    ring_.release_slot(0);
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::READY);
}

// ── safe_m watermark ─────────────────────────────────────────────────────────

TEST_F(SplitRingTest, SafeMIsZeroBeforeAnyWrite)
{
    EXPECT_EQ(ring_.safe_m(0), 0u);
}

TEST_F(SplitRingTest, SafeMEqualsBlocksWrittenWhenAllAntennasPresent)
{
    auto pkt = make_packet(SPLIT_M, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, SPLIT_M, pkt.data(), 1.0, 1));
    EXPECT_EQ(ring_.safe_m(0), SPLIT_M);
}

TEST_F(SplitRingTest, SafeMReflectsMinimumAcrossAntennas)
{
    // Write 4 blocks for antennas 0-1, 2 blocks for antennas 2-3.
    // safe_m should be min(4,2) = 2.
    auto pkt4 = make_packet(4, 2);
    auto pkt2 = make_packet(2, 2);
    EXPECT_TRUE(ring_.write_data(0, 0, 2, 0, 4, pkt4.data(), 1.0, 1));
    EXPECT_TRUE(ring_.write_data(0, 2, 2, 0, 2, pkt2.data(), 1.0, 1));
    EXPECT_EQ(ring_.safe_m(0), 2u);
}

TEST_F(SplitRingTest, SafeMAdvancesAsPacketsArrive)
{
    // safe_m only advances when the slowest antenna catches up - it is the
    // minimum watermark across all active antennas.  This test drives packets
    // in two-block chunks and checks safe_m after each step.
    auto pkt_all = make_packet(2, NOF_ANT);  // 2 blocks, all 4 antennas
    auto pkt_2   = make_packet(2, 2);        // 2 blocks, 2 antennas

    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::EMPTY);

    // All four antennas write blocks 0-1.
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, 2, pkt_all.data(), 1.0, 1));
    EXPECT_EQ(ring_.safe_m(0), 2u);
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::FILLING);

    // All four antennas write blocks 2-3.
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 2, 2, pkt_all.data(), 1.0, 1));
    EXPECT_EQ(ring_.safe_m(0), 4u);
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::FILLING);

    // Only antennas 0-1 write blocks 4-5 - safe_m stays at 4 while 2-3 lag.
    EXPECT_TRUE(ring_.write_data(0, 0, 2, 4, 2, pkt_2.data(), 1.0, 1));
    EXPECT_EQ(ring_.safe_m(0), 4u);
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::FILLING);

    // Antennas 2-3 catch up with blocks 4-5 - safe_m advances to 6.
    EXPECT_TRUE(ring_.write_data(0, 2, 2, 4, 2, pkt_2.data(), 1.0, 1));
    EXPECT_EQ(ring_.safe_m(0), 6u);
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::FILLING);

    // All antennas write the final blocks 6-7 - safe_m reaches split_m and
    // the slot transitions to READY.
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 6, 2, pkt_all.data(), 1.0, 1));
    EXPECT_EQ(ring_.safe_m(0), SPLIT_M);
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::READY);
}

// ── flush / check_and_reset ───────────────────────────────────────────────────

TEST_F(SplitRingTest, FlushForcesFillingSlotToReady)
{
    auto pkt = make_packet(1, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, 1, pkt.data(), 1.0, 1));
    ASSERT_EQ(ring_.slot(0).state.load(), SlotState::FILLING);

    ring_.flush();
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::READY);
}

TEST_F(SplitRingTest, FlushLeavesEmptySlotsEmpty)
{
    ring_.flush();
    EXPECT_EQ(ring_.slot(1).state.load(), SlotState::EMPTY);
}

TEST_F(SplitRingTest, CheckAndResetReturnsFalseWithoutFlush)
{
    EXPECT_FALSE(ring_.check_and_reset());
}

TEST_F(SplitRingTest, CheckAndResetReturnsTrueAfterFlush)
{
    ring_.flush();
    EXPECT_TRUE(ring_.check_and_reset());
}

TEST_F(SplitRingTest, CheckAndResetClearsConsumedWatermark)
{
    ring_.mark_consumed(99);
    ring_.flush();
    ring_.check_and_reset();

    // After reset, split 0 should be accepted again (consumed_up_to_ = 0).
    auto pkt = make_packet(1, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, 1, pkt.data(), 1.0, 1));
}

TEST_F(SplitRingTest, CheckAndResetIdempotentOnSecondCall)
{
    ring_.flush();
    EXPECT_TRUE(ring_.check_and_reset());  // first call should return true
    EXPECT_FALSE(ring_.check_and_reset());  // flag should be cleared after first call
}

// ── Slot metadata ─────────────────────────────────────────────────────────────

TEST_F(SplitRingTest, RefTimeIsSetFromFirstPacket)
{
    auto pkt = make_packet(1, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, 1, pkt.data(), 42.5, 1));
    EXPECT_DOUBLE_EQ(ring_.slot(0).ref_time.load(), 42.5);
}

TEST_F(SplitRingTest, RefTimeKeepsMinimumAcrossPackets)
{
    auto pkt = make_packet(1, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, 1, pkt.data(), 10.0, 1));
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 1, 1, pkt.data(),  5.0, 1));
    EXPECT_DOUBLE_EQ(ring_.slot(0).ref_time.load(), 5.0);
}

TEST_F(SplitRingTest, ChannelIsRecordedOnSlot)
{
    auto pkt = make_packet(1, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, 1, pkt.data(), 1.0, /*channel=*/7));
    EXPECT_EQ(ring_.slot(0).channel, 7);
}

// ── Full consumer cycle: READY to PROCESSING to EMPTY ─────────────────────────

TEST_F(SplitRingTest, FullConsumerCycleReadyToProcessingToEmpty)
{
    auto pkt = make_packet(SPLIT_M, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, SPLIT_M, pkt.data(), 1.0, 1));
    ASSERT_EQ(ring_.slot(0).state.load(), SlotState::READY);

    // Would be done by the consumer after committing to processing the split.
    ring_.slot(0).state.store(SlotState::PROCESSING);
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::PROCESSING);

    ring_.release_slot(/*global_split=*/0);
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::EMPTY);
}

TEST_F(SplitRingTest, SlotIsReusableAfterFullConsumerCycle)
{
    auto pkt = make_packet(SPLIT_M, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, SPLIT_M, pkt.data(), 1.0, 1));
    ring_.slot(0).state.store(SlotState::PROCESSING);
    ring_.mark_consumed(0);
    ring_.release_slot(0);
    ASSERT_EQ(ring_.slot(0).state.load(), SlotState::EMPTY);

    // global_split == RING_SIZE maps back to slot 0 for the next integration.
    EXPECT_TRUE(ring_.write_data(RING_SIZE, 0, NOF_ANT, 0, 1, pkt.data(), 2.0, 1));
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::FILLING);
}

TEST_F(SplitRingTest, WriteToReadySlotIsDropped)
{
    auto pkt = make_packet(SPLIT_M, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, SPLIT_M, pkt.data(), 1.0, 1));
    ASSERT_EQ(ring_.slot(0).state.load(), SlotState::READY);

    // Stale packet for the same split after the slot is already READY.
    EXPECT_FALSE(ring_.write_data(0, 0, NOF_ANT, 0, 1, pkt.data(), 1.5, 1));
    EXPECT_EQ(ring_.slot(0).state.load(), SlotState::READY);
}

// ── Data layout [M][R][P][T] ──────────────────────────────────────────────────

TEST_F(SplitRingTest, DataIsWrittenInMRPTLayout)
{
    // Single antenna, single block to make index arithmetic easy to verify.
    // write_data transposes [T][R][P] to [M][R][P][T].
    constexpr uint16_t VAL       = 0xABCD;
    constexpr uint16_t M_LOCAL   = 2;

    TccSplitRing small(/*nof_antennas=*/1, SPLIT_M, NOF_POLS,
                       /*nof_active=*/1, RING_SIZE);
    auto pkt = make_packet(1, 1, VAL);
    EXPECT_TRUE(small.write_data(0, 0, 1, M_LOCAL, /*blocks=*/1, pkt.data(), 1.0, 0));

    // Expected offset for [M=2][R=0][P=0][T=0]:
    //   m_stride = nof_antennas * nof_pols * TIMES = 1 * 2 * 16 = 32
    //   offset   = M_LOCAL * m_stride + 0 + 0 = 2 * 32 = 64
    const uint16_t *base = small.slot(0).data;
    const size_t    offset = M_LOCAL * 1u * NOF_POLS * TIMES;
    EXPECT_EQ(base[offset], VAL);
}

// ── Data zeroing on slot reopen ───────────────────────────────────────────────

TEST_F(SplitRingTest, DataIsZeroedOnSlotReopen)
{
    // First integration: all antennas, all blocks, non-zero fill.
    auto pkt_full = make_packet(SPLIT_M, NOF_ANT, 0xFFFF);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, SPLIT_M, pkt_full.data(), 1.0, 1));
    ASSERT_EQ(ring_.slot(0).state.load(), SlotState::READY);

    // Antenna 1, block 0, pol 0, time 0: offset = 1 * nof_pols * TIMES = 32.
    constexpr size_t r_stride = NOF_POLS * TIMES;
    ASSERT_EQ(ring_.slot(0).data[1 * r_stride], 0xFFFFu);

    // Full consumer cycle to EMPTY.
    ring_.slot(0).state.store(SlotState::PROCESSING);
    ring_.mark_consumed(0);
    ring_.release_slot(0);
    ASSERT_EQ(ring_.slot(0).state.load(), SlotState::EMPTY);

    // Second integration: only antenna 0, block 0 - antenna 1 is never written.
    auto pkt_one = make_packet(1, 1, 0xABCD);
    EXPECT_TRUE(ring_.write_data(RING_SIZE, 0, 1, 0, 1, pkt_one.data(), 2.0, 1));

    // Antenna 1 must be zero: the EMPTY to FILLING memset cleared the stale data.
    EXPECT_EQ(ring_.slot(0).data[1 * r_stride], 0u);
}

// ── Slot counters: nof_packets and read_samples ───────────────────────────────

TEST_F(SplitRingTest, NofPacketsCountsWriteDataCalls)
{
    auto pkt = make_packet(1, NOF_ANT);
    for (uint32_t b = 0; b < 3; ++b)
        EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, b, 1, pkt.data(), 1.0, 1));
    EXPECT_EQ(ring_.slot(0).nof_packets.load(), 3u);
}

TEST_F(SplitRingTest, ReadSamplesCountsOnlyAntenna0Writes)
{
    // start_antenna=0 to read_samples increments by blocks * kTimesPerBlock.
    auto pkt = make_packet(2, NOF_ANT);
    EXPECT_TRUE(ring_.write_data(0, 0, NOF_ANT, 0, 2, pkt.data(), 1.0, 1));
    EXPECT_EQ(ring_.slot(0).read_samples.load(), 2u * TIMES);

    // start_antenna=2 to read_samples must not change.
    auto pkt2 = make_packet(2, 2);
    EXPECT_TRUE(ring_.write_data(0, 2, 2, 2, 2, pkt2.data(), 1.0, 1));
    EXPECT_EQ(ring_.slot(0).read_samples.load(), 2u * TIMES);
}

// ── nof_active_antennas < nof_antennas ───────────────────────────────────────

TEST_F(SplitRingTest, InactiveAntennasIgnoredInSafeMAndReadyTransition)
{
    // 6-antenna buffer, only 4 active - antennas 4 and 5 never write data.
    TccSplitRing ring(/*nof_antennas=*/6, SPLIT_M, NOF_POLS, /*nof_active=*/4, RING_SIZE);

    auto pkt = make_packet(SPLIT_M, /*nof_antennas=*/4);
    EXPECT_TRUE(ring.write_data(0, 0, 4, 0, SPLIT_M, pkt.data(), 1.0, 1));

    // safe_m considers only the 4 active antennas, all of which are complete.
    EXPECT_EQ(ring.safe_m(0), SPLIT_M);
    // Slot is READY even though antennas 4–5 never wrote.
    EXPECT_EQ(ring.slot(0).state.load(), SlotState::READY);
}
