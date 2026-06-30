// Unit tests for StationRawDoubleBuffer (StationDataRaw.cpp).
//
// StationRawDoubleBuffer stores raw channelised voltage samples in a rotating
// set of N buffers.  It supports two copy modes: non-transposed
// (channel/sample/pol layout) and transposed (sample/channel/pol layout).
// A buffer is marked ready when the producer advances far enough to leave it
// two slots behind.
//
// Compiled as a single TU by including the implementation directly.
#include "StationDataRaw.cpp"  // NOLINT(bugprone-suspicious-include)

#include <cfloat>
#include <climits>
#include <cstring>
#include <vector>

#include <gtest/gtest.h>

#include "DAQ.h"

// ── Geometry ──────────────────────────────────────────────────────────────────

static constexpr uint16_t START_CH  = 0;
static constexpr uint32_t N_SAMP    = 8;
static constexpr uint16_t N_CHANS   = 2;
static constexpr uint8_t  N_POLS    = 2;
static constexpr uint8_t  N_BUFS    = 4;
static constexpr uint32_t SAMP_PKT  = 4;  // samples per write_data call
// advance fires when counter_diff >= N_SAMP / SAMP_PKT = 2
// 7 sequential writes (counters 1..7) are enough to mark buf[0] ready

// ── Helpers ───────────────────────────────────────────────────────────────────

static std::vector<uint16_t> make_raw_payload(uint16_t val = 0x0001)
{
    return std::vector<uint16_t>(SAMP_PKT * N_POLS, val);
}

// Drive db to the state where buf[0] is ready using 7 sequential write_data
// calls on channel START_CH.
static void fill_to_ready(StationRawDoubleBuffer *db,
                           double ts = 1.0, uint32_t freq = 1000000)
{
    auto p = make_raw_payload();
    for (uint64_t pc = 1; pc <= 7; ++pc)
        db->write_data(SAMP_PKT, START_CH, pc, p.data(), ts, freq, /*offset=*/0);
}

// ── Fixture ───────────────────────────────────────────────────────────────────

class StationRawDoubleBufferTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        attachLogger([](int, const char *) {});
        db = new StationRawDoubleBuffer(START_CH, N_SAMP, N_CHANS, N_POLS,
                                        /*transpose=*/false, N_BUFS);
    }
    void TearDown() override { delete db; attachLogger(nullptr); }
    StationRawDoubleBuffer *db = nullptr;
};

// ── Construction ──────────────────────────────────────────────────────────────

TEST_F(StationRawDoubleBufferTest, ConstructorInitialisesBufferNotReady)
{
    EXPECT_EQ(db->read_buffer(), nullptr);
}

// ── write_data: single call ───────────────────────────────────────────────────

TEST_F(StationRawDoubleBufferTest, WriteDataSetsBufferIndex)
{
    auto p = make_raw_payload();
    db->write_data(SAMP_PKT, START_CH, 3, p.data(), 1.0, 1000000, 0);
    EXPECT_EQ(db->read_buffer(), nullptr);
}

// ── Buffer advance and ready marking ─────────────────────────────────────────

TEST_F(StationRawDoubleBufferTest, SevenWritesMarkFirstBufferReady)
{
    fill_to_ready(db);
    EXPECT_NE(db->read_buffer(), nullptr);
}

// ── Non-transposed copy (channel/sample/pol layout) ───────────────────────────

// With transpose=false (the fixture default), data for channel C goes to
// data + C * N_SAMP * N_POLS.  Within a channel, packet at counter K (buf[0]
// sample_index=1) starts at offset (K-1)*SAMP_PKT*N_POLS.
TEST_F(StationRawDoubleBufferTest, NonTransposedCopyPreservesData)
{
    auto p1 = make_raw_payload(0x1111);
    auto p2 = make_raw_payload(0x2222);
    db->write_data(SAMP_PKT, START_CH, 1, p1.data(), 1.0, 1000000, 0);
    db->write_data(SAMP_PKT, START_CH, 2, p2.data(), 1.0, 1000000, 0);
    for (uint64_t pc = 3; pc <= 7; ++pc) {
        auto p = make_raw_payload();
        db->write_data(SAMP_PKT, START_CH, pc, p.data(), 1.0, 1000000, 0);
    }
    auto *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    // counter=1 → data[0..7]
    EXPECT_EQ(buf->data[0], 0x1111u);
    EXPECT_EQ(buf->data[1], 0x1111u);
    // counter=2 → data[8..15]  (SAMP_PKT * N_POLS = 8)
    EXPECT_EQ(buf->data[SAMP_PKT * N_POLS], 0x2222u);
    db->release_buffer();
}

// ── Transposed copy (sample/channel/pol layout) ───────────────────────────────

// With transpose=true and nof_channels=2, each sample stride is
// nof_channels * nof_pols = 4.  Channel 0 sits at stride offset 0 and
// channel 1 at stride offset nof_pols = 2.
TEST_F(StationRawDoubleBufferTest, TransposedCopyInterleavesSamplesAndChannels)
{
    delete db;
    db = new StationRawDoubleBuffer(START_CH, N_SAMP, N_CHANS, N_POLS,
                                    /*transpose=*/true, N_BUFS);

    auto p_ch0 = make_raw_payload(0x1111);
    auto p_ch1 = make_raw_payload(0x2222);
    db->write_data(SAMP_PKT, /*channel=*/0, 1, p_ch0.data(), 1.0, 1000000, 0);
    db->write_data(SAMP_PKT, /*channel=*/1, 1, p_ch1.data(), 1.0, 1000000, 0);
    for (uint64_t pc = 2; pc <= 7; ++pc) {
        auto p = make_raw_payload();
        db->write_data(SAMP_PKT, START_CH, pc, p.data(), 1.0, 1000000, 0);
    }
    auto *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    // Sample 0 layout: [ch0_p0, ch0_p1, ch1_p0, ch1_p1]
    EXPECT_EQ(buf->data[0], 0x1111u);
    EXPECT_EQ(buf->data[1], 0x1111u);
    EXPECT_EQ(buf->data[2], 0x2222u);
    EXPECT_EQ(buf->data[3], 0x2222u);
    db->release_buffer();
}

// ── Late packet routing ───────────────────────────────────────────────────────

// A packet with counter smaller than the current producer's sample_index is
// routed back to the previous buffer.
TEST_F(StationRawDoubleBufferTest, LatePacketGoesToPreviousBuffer)
{
    auto p = make_raw_payload();
    // counter=1 → buf[0]; counter=3 → advance to buf[1]; counter=2 → late → buf[0]
    db->write_data(SAMP_PKT, START_CH, 1, p.data(), 1.0, 1000000, 0);
    db->write_data(SAMP_PKT, START_CH, 3, p.data(), 1.0, 1000000, 0);
    db->write_data(SAMP_PKT, START_CH, 2, p.data(), 1.0, 1000000, 0);
    for (uint64_t pc = 4; pc <= 7; ++pc)
        db->write_data(SAMP_PKT, START_CH, pc, p.data(), 1.0, 1000000, 0);
    auto *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_EQ(buf->nof_packets, 2u);  // counter=1 and the late counter=2
    db->release_buffer();
}

// ── Too-old packet is silently discarded ─────────────────────────────────────

// A "late" packet whose counter is also earlier than the buffer BEFORE the
// producer is too old to place anywhere and is dropped.
TEST_F(StationRawDoubleBufferTest, TooOldPacketIsIgnored)
{
    auto p = make_raw_payload();
    // counter=3 → buf[0]; counter=5 → advance to buf[1]
    db->write_data(SAMP_PKT, START_CH, 3, p.data(), 1.0, 1000000, 0);
    db->write_data(SAMP_PKT, START_CH, 5, p.data(), 1.0, 1000000, 0);
    // counter=1: buf[1].sample_index=5 > 1 → late; buf[0].sample_index=3 > 1 → too old → ignored
    db->write_data(SAMP_PKT, START_CH, 1, p.data(), 1.0, 1000000, 0);
    for (uint64_t pc = 6; pc <= 9; ++pc)
        db->write_data(SAMP_PKT, START_CH, pc, p.data(), 1.0, 1000000, 0);
    auto *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_EQ(buf->nof_packets, 1u);  // only counter=3; counter=1 was discarded
    db->release_buffer();
}

// ── ref_time ──────────────────────────────────────────────────────────────────

TEST_F(StationRawDoubleBufferTest, RefTimeTracksMinimumTimestamp)
{
    auto p = make_raw_payload();
    db->write_data(SAMP_PKT, START_CH, 1, p.data(), 5.0, 1000000, 0);
    db->write_data(SAMP_PKT, START_CH, 2, p.data(), 3.0, 1000000, 0);  // earlier
    for (uint64_t pc = 3; pc <= 7; ++pc)
        db->write_data(SAMP_PKT, START_CH, pc, p.data(), 9.0, 1000000, 0);
    auto *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_DOUBLE_EQ(buf->ref_time, 3.0);
    db->release_buffer();
}

// ── frequency ────────────────────────────────────────────────────────────────

// The buffer stores the minimum frequency seen across all writes to it.
TEST_F(StationRawDoubleBufferTest, FrequencyTracksMinimumFrequency)
{
    auto p = make_raw_payload();
    db->write_data(SAMP_PKT, START_CH, 1, p.data(), 1.0, 5000000, 0);
    db->write_data(SAMP_PKT, START_CH, 2, p.data(), 1.0, 3000000, 0);  // smaller
    for (uint64_t pc = 3; pc <= 7; ++pc)
        db->write_data(SAMP_PKT, START_CH, pc, p.data(), 1.0, 9000000, 0);
    auto *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_EQ(buf->frequency, 3000000u);
    db->release_buffer();
}

// ── nof_samples ───────────────────────────────────────────────────────────────

// nof_samples is only incremented for writes to channel == start_channel.
TEST_F(StationRawDoubleBufferTest, NofSamplesCountsStartChannelOnly)
{
    auto p = make_raw_payload();
    // counter=1 goes to ch=1 (not start_channel=0) → nof_samples not counted
    db->write_data(SAMP_PKT, /*channel=*/1, 1, p.data(), 1.0, 1000000, 0);
    // counter=2 goes to ch=0 (= start_channel) → nof_samples += SAMP_PKT
    db->write_data(SAMP_PKT, START_CH, 2, p.data(), 1.0, 1000000, 0);
    for (uint64_t pc = 3; pc <= 7; ++pc)
        db->write_data(SAMP_PKT, START_CH, pc, p.data(), 1.0, 1000000, 0);
    auto *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_EQ(buf->nof_samples, SAMP_PKT);
    db->release_buffer();
}

// ── release_buffer ────────────────────────────────────────────────────────────

TEST_F(StationRawDoubleBufferTest, ReleaseBufferClearsAndAdvancesConsumer)
{
    fill_to_ready(db);
    ASSERT_NE(db->read_buffer(), nullptr);
    db->release_buffer();
    EXPECT_EQ(db->read_buffer(), nullptr);  // consumer now at buf[1], not ready
}

// ── clear ─────────────────────────────────────────────────────────────────────

TEST_F(StationRawDoubleBufferTest, ClearAllBuffersResetsState)
{
    auto p = make_raw_payload();
    db->write_data(SAMP_PKT, START_CH, 1, p.data(), 1.0, 1000000, 0);
    db->clear(-1);
    EXPECT_EQ(db->read_buffer(), nullptr);
}
