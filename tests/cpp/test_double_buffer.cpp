// Tests for the DoubleBuffer data structure (DoubleBuffer.cpp).
//
// DoubleBuffer is not a DataConsumer — it has no processPacket/onStreamEnd
// interface.  Instead it is the shared-memory relay between a SPEAD-reader
// thread (producer) and a correlator/persister thread (consumer), so tests
// drive its write/read/release interface directly.
//
// Compiled as a single TU by including the implementation directly.
#include "DoubleBuffer.cpp"  // NOLINT(bugprone-suspicious-include)

#include <gtest/gtest.h>
#include <cfloat>
#include <vector>

#include "DAQ.h"

// ── Geometry ──────────────────────────────────────────────────────────────────

static constexpr uint16_t N_ANT  = 4;
static constexpr uint32_t N_SAMP = 8;
static constexpr uint8_t  N_POLS = 2;
static constexpr uint8_t  N_BUFS = 4;  // must be a power of 2

// ── Helper ────────────────────────────────────────────────────────────────────

static std::vector<uint16_t> make_data(size_t count, uint16_t base = 1)
{
    std::vector<uint16_t> v(count);
    for (size_t i = 0; i < count; ++i)
        v[i] = static_cast<uint16_t>(base + i);
    return v;
}

// ── Fixture ───────────────────────────────────────────────────────────────────

class DoubleBufferTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        attachLogger([](int, const char *) {});
        db = new DoubleBuffer(N_ANT, N_SAMP, N_POLS, N_BUFS);
    }
    void TearDown() override
    {
        delete db;
        attachLogger(nullptr);
    }
    DoubleBuffer *db = nullptr;
};

// ── Constructor ───────────────────────────────────────────────────────────────

TEST_F(DoubleBufferTest, ConstructorInitialisesBuffers)
{
    EXPECT_EQ(db->get_number_of_buffers(), N_BUFS);
    EXPECT_EQ(db->get_consumer(), 0);
    for (int i = 0; i < N_BUFS; ++i) {
        Buffer *b = db->get_buffer_pointer(i);
        ASSERT_NE(b, nullptr) << "buffer " << i;
        EXPECT_EQ(b->channel,     -1)    << "buffer " << i;
        EXPECT_FALSE(b->ready)           << "buffer " << i;
        EXPECT_EQ(b->nof_packets, 0u)    << "buffer " << i;
        EXPECT_NE(b->data, nullptr)      << "buffer " << i;
        EXPECT_EQ(b->nof_antennas, N_ANT)  << "buffer " << i;
        EXPECT_EQ(b->nof_samples, N_SAMP)  << "buffer " << i;
        EXPECT_EQ(b->nof_pols, N_POLS)     << "buffer " << i;
    }
}

// ── read_buffer before any writes ────────────────────────────────────────────

TEST_F(DoubleBufferTest, ReadBufferReturnsNullptrWhenNotReady)
{
    EXPECT_EQ(db->read_buffer(), nullptr);
}

// ── write_data: channel assignment ────────────────────────────────────────────

TEST_F(DoubleBufferTest, WriteDataSetsChannel)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, /*channel=*/5, /*start_sample=*/0, /*samples=*/1,
                   data.data(), 1.0);
    EXPECT_EQ(db->get_buffer_pointer(0)->channel, 5);
}

// ── write_data: payload layout ────────────────────────────────────────────────

// copy_data stores data in [sample][antenna][pol] order.  Writing all antennas
// in one call produces contiguous samples with no inter-antenna gaps.
TEST_F(DoubleBufferTest, WriteDataCopiesPayloadLayout)
{
    const uint32_t samples = 2;
    auto src = make_data(samples * N_ANT * N_POLS);
    db->write_data(0, N_ANT, 7, /*start_sample=*/0, samples, src.data(), 1.0);
    db->finish_write();

    Buffer *b = db->read_buffer();
    ASSERT_NE(b, nullptr);
    for (uint32_t s = 0; s < samples; ++s)
        for (uint16_t a = 0; a < N_ANT; ++a)
            for (uint8_t p = 0; p < N_POLS; ++p) {
                size_t dst     = (s * N_ANT + a) * N_POLS + p;
                size_t src_idx =  s * N_ANT * N_POLS + a * N_POLS + p;
                EXPECT_EQ(b->data[dst], src[src_idx])
                    << "s=" << s << " a=" << a << " p=" << +p;
            }
}

// ── write_data: packet counter ────────────────────────────────────────────────

TEST_F(DoubleBufferTest, WriteDataUpdatesNofPackets)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 3, 0, 1, data.data(), 1.0);
    db->write_data(0, N_ANT, 3, 1, 1, data.data(), 1.1);
    db->finish_write();
    EXPECT_EQ(db->read_buffer()->nof_packets, 2u);
}

// ── write_data: read_samples only increments for start_antenna == 0 ──────────

TEST_F(DoubleBufferTest, WriteDataUpdatesReadSamplesOnlyAtAntenna0)
{
    auto half = make_data(N_ANT / 2 * N_POLS);
    // start_antenna=0 → contributes to read_samples.
    db->write_data(0,         N_ANT / 2, 2, 0, 1, half.data(), 1.0);
    // start_antenna=2 → does not increment read_samples.
    db->write_data(N_ANT / 2, N_ANT / 2, 2, 0, 1, half.data(), 1.0);
    db->finish_write();
    EXPECT_EQ(db->read_buffer()->read_samples, 1u);
}

// ── write_data: ref_time tracks minimum timestamp ─────────────────────────────

TEST_F(DoubleBufferTest, WriteDataTracksMinimumTimestamp)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 1, 0, 1, data.data(), 2.0);
    db->write_data(0, N_ANT, 1, 1, 1, data.data(), 1.0);
    db->finish_write();
    EXPECT_DOUBLE_EQ(db->read_buffer()->ref_time, 1.0);
}

// ── finish_write ──────────────────────────────────────────────────────────────

TEST_F(DoubleBufferTest, FinishWriteMarksCurrentBufferReady)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 5, 0, 1, data.data(), 1.0);
    EXPECT_FALSE(db->get_buffer_pointer(0)->ready);
    db->finish_write();
    EXPECT_TRUE(db->get_buffer_pointer(0)->ready);
}

TEST_F(DoubleBufferTest, ReadBufferReturnsReadyBufferAfterFinishWrite)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 5, 0, 1, data.data(), 1.0);
    db->finish_write();
    Buffer *b = db->read_buffer();
    ASSERT_NE(b, nullptr);
    EXPECT_EQ(b->channel, 5);
}

// After a channel switch, finish_write marks both the old and new buffers ready.
TEST_F(DoubleBufferTest, FinishWriteAfterChannelSwitchMarksBothBuffersReady)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 5, 0, 1, data.data(), 1.0);
    db->write_data(0, N_ANT, 6, 0, 1, data.data(), 2.0);
    db->finish_write();
    EXPECT_TRUE(db->get_buffer_pointer(0)->ready);
    EXPECT_TRUE(db->get_buffer_pointer(1)->ready);
}

// ── release_buffer ────────────────────────────────────────────────────────────

TEST_F(DoubleBufferTest, ReleaseBufferClearsAndAdvancesConsumer)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 9, 0, 1, data.data(), 1.0);
    db->finish_write();
    ASSERT_NE(db->read_buffer(), nullptr);
    db->release_buffer();

    EXPECT_EQ(db->get_consumer(), 1);
    Buffer *b = db->get_buffer_pointer(0);
    EXPECT_EQ(b->channel,     -1);
    EXPECT_FALSE(b->ready);
    EXPECT_EQ(b->nof_packets, 0u);
    EXPECT_EQ(b->read_samples, 0u);
}

// Releasing twice wraps the consumer pointer modulo nbuffers.
TEST_F(DoubleBufferTest, ReleaseBufferWrapsConsumerModuloNbuffers)
{
    auto data = make_data(N_ANT * N_POLS);
    for (int i = 0; i < N_BUFS; ++i) {
        db->write_data(0, N_ANT, i, 0, 1, data.data(), double(i));
        db->finish_write();
        ASSERT_NE(db->read_buffer(), nullptr);
        db->release_buffer();
    }
    EXPECT_EQ(db->get_consumer(), 0);  // wrapped back to 0
}

// ── channel switching ─────────────────────────────────────────────────────────

// A write to a different channel advances the producer and starts a new buffer.
TEST_F(DoubleBufferTest, ChannelSwitchAdvancesToNextBuffer)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 5, 0, 1, data.data(), 1.0);
    db->write_data(0, N_ANT, 6, 0, 1, data.data(), 2.0);

    EXPECT_EQ(db->get_buffer_pointer(0)->channel, 5);
    EXPECT_EQ(db->get_buffer_pointer(1)->channel, 6);
}

// Buffer[0] (ch5) only becomes ready once we're two channels ahead: the
// second switch (ch7 write) marks the buffer one behind the previous producer
// as ready.
TEST_F(DoubleBufferTest, TwoChannelSwitchesMarkFirstBufferReady)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 5, 0, 1, data.data(), 1.0);
    db->write_data(0, N_ANT, 6, 0, 1, data.data(), 2.0);
    db->write_data(0, N_ANT, 7, 0, 1, data.data(), 3.0);

    Buffer *b = db->read_buffer();
    ASSERT_NE(b, nullptr);
    EXPECT_EQ(b->channel, 5);
}

// ── late packet (channel < current producer's channel) ────────────────────────

// A packet whose channel is less than the current producer's channel is routed
// back to the previous buffer rather than the current one.
TEST_F(DoubleBufferTest, LatePacketGoesToPreviousBuffer)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 5, 0, 1, data.data(), 1.0);  // buffer[0]: ch5
    db->write_data(0, N_ANT, 6, 0, 1, data.data(), 2.0);  // buffer[1]: ch6
    // Late ch5 packet: goes back into buffer[0].
    db->write_data(0, N_ANT, 5, 1, 1, data.data(), 1.5);

    EXPECT_EQ(db->get_buffer_pointer(0)->nof_packets, 2u);
    EXPECT_EQ(db->get_buffer_pointer(1)->nof_packets, 1u);
}

// ── partial antenna writes interleave correctly ───────────────────────────────

// Two half-width writes (antennas 0..1 and 2..3) should produce the same
// buffer layout as a single full-width write with the same values.
TEST_F(DoubleBufferTest, PartialWritesDeinterleavedIntoFullAntennaLayout)
{
    const uint32_t samples = 1;
    const uint16_t half = N_ANT / 2;
    auto src = make_data(half * N_POLS * samples, 0x100);

    db->write_data(0,    half, 3, 0, samples, src.data(), 1.0);
    db->write_data(half, half, 3, 0, samples, src.data(), 1.0);
    db->finish_write();

    Buffer *b = db->read_buffer();
    ASSERT_NE(b, nullptr);
    // Both antenna halves should hold the same data as src.
    for (uint16_t a = 0; a < half; ++a)
        for (uint8_t p = 0; p < N_POLS; ++p) {
            EXPECT_EQ(b->data[a * N_POLS + p],        src[a * N_POLS + p])
                << "low half a=" << a  << " p=" << +p;
            EXPECT_EQ(b->data[(half + a) * N_POLS + p], src[a * N_POLS + p])
                << "high half a=" << a << " p=" << +p;
        }
}

// ── clear ─────────────────────────────────────────────────────────────────────

TEST_F(DoubleBufferTest, ClearResetsAllBuffers)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data(0, N_ANT, 5, 0, 1, data.data(), 1.0);
    db->clear();

    for (int i = 0; i < N_BUFS; ++i) {
        Buffer *b = db->get_buffer_pointer(i);
        EXPECT_EQ(b->channel, -1) << "buffer " << i;
        EXPECT_FALSE(b->ready)    << "buffer " << i;
        for (size_t j = 0; j < N_ANT * N_SAMP * N_POLS; ++j)
            EXPECT_EQ(b->data[j], 0) << "buffer " << i << " byte " << j;
    }
}

// ── get_buffer_pointer ────────────────────────────────────────────────────────

TEST_F(DoubleBufferTest, GetBufferPointerReturnsValidSlotsInRange)
{
    for (int i = 0; i < N_BUFS; ++i)
        EXPECT_NE(db->get_buffer_pointer(i), nullptr) << "index " << i;
}

TEST_F(DoubleBufferTest, GetBufferPointerReturnsNullForOutOfBounds)
{
    EXPECT_EQ(db->get_buffer_pointer(N_BUFS + 1), nullptr);
}

// ── write_data_single_channel ─────────────────────────────────────────────────

TEST_F(DoubleBufferTest, SingleChannelWriteSetsChannelAndIndex)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data_single_channel(0, N_ANT, /*channel=*/3, /*packet_index=*/7,
                                  /*samples=*/1, data.data(), 1.0);
    Buffer *b = db->get_buffer_pointer(0);
    EXPECT_EQ(b->channel, 3);
    EXPECT_EQ(b->index,   7);
}

// A second call with packet_index=0 and a timestamp far beyond the current
// buffer's ref_time (> nof_samples * 1.08µs) triggers a buffer advance.
TEST_F(DoubleBufferTest, SingleChannelWriteSwitchesBufferOnTimestampBoundary)
{
    auto data = make_data(N_ANT * N_POLS);
    db->write_data_single_channel(0, N_ANT, 3, 0, 1, data.data(), 0.0);
    // ts=1.0 >> 0.0 + (N_SAMP-1)*1.08µs → triggers advance.
    db->write_data_single_channel(0, N_ANT, 3, 0, 1, data.data(), 1.0);
    EXPECT_EQ(db->get_buffer_pointer(1)->channel, 3);
}

// ── allocate_buffer=false constructor path ────────────────────────────────────

// When allocate_buffer=false the buffer struct members data and owned_by_base
// are set to nullptr/false rather than allocating aligned memory.
TEST(DoubleBufferAllocTest, AllocateBufferFalseDoesNotAllocate)
{
    attachLogger([](int, const char *) {});
    DoubleBuffer db(N_ANT, N_SAMP, N_POLS, N_BUFS, /*allocate_buffer=*/false);
    Buffer *b = db.get_buffer_pointer(0);
    ASSERT_NE(b, nullptr);
    EXPECT_EQ(b->data, nullptr);
    EXPECT_FALSE(b->owned_by_base);
    attachLogger(nullptr);
}

// ── write_data_single_channel: late-packet path ───────────────────────────────

// A packet with a timestamp earlier than the current buffer's ref_time is routed
// to the previous buffer (producer-1), not the current one.
TEST_F(DoubleBufferTest, SingleChannelWriteLatePacketGoesToPreviousBuffer)
{
    auto data = make_data(N_ANT * N_POLS);
    // First packet: sets ref_time = 5.0 in buffer[0].
    db->write_data_single_channel(0, N_ANT, 3, 0, 1, data.data(), 5.0);
    // Late packet: ts=3.0 < ref_time=5.0 → goes to (producer-1) = buffer[N_BUFS-1].
    db->write_data_single_channel(0, N_ANT, 3, 0, 1, data.data(), 3.0);
    EXPECT_EQ(db->get_buffer_pointer(N_BUFS - 1)->nof_packets, 1u);
}

// ── write_data_single_channel: double-advance marks first buffer ready ────────

// After two advance events the second advance's local_producer (= the first
// advance's buffer) has index != -1, so line 168 marks it ready.
TEST_F(DoubleBufferTest, SingleChannelWriteDoubleAdvanceMarksFirstBufferReady)
{
    auto data = make_data(N_ANT * N_POLS);
    // Advance 0: initialises buffer[0], ref_time=5.0.
    db->write_data_single_channel(0, N_ANT, 3, 0, 1, data.data(), 5.0);
    // Advance 1: ts=6.0 > ref_time+(N_SAMP-1)*1.08µs → buffer[0]→buffer[1].
    // local_producer == N_BUFS-1, index==-1 → ready NOT set yet.
    db->write_data_single_channel(0, N_ANT, 3, 0, 1, data.data(), 6.0);
    // Advance 2: ts=7.0 → buffer[1]→buffer[2].
    // local_producer == 0, index==0 (≠-1) → buffer[0].ready set to true.
    db->write_data_single_channel(0, N_ANT, 3, 0, 1, data.data(), 7.0);

    Buffer *buf = db->read_buffer();
    ASSERT_NE(buf, nullptr);
    EXPECT_TRUE(buf->ready);
    db->release_buffer();
}
