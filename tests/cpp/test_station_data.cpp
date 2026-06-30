// Unit tests for StationDoubleBuffer (StationData.cpp).
//
// StationDoubleBuffer is the data side of StationData: it receives accumulated
// channel power via write_data(), buffers it across six rotating slots, marks
// a slot ready when the next time-window of packets arrives, and exposes the
// normalised integrators via read_buffer()/release_buffer().
//
// Compiled as a single TU by including the implementation directly.
#include "StationData.cpp"  // NOLINT(bugprone-suspicious-include)

#include <gtest/gtest.h>
#include <vector>
#include <cstring>

#include "DAQ.h"

// ── Geometry ──────────────────────────────────────────────────────────────────

static constexpr uint16_t N_CHANS     = 4;
static constexpr uint32_t N_SAMP      = 8;
static constexpr uint8_t  N_POLS      = 2;
static constexpr uint8_t  N_BUFS      = 8;   // power of 2; must stay >= 3
static constexpr uint32_t SAMP_PER_PKT = 4;  // samples per write_data call
// packets_per_buffer = N_SAMP / SAMP_PER_PKT = 2
// advances needed to mark buf[0] ready = 3 (buf[0]→buf[1]→buf[2]→buf[3])
// total write_data calls needed = 2 (fill buf[0]) + 5×1 (advance triggers + fill) = 7

// ── Payload helpers ───────────────────────────────────────────────────────────

// Non-saturating payload: real=1, imag=0 for every sample, both pols.
// Per sample: power_x = 1, power_y = 1, not_saturated = 1, read_samples += 1.
// After SAMP_PER_PKT=4 samples: acc=4, read_samples=4 → normalised = 1.0.
static std::vector<uint16_t> make_payload(bool saturate = false)
{
    std::vector<uint16_t> p(SAMP_PER_PKT * N_POLS);
    // Each uint16_t is reinterpreted as two complex8_t bytes: low byte = real, high = imag.
    for (auto &v : p) v = saturate ? 0x7F7F  // real=127, imag=127 → saturated
                                   : 0x0001;  // real=1,   imag=0   → power=1
    return p;
}

// Drive the buffer to the state where buf[0] is ready using 7 sequential
// write_data calls (counters 1..7 inclusive).
static void fill_to_ready(StationDoubleBuffer *db)
{
    auto payload = make_payload();
    for (uint64_t pc = 1; pc <= 7; ++pc)
        db->write_data(/*channel=*/0, SAMP_PER_PKT, pc, payload.data(), 1.0);
}

// ── Fixture ───────────────────────────────────────────────────────────────────

class StationDoubleBufferTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        attachLogger([](int, const char *) {});
        db = new StationDoubleBuffer(N_CHANS, N_SAMP, N_POLS, N_BUFS);
    }
    void TearDown() override
    {
        db->tearDown();
        delete db;
        attachLogger(nullptr);
    }
    StationDoubleBuffer *db = nullptr;
};

// ── Construction ──────────────────────────────────────────────────────────────

TEST_F(StationDoubleBufferTest, ConstructorInitialisesBufferNotReady)
{
    // Before any write, no buffer is ready.
    EXPECT_EQ(db->read_buffer(), nullptr);
}

// ── write_data: single call ───────────────────────────────────────────────────

TEST_F(StationDoubleBufferTest, WriteDataSetsBufferIndex)
{
    auto payload = make_payload();
    db->write_data(0, SAMP_PER_PKT, /*counter=*/3, payload.data(), 1.0);
    // Buffer is not yet ready after one write; no crash is sufficient.
    EXPECT_EQ(db->read_buffer(), nullptr);
}

// ── write_data: saturation detection ─────────────────────────────────────────

// Saturated samples (|value| >= 127) are excluded from the integrator average
// and counted in nof_saturations.  Use a saturated packet as the first write
// and normal fills for the rest.
TEST_F(StationDoubleBufferTest, WriteDataCountsSaturations)
{
    auto sat    = make_payload(/*saturate=*/true);
    auto normal = make_payload();
    db->write_data(0, SAMP_PER_PKT, 1, sat.data(), 1.0);
    for (uint64_t pc = 2; pc <= 7; ++pc)
        db->write_data(0, SAMP_PER_PKT, pc, normal.data(), 1.0);

    StationBuffer *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_GT(buf->nof_saturations, 0u);
}

// Saturated samples are excluded: read_samples[channel] reflects only the
// non-saturated count.
TEST_F(StationDoubleBufferTest, WriteDataExcludesSaturatedSamplesFromAverage)
{
    auto sat    = make_payload(/*saturate=*/true);
    auto normal = make_payload();
    // Counter 1 → saturated packet, counter 2 → normal; rest to reach ready.
    db->write_data(0, SAMP_PER_PKT, 1, sat.data(), 1.0);
    db->write_data(0, SAMP_PER_PKT, 2, normal.data(), 1.0);
    for (uint64_t pc = 3; pc <= 7; ++pc)
        db->write_data(0, SAMP_PER_PKT, pc, normal.data(), 1.0);

    StationBuffer *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    // buf[0] received counters 1 (sat) and 2 (normal).  Only the 4 normal samples
    // in counter 2 are included; read_samples[0] = 4, not 8.
    EXPECT_EQ(buf->read_samples[0], SAMP_PER_PKT);
}

// ── Buffer advance and ready marking ─────────────────────────────────────────

// After 7 write_data calls with sequential counters, the producer has advanced
// three times (packets 3, 5, 7 each trigger an advance).  The third advance
// marks buf[0] ready (producer was at index 2, local_producer = 0).
TEST_F(StationDoubleBufferTest, SevenWritesMarkFirstBufferReady)
{
    fill_to_ready(db);
    StationBuffer *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    // buf[0] held counters 1 and 2 → 2 packets.
    EXPECT_EQ(buf->nof_packets, 2u);
}

// ── read_buffer: normalisation ────────────────────────────────────────────────

// read_buffer divides integrators[i] by read_samples[i] before returning.
// With make_payload() (power=1 per sample, 4 samples per packet, 2 packets in
// buf[0]): acc=8, read_samples=8 → normalised = 1.0.
TEST_F(StationDoubleBufferTest, ReadBufferNormalisesIntegrators)
{
    fill_to_ready(db);
    StationBuffer *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_NEAR(buf->integrators[0],           1.0, 1e-6);  // pol X, channel 0
    EXPECT_NEAR(buf->integrators[N_CHANS + 0], 1.0, 1e-6);  // pol Y, channel 0
}

// ── read_buffer: ref_time ─────────────────────────────────────────────────────

// process_data tracks the minimum timestamp seen within a buffer.
TEST_F(StationDoubleBufferTest, RefTimeTracksMinimumTimestamp)
{
    auto payload = make_payload();
    db->write_data(0, SAMP_PER_PKT, 1, payload.data(), 5.0);
    db->write_data(0, SAMP_PER_PKT, 2, payload.data(), 3.0);  // earlier
    for (uint64_t pc = 3; pc <= 7; ++pc)
        db->write_data(0, SAMP_PER_PKT, pc, payload.data(), 9.0);

    StationBuffer *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_DOUBLE_EQ(buf->ref_time, 3.0);
}

// ── nof_packets ───────────────────────────────────────────────────────────────

// Both packets of a buffer are counted.
TEST_F(StationDoubleBufferTest, NofPacketsCountsBothPacketsInBuffer)
{
    fill_to_ready(db);
    StationBuffer *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_EQ(buf->nof_packets, 2u);
}

// ── release_buffer ────────────────────────────────────────────────────────────

// After release, the consumer pointer advances and the just-released buffer is
// no longer returned by the next read_buffer call.
TEST_F(StationDoubleBufferTest, ReleaseBufferClearsAndAdvancesConsumer)
{
    fill_to_ready(db);
    ASSERT_NE(db->read_buffer(), nullptr);
    db->release_buffer();
    // Consumer advanced to index 1; buf[1] is not ready yet.
    EXPECT_EQ(db->read_buffer(), nullptr);
}

// ── Late packet routing ───────────────────────────────────────────────────────

// A packet whose counter is smaller than the current producer buffer's index is
// a "late" packet — it belongs to the previous buffer.
TEST_F(StationDoubleBufferTest, LatePacketGoesToPreviousBuffer)
{
    auto payload = make_payload();
    // Fill buf[0] with counter=1, then jump to buf[1] with counter=3.
    db->write_data(0, SAMP_PER_PKT, 1, payload.data(), 1.0);  // buf[0]: index=1
    db->write_data(0, SAMP_PER_PKT, 3, payload.data(), 1.0);  // advance → buf[1]
    // Counter=2: buf[1].index=3 > 2 → routed back to buf[0].
    db->write_data(0, SAMP_PER_PKT, 2, payload.data(), 1.0);
    // Continue driving to ready.
    for (uint64_t pc = 4; pc <= 7; ++pc)
        db->write_data(0, SAMP_PER_PKT, pc, payload.data(), 1.0);

    StationBuffer *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_EQ(buf->nof_packets, 2u);  // counter=1 and the late counter=2
}

// ── Packet too far ahead is dropped ───────────────────────────────────────────

// If packet_counter > buffer.index + 2*(nof_samples/SAMP_PER_PKT), the packet
// is beyond the two-buffer lookahead window and is silently discarded.
TEST_F(StationDoubleBufferTest, PacketTooFarAheadIsDropped)
{
    auto payload = make_payload();
    db->write_data(0, SAMP_PER_PKT, 1, payload.data(), 1.0);  // buf[0]: index=1
    // counter=100 is far beyond 1 + 2*(8/4) = 5 → dropped.
    db->write_data(0, SAMP_PER_PKT, 100, payload.data(), 1.0);
    // buf[0] stays with only 1 packet; nothing ready.
    EXPECT_EQ(db->read_buffer(), nullptr);
}

// ── clear ─────────────────────────────────────────────────────────────────────

TEST_F(StationDoubleBufferTest, ClearResetsAllBuffers)
{
    auto payload = make_payload();
    db->write_data(0, SAMP_PER_PKT, 1, payload.data(), 1.0);
    db->clear();
    EXPECT_EQ(db->read_buffer(), nullptr);
}
