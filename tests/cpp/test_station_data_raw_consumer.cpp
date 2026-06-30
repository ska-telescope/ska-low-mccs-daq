// Consumer-path tests for StationRawData (StationDataRaw.cpp).
//
// Exercises StationRawData::packetFilter, processPacket (SPEAD parsing,
// capture_start_time filtering, channel range filtering, rollover handling,
// TAI time mode) and StationRawPersister (threaded callback delivery).
//
// The .cpp is #included directly so StationRawDoubleBuffer, StationRawPersister
// and StationRawData all compile in one TU alongside the stationdataraw() factory.
#include "StationDataRaw.cpp"  // NOLINT(bugprone-suspicious-include)

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <vector>

#include <gtest/gtest.h>

#include "DAQ.h"
#include "spead_test_util.h"

// ── Geometry ──────────────────────────────────────────────────────────────────

static constexpr uint16_t NOF_CHANS  = 2;
static constexpr uint32_t NOF_SAMP   = 8;
static constexpr uint32_t SAMP_PKT   = 4;
// payload = SAMP_PKT * nof_pols(2) * sizeof(uint16_t) = 16 bytes

// ── SPEAD item IDs ────────────────────────────────────────────────────────────

namespace {
constexpr int ID_HEAP_COUNTER = 0x0001;
constexpr int ID_PAYLOAD_LEN  = 0x0004;
constexpr int ID_SYNC_TIME    = 0x1027;
constexpr int ID_TIMESTAMP    = 0x1600;
constexpr int ID_FREQUENCY    = 0x1011;
constexpr int ID_ANT_CHAN     = 0x3000;
constexpr int ID_TILE_INFO    = 0x3001;
constexpr int ID_SCAN_ID      = 0x3010;
constexpr int ID_PAYLOAD_OFF  = 0x3300;
}  // namespace

// ── Callback capture ──────────────────────────────────────────────────────────

namespace {
struct RawCapture {
    std::atomic<int>        calls{0};
    std::mutex              mtx;
    std::condition_variable cv;
    unsigned                last_frequency{0};
    unsigned                last_nof_packets{0};
    unsigned                last_start_sample_index{0};
};
RawCapture g_raw_cap;

void raw_capturing_callback(void * /*data*/, double /*ts*/, void *ud)
{
    auto *meta = reinterpret_cast<RawStationMetadata *>(ud);
    std::lock_guard<std::mutex> lk(g_raw_cap.mtx);
    g_raw_cap.calls++;
    g_raw_cap.last_frequency          = meta->frequency;
    g_raw_cap.last_nof_packets        = meta->nof_packets;
    g_raw_cap.last_start_sample_index = meta->start_sample_index;
    g_raw_cap.cv.notify_all();
}
}  // namespace

// ── Packet builders ───────────────────────────────────────────────────────────

static std::vector<uint8_t> make_raw_payload_bytes()
{
    std::vector<uint8_t> p(SAMP_PKT * 2 * 2, 0);
    for (size_t i = 0; i < p.size(); i += 2) p[i] = 1;  // real=1, imag=0
    return p;
}

// Standard (non-TAI) 8-item raw station packet. nofitems=8 → tai_time=false.
static std::vector<uint8_t> make_raw_packet(
    uint32_t packet_counter,
    uint16_t logical_channel_id = 0,
    uint64_t sync_time          = 1000,
    uint64_t timestamp          = 5,
    uint16_t frequency_id       = 3,
    uint32_t payload_offset     = 0,
    uint8_t  substation_id      = 1,
    uint8_t  subarray_id        = 1,
    uint16_t station_id         = 7,
    uint16_t beam_id            = 5)
{
    const uint64_t heap      = (uint64_t(logical_channel_id) << 32) | packet_counter;
    const uint64_t ant_chan  = (uint64_t(beam_id) << 16) | frequency_id;
    const uint64_t tile_info = (uint64_t(substation_id) << 40) |
                               (uint64_t(subarray_id)   << 32) |
                               (uint64_t(station_id)    << 16);
    return SpeadPacket()
        .item(ID_HEAP_COUNTER, heap)
        .item(ID_PAYLOAD_LEN,  make_raw_payload_bytes().size())
        .item(ID_SYNC_TIME,    sync_time)
        .item(ID_TIMESTAMP,    timestamp)
        .item(ID_FREQUENCY,    781250ULL * frequency_id)
        .item(ID_ANT_CHAN,     ant_chan)
        .item(ID_TILE_INFO,    tile_info)
        .item(ID_PAYLOAD_OFF,  payload_offset)
        .payload(make_raw_payload_bytes())
        .build();
}

// TAI-time packet: exactly 6 items → nofitems=6 → tai_time=true.
static std::vector<uint8_t> make_raw_tai_packet(
    uint64_t tai_counter       = 12345678,
    uint16_t logical_channel_id = 0,
    uint16_t frequency_id      = 2,
    uint8_t  subarray_id       = 1,
    uint16_t station_id        = 9)
{
    const uint64_t ant_chan_tai = (uint64_t(logical_channel_id) << 32) |
                                  (uint64_t(0) << 16) | frequency_id;
    const uint64_t tile_info   = (uint64_t(subarray_id) << 32) |
                                  (uint64_t(station_id) << 16);
    return SpeadPacket()
        .item(ID_HEAP_COUNTER, tai_counter & 0xFFFFFFFFFFULL)
        .item(ID_PAYLOAD_LEN,  make_raw_payload_bytes().size())
        .item(ID_FREQUENCY,    781250ULL * frequency_id)
        .item(ID_ANT_CHAN,     ant_chan_tai)
        .item(ID_TILE_INFO,    tile_info)
        .item(ID_PAYLOAD_OFF,  0)
        .payload(make_raw_payload_bytes())
        .build();
}

// ── Testable subclass ─────────────────────────────────────────────────────────

class TestableStationRawData : public StationRawData {
public:
    using StationRawData::processPacket;
    using StationRawData::packetFilter;
    using StationRawData::cleanUp;
    bool push(std::vector<uint8_t> &pkt)
    {
        return ring_buffer->push(pkt.data(), pkt.size());
    }
};

// ── Fixture ───────────────────────────────────────────────────────────────────

class StationRawDataConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_raw_cap.calls = 0;
        attachLogger([](int, const char *) {});
        json config = {
            {"start_channel",     0},
            {"nof_channels",      NOF_CHANS},
            {"nof_samples",       NOF_SAMP},
            {"transpose_samples", 0},
            {"max_packet_size",   512},
            {"capture_start_time", 0},
        };
        initialized_ = consumer_.initialiseConsumer(config);
        ASSERT_TRUE(initialized_);
        consumer_.setCallback(raw_capturing_callback);
    }
    void TearDown() override
    {
        if (initialized_) consumer_.cleanUp();
        attachLogger(nullptr);
    }
    bool                   initialized_ = false;
    TestableStationRawData consumer_;
};

// ── packetFilter ──────────────────────────────────────────────────────────────

TEST_F(StationRawDataConsumerTest, PacketFilterAcceptsFrequencyItem)
{
    auto pkt = make_raw_packet(1);
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(StationRawDataConsumerTest, PacketFilterAcceptsScanIdItem)
{
    // 0x3010 (scan_id) also triggers the filter.
    auto pkt = SpeadPacket()
        .item(ID_SCAN_ID, 42)
        .item(ID_PAYLOAD_LEN, 16)
        .payload(make_raw_payload_bytes())
        .build();
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(StationRawDataConsumerTest, PacketFilterRejectsNonSpead)
{
    std::vector<uint8_t> junk(64, 0xFF);
    EXPECT_FALSE(consumer_.packetFilter(junk.data()));
}

TEST_F(StationRawDataConsumerTest, PacketFilterRejectsValidSpeadWithNoMatchingItem)
{
    auto pkt = SpeadPacket()
        .item(ID_HEAP_COUNTER, 1)
        .item(ID_PAYLOAD_LEN,  16)
        .payload(make_raw_payload_bytes())
        .build();
    EXPECT_FALSE(consumer_.packetFilter(pkt.data()));
}

// ── processPacket: timeout ────────────────────────────────────────────────────

TEST_F(StationRawDataConsumerTest, ProcessPacketTimesOutWhenRingEmpty)
{
    EXPECT_FALSE(consumer_.processPacket());
}

// ── processPacket: standard parsing ──────────────────────────────────────────

TEST_F(StationRawDataConsumerTest, ProcessPacketParsesPacketCounter)
{
    // Verify the function consumes the ring entry and returns true without crash.
    auto pkt = make_raw_packet(/*counter=*/5, /*logi_ch=*/0);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
}

// ── processPacket: channel range filtering ────────────────────────────────────

// A packet with logical_channel_id outside [start_channel, start_channel+nof_channels)
// is consumed (pull_ready called) but write_data is not invoked, so the ring drains.
TEST_F(StationRawDataConsumerTest, ProcessPacketFiltersOutOfRangeChannel)
{
    // Consumer start_channel=0, nof_channels=2 → accept 0 and 1 only.
    // Send channel=5 (out of range): consumed without write.
    auto pkt = make_raw_packet(1, /*logi_ch=*/5);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    // Ring is drained; no write happened.
    EXPECT_FALSE(consumer_.processPacket());
}

// ── processPacket: capture_start_time drop ────────────────────────────────────

// When capture_start_time > packet_end_time, the packet is dropped (pull_ready
// called without write_data).
TEST_F(StationRawDataConsumerTest, ProcessPacketDropsPacketBeforeCaptureStartTime)
{
    // Reinitialise with capture_start_time far in the future.
    consumer_.cleanUp();
    g_raw_cap.calls = 0;

    json config = {
        {"start_channel",      0},
        {"nof_channels",       NOF_CHANS},
        {"nof_samples",        NOF_SAMP},
        {"transpose_samples",  0},
        {"max_packet_size",    512},
        {"capture_start_time", 9999999},  // far future → drop all test packets
    };
    ASSERT_TRUE(consumer_.initialiseConsumer(config));
    consumer_.setCallback(raw_capturing_callback);

    // Packet with sync_time=1000, timestamp=5 → packet_end_time ≈ 1000.0000043 ≪ 9999999
    auto pkt = make_raw_packet(1);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());   // consumed but dropped
    EXPECT_FALSE(consumer_.processPacket());  // ring now empty
}

// ── processPacket: TAI time mode ─────────────────────────────────────────────

TEST_F(StationRawDataConsumerTest, ProcessPacketHandlesTaiTimeMode)
{
    // 6-item packet → tai_time=true.  Heap counter is 40-bit combined counter.
    auto pkt = make_raw_tai_packet(/*tai_counter=*/99999, /*logi_ch=*/0);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
}

// ── processPacket: rollover ───────────────────────────────────────────────────

// counter==0 && logi_ch==0 increments rollover_counter.
TEST_F(StationRawDataConsumerTest, ProcessPacketHandlesRolloverCounter)
{
    auto pkt = make_raw_packet(/*counter=*/0, /*logi_ch=*/0);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
}

// ── processPacket: frequency fallback ────────────────────────────────────────

// If the 0x1011 frequency item value is 0, frequency is derived from frequency_id.
TEST_F(StationRawDataConsumerTest, ProcessPacketHandlesFrequencyFallback)
{
    // Build a packet with explicit 0x1011 value = 0.
    const uint64_t heap      = (uint64_t(0) << 32) | 1;
    const uint64_t ant_chan  = (uint64_t(5) << 16) | 10;  // frequency_id=10
    const uint64_t tile_info = (uint64_t(1) << 40) | (uint64_t(1) << 32) | (uint64_t(7) << 16);
    auto pkt = SpeadPacket()
        .item(ID_HEAP_COUNTER, heap)
        .item(ID_PAYLOAD_LEN,  make_raw_payload_bytes().size())
        .item(ID_SYNC_TIME,    1000)
        .item(ID_TIMESTAMP,    5)
        .item(ID_FREQUENCY,    0)       // triggers filter but value=0 → fallback
        .item(ID_ANT_CHAN,     ant_chan)
        .item(ID_TILE_INFO,    tile_info)
        .item(ID_PAYLOAD_OFF,  0)
        .payload(make_raw_payload_bytes())
        .build();
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
}

// ── processPacket: scan_id item (no fallthrough in raw consumer) ─────────────

TEST_F(StationRawDataConsumerTest, ProcessPacketHandlesScanIdItem)
{
    // Build a packet that also carries 0x3010 (scan_id). Must not crash.
    const uint64_t heap      = 1;
    const uint64_t ant_chan  = (uint64_t(5) << 16) | 3;
    const uint64_t tile_info = (uint64_t(1) << 40) | (uint64_t(1) << 32) | (uint64_t(7) << 16);
    auto pkt = SpeadPacket()
        .item(ID_HEAP_COUNTER, heap)
        .item(ID_PAYLOAD_LEN,  make_raw_payload_bytes().size())
        .item(ID_SYNC_TIME,    1000)
        .item(ID_TIMESTAMP,    5)
        .item(ID_FREQUENCY,    781250ULL * 3)
        .item(ID_ANT_CHAN,     ant_chan)
        .item(ID_TILE_INFO,    tile_info)
        .item(ID_SCAN_ID,      0xABCD)
        .item(ID_PAYLOAD_OFF,  0)
        .payload(make_raw_payload_bytes())
        .build();
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
}

// ── processPacket: unknown SPEAD item ────────────────────────────────────────

TEST_F(StationRawDataConsumerTest, ProcessPacketHandlesUnknownSpeadItem)
{
    const uint64_t heap      = 1;
    const uint64_t ant_chan  = (uint64_t(5) << 16) | 3;
    const uint64_t tile_info = (uint64_t(1) << 40) | (uint64_t(1) << 32) | (uint64_t(7) << 16);
    auto pkt = SpeadPacket()
        .item(ID_HEAP_COUNTER, heap)
        .item(ID_PAYLOAD_LEN,  make_raw_payload_bytes().size())
        .item(ID_SYNC_TIME,    1000)
        .item(ID_TIMESTAMP,    5)
        .item(ID_FREQUENCY,    781250ULL * 3)
        .item(ID_ANT_CHAN,     ant_chan)
        .item(ID_TILE_INFO,    tile_info)
        .item(0xDEAD, 0xBEEF)  // unknown → default: LOG(WARN)
        .item(ID_PAYLOAD_OFF,  0)
        .payload(make_raw_payload_bytes())
        .build();
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
}

// ── cleanUp ───────────────────────────────────────────────────────────────────

TEST_F(StationRawDataConsumerTest, CleanUpStopsThreadWithoutCrash)
{
    consumer_.cleanUp();
    initialized_ = false;  // prevent double cleanUp in TearDown
}

// ── StationRawPersister callback ──────────────────────────────────────────────

// Drive 7 sequential packets through processPacket to mark buf[0] ready, then
// wait for the persister thread to fire the callback.
TEST_F(StationRawDataConsumerTest, PersisterFiresCallbackWhenBufferReady)
{
    for (uint32_t pc = 1; pc <= 7; ++pc) {
        auto pkt = make_raw_packet(pc, /*logi_ch=*/0);
        ASSERT_TRUE(consumer_.push(pkt));
        EXPECT_TRUE(consumer_.processPacket());
    }
    std::unique_lock<std::mutex> lk(g_raw_cap.mtx);
    bool fired = g_raw_cap.cv.wait_for(lk, std::chrono::milliseconds(500),
                                       [] { return g_raw_cap.calls >= 1; });
    EXPECT_TRUE(fired);
    EXPECT_GE(g_raw_cap.calls, 1);
}

// ── initialiseConsumer: missing keys ─────────────────────────────────────────

TEST(StationRawDataInitTest, InitialiseConsumerReturnsFalseWhenStartChannelMissing)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"nof_channels", 2}, {"nof_samples", 8},
        {"transpose_samples", 0}, {"max_packet_size", 512}, {"capture_start_time", 0},
    };
    EXPECT_FALSE(c.initialiseConsumer(config));
    attachLogger(nullptr);
}

TEST(StationRawDataInitTest, InitialiseConsumerReturnsFalseWhenNofChannelsMissing)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_samples", 8},
        {"transpose_samples", 0}, {"max_packet_size", 512}, {"capture_start_time", 0},
    };
    EXPECT_FALSE(c.initialiseConsumer(config));
    attachLogger(nullptr);
}

TEST(StationRawDataInitTest, InitialiseConsumerReturnsFalseWhenNofSamplesMissing)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_channels", 2},
        {"transpose_samples", 0}, {"max_packet_size", 512}, {"capture_start_time", 0},
    };
    EXPECT_FALSE(c.initialiseConsumer(config));
    attachLogger(nullptr);
}

TEST(StationRawDataInitTest, InitialiseConsumerReturnsFalseWhenTransposeMissing)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_channels", 2}, {"nof_samples", 8},
        {"max_packet_size", 512}, {"capture_start_time", 0},
    };
    EXPECT_FALSE(c.initialiseConsumer(config));
    attachLogger(nullptr);
}

TEST(StationRawDataInitTest, InitialiseConsumerReturnsFalseWhenMaxPacketSizeMissing)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_channels", 2}, {"nof_samples", 8},
        {"transpose_samples", 0}, {"capture_start_time", 0},
    };
    EXPECT_FALSE(c.initialiseConsumer(config));
    attachLogger(nullptr);
}

TEST(StationRawDataInitTest, InitialiseConsumerReturnsFalseWhenCaptureStartTimeMissing)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_channels", 2}, {"nof_samples", 8},
        {"transpose_samples", 0}, {"max_packet_size", 512},
    };
    EXPECT_FALSE(c.initialiseConsumer(config));
    attachLogger(nullptr);
}

// ── processPacket: additional parsing paths ───────────────────────────────────

// 0x2004 mode item is silently accepted (break only, no action).
TEST(StationRawDataExtraTest, ProcessPacketHandlesModeItem)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_channels", 2}, {"nof_samples", 8},
        {"transpose_samples", 0}, {"max_packet_size", 512}, {"capture_start_time", 0},
    };
    ASSERT_TRUE(c.initialiseConsumer(config));

    const uint64_t heap      = 1;
    const uint64_t ant_chan  = (uint64_t(5) << 16) | 3;
    const uint64_t tile_info = (uint64_t(1) << 40) | (uint64_t(1) << 32) | (uint64_t(7) << 16);
    auto pkt = SpeadPacket()
        .item(ID_HEAP_COUNTER, heap)
        .item(ID_PAYLOAD_LEN,  make_raw_payload_bytes().size())
        .item(ID_SYNC_TIME,    1000)
        .item(ID_TIMESTAMP,    5)
        .item(ID_FREQUENCY,    781250ULL * 3)
        .item(ID_ANT_CHAN,     ant_chan)
        .item(ID_TILE_INFO,    tile_info)
        .item(0x2004,          0)  // mode item → case 0x2004: break
        .item(ID_PAYLOAD_OFF,  0)
        .payload(make_raw_payload_bytes())
        .build();
    ASSERT_TRUE(c.push(pkt));
    EXPECT_TRUE(c.processPacket());
    c.cleanUp();
    attachLogger(nullptr);
}

// Timestamp rollover: timestamp==0 && logi_ch==0 increments timestamp_rollover.
TEST(StationRawDataExtraTest, ProcessPacketHandlesTimestampRolloverBothZero)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_channels", 2}, {"nof_samples", 8},
        {"transpose_samples", 0}, {"max_packet_size", 512}, {"capture_start_time", 0},
    };
    ASSERT_TRUE(c.initialiseConsumer(config));
    // timestamp=0, logi_ch=0 → rollover path (lines 238-239)
    auto pkt = make_raw_packet(/*counter=*/1, /*logi_ch=*/0,
                               /*sync_time=*/1000, /*timestamp=*/0);
    ASSERT_TRUE(c.push(pkt));
    EXPECT_TRUE(c.processPacket());
    c.cleanUp();
    attachLogger(nullptr);
}

// Timestamp rollover: timestamp==0 && logi_ch!=0 (channel-only path, line 242).
TEST(StationRawDataExtraTest, ProcessPacketHandlesTimestampRolloverChannelOnly)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_channels", 2}, {"nof_samples", 8},
        {"transpose_samples", 0}, {"max_packet_size", 512}, {"capture_start_time", 0},
    };
    ASSERT_TRUE(c.initialiseConsumer(config));
    // timestamp=0, logi_ch=1 → else-if path (line 242)
    auto pkt = make_raw_packet(/*counter=*/1, /*logi_ch=*/1,
                               /*sync_time=*/1000, /*timestamp=*/0);
    ASSERT_TRUE(c.push(pkt));
    EXPECT_TRUE(c.processPacket());
    c.cleanUp();
    attachLogger(nullptr);
}

// packet_counter rollover for logi_ch!=0 (line 284).
TEST(StationRawDataExtraTest, ProcessPacketHandlesPacketCounterRolloverChannelOnly)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_channels", 2}, {"nof_samples", 8},
        {"transpose_samples", 0}, {"max_packet_size", 512}, {"capture_start_time", 0},
    };
    ASSERT_TRUE(c.initialiseConsumer(config));
    // counter=0, logi_ch=1 → else-if (packet_counter == 0) branch (line 284)
    auto pkt = make_raw_packet(/*counter=*/0, /*logi_ch=*/1);
    ASSERT_TRUE(c.push(pkt));
    EXPECT_TRUE(c.processPacket());
    c.cleanUp();
    attachLogger(nullptr);
}

// Capture start time overlap: packet_time < capture_start_time <= packet_end_time.
// Uses sync_time=999 and timestamp=99999990 so packet straddles the 1000-second mark.
TEST(StationRawDataExtraTest, ProcessPacketHandlesCaptureStartTimeOverlap)
{
    attachLogger([](int, const char *) {});
    TestableStationRawData c;
    json config = {
        {"start_channel", 0}, {"nof_channels", 2}, {"nof_samples", 8},
        {"transpose_samples", 0}, {"max_packet_size", 512},
        {"capture_start_time", 1000},  // round(1000)=1000; packet_time=999.9999999 < 1000
    };
    ASSERT_TRUE(c.initialiseConsumer(config));
    // packet_time = 999 + 99999990*1e-8 = 999.9999999 < 1000 (capture_start_time)
    // packet_end_time ≈ 1000.0000043 >= 1000 → not dropped; enters offset calc (lines 267-275)
    auto pkt = make_raw_packet(/*counter=*/1, /*logi_ch=*/0,
                               /*sync_time=*/999, /*timestamp=*/99999990);
    ASSERT_TRUE(c.push(pkt));
    EXPECT_TRUE(c.processPacket());  // accepted, capture_start_time set to -1
    c.cleanUp();
    attachLogger(nullptr);
}

// ── Factory ───────────────────────────────────────────────────────────────────

TEST(StationRawDataFactoryTest, StationDataRawFactoryReturnsNonNull)
{
    DataConsumer *c = stationdataraw();
    ASSERT_NE(c, nullptr);
    delete c;
}
