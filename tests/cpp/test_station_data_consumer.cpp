// Consumer-path tests for StationData (StationData.cpp).
//
// Exercises StationData::packetFilter, processPacket (SPEAD parsing, metadata
// extraction, rollover handling, multi-subarray routing) and StationPersister
// (threaded callback delivery).
//
// The .cpp is #included directly so StationDoubleBuffer, StationPersister and
// StationData all compile in one TU alongside the stationdata() factory.
#include "StationData.cpp"  // NOLINT(bugprone-suspicious-include)

#include <gtest/gtest.h>
#include <atomic>
#include <condition_variable>
#include <mutex>
#include <vector>

#include "DAQ.h"
#include "spead_test_util.h"

// ── Geometry ──────────────────────────────────────────────────────────────────

static constexpr uint16_t NOF_CHANS   = 4;
static constexpr uint32_t NOF_SAMPLES = 8;
static constexpr uint32_t SAMP_PKT    = 4;   // samples encoded in each test packet
// payload_length = SAMP_PKT * nof_pols(=2) * sizeof(uint16_t) = 16 bytes

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
struct Capture {
    std::atomic<int>        calls{0};
    std::mutex              mtx;
    std::condition_variable cv;
};
Capture g_cap;

void capturing_callback(void * /*data*/, double /*ts*/, void * /*ud*/)
{
    {
        std::lock_guard<std::mutex> lk(g_cap.mtx);
        g_cap.calls++;
    }
    g_cap.cv.notify_all();
}
}  // namespace

// ── Packet builders ───────────────────────────────────────────────────────────

// Non-saturating raw payload: 16 bytes (4 samples × 2 pols × 2 bytes).
static std::vector<uint8_t> make_payload()
{
    std::vector<uint8_t> p(SAMP_PKT * 2 * 2, 0);
    for (size_t i = 0; i < p.size(); i += 2) p[i] = 1;  // real=1, imag=0
    return p;
}

// Standard (non-TAI) 8-item station packet.
// heap_counter[63:32]=logical_channel_id, heap_counter[31:0]=packet_counter.
// nofitems=8 → tai_time=false.
static std::vector<uint8_t> make_station_packet(
    uint32_t packet_counter,
    uint16_t logical_channel_id = 0,
    uint8_t  substation_id      = 2,
    uint8_t  subarray_id        = 1,
    uint16_t station_id         = 7,
    uint16_t beam_id            = 5,
    uint16_t frequency_id       = 3,
    uint32_t payload_offset     = 0)
{
    const uint64_t heap = (uint64_t(logical_channel_id) << 32) | packet_counter;
    const uint64_t ant_chan = (uint64_t(beam_id) << 16) | frequency_id;
    const uint64_t tile_info = (uint64_t(substation_id) << 40) |
                               (uint64_t(subarray_id)   << 32) |
                               (uint64_t(station_id)    << 16);
    return SpeadPacket()
        .item(ID_HEAP_COUNTER, heap)
        .item(ID_PAYLOAD_LEN,  make_payload().size())
        .item(ID_SYNC_TIME,    1000)
        .item(ID_TIMESTAMP,    5)
        .item(ID_FREQUENCY,    781250ULL * frequency_id)  // triggers packetFilter
        .item(ID_ANT_CHAN,     ant_chan)
        .item(ID_TILE_INFO,    tile_info)
        .item(ID_PAYLOAD_OFF,  payload_offset)
        .payload(make_payload())
        .build();
}

// TAI-time packet: exactly 6 items → nofitems=6 → tai_time=true.
// Heap counter holds the 40-bit combined counter/timestamp value.
// Antenna/channel item has logical_channel_id in bits 47:32.
static std::vector<uint8_t> make_tai_packet(
    uint64_t tai_counter       = 12345678,
    uint16_t logical_channel_id = 1,
    uint8_t  subarray_id       = 1,
    uint16_t station_id        = 9,
    uint16_t beam_id           = 2,
    uint16_t frequency_id      = 4)
{
    const uint64_t ant_chan_tai = (uint64_t(logical_channel_id) << 32) |
                                  (uint64_t(beam_id) << 16) | frequency_id;
    const uint64_t tile_info   = (uint64_t(subarray_id) << 32) |
                                  (uint64_t(station_id) << 16);
    return SpeadPacket()
        .item(ID_HEAP_COUNTER, tai_counter & 0xFFFFFFFFFFULL)
        .item(ID_PAYLOAD_LEN,  make_payload().size())
        .item(ID_ANT_CHAN,     ant_chan_tai)
        .item(ID_TILE_INFO,    tile_info)
        .item(ID_SCAN_ID,      0)  // scan_id=0; fallthrough sets payload_offset=0
        .item(ID_PAYLOAD_OFF,  0)
        .payload(make_payload())
        .build();
}

// ── Testable subclass ─────────────────────────────────────────────────────────

class TestableStationData : public StationData {
public:
    using StationData::processPacket;
    using StationData::packetFilter;
    using StationData::cleanUp;
    bool push(std::vector<uint8_t> &pkt) { return ring_buffer->push(pkt.data(), pkt.size()); }
};

// ── Fixture ───────────────────────────────────────────────────────────────────

class StationDataConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_cap.calls = 0;
        attachLogger([](int, const char *) {});
        json config = {
            {"nof_channels",    NOF_CHANS},
            {"nof_samples",     NOF_SAMPLES},
            {"max_packet_size", 512},
        };
        initialized_ = consumer_.initialiseConsumer(config);
        ASSERT_TRUE(initialized_);
        consumer_.setCallback(capturing_callback);
    }
    void TearDown() override
    {
        if (initialized_)
            consumer_.cleanUp();
        attachLogger(nullptr);
    }
    bool initialized_ = false;
    TestableStationData consumer_;
};

// ═══════════════════════════════════════════════════════════════════════════════
// packetFilter
// ═══════════════════════════════════════════════════════════════════════════════

TEST_F(StationDataConsumerTest, PacketFilterAcceptsFrequencyItem)
{
    auto pkt = make_station_packet(1);  // contains 0x1011
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(StationDataConsumerTest, PacketFilterAcceptsScanIdItem)
{
    // Build a packet whose only identifying item is 0x3010.
    auto payload = make_payload();
    auto pkt = SpeadPacket()
        .item(ID_HEAP_COUNTER, 1)
        .item(ID_PAYLOAD_LEN,  payload.size())
        .item(ID_SCAN_ID,      42)   // 0x3010 → accepted
        .item(ID_PAYLOAD_OFF,  0)
        .payload(std::move(payload))
        .build();
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(StationDataConsumerTest, PacketFilterRejectsNonSpead)
{
    std::vector<uint8_t> garbage(64, 0xFF);
    EXPECT_FALSE(consumer_.packetFilter(garbage.data()));
}

TEST_F(StationDataConsumerTest, PacketFilterRejectsValidSpeadWithNoMatchingItem)
{
    // A well-formed SPEAD packet that contains neither 0x1011 nor 0x3010.
    auto payload = make_payload();
    auto pkt = SpeadPacket()
        .item(ID_HEAP_COUNTER, 1)
        .item(ID_PAYLOAD_LEN,  payload.size())
        .item(ID_SYNC_TIME,    1000)
        .item(ID_TIMESTAMP,    5)
        .item(ID_PAYLOAD_OFF,  0)
        .payload(std::move(payload))
        .build();
    EXPECT_FALSE(consumer_.packetFilter(pkt.data()));
}

// ═══════════════════════════════════════════════════════════════════════════════
// processPacket: basic parsing
// ═══════════════════════════════════════════════════════════════════════════════

TEST_F(StationDataConsumerTest, ProcessPacketTimesOutWhenRingEmpty)
{
    EXPECT_FALSE(consumer_.processPacket());
}

TEST_F(StationDataConsumerTest, ProcessPacketParsesStandardMetadata)
{
    auto pkt = make_station_packet(
        /*pc=*/42, /*logi_ch=*/1, /*substation=*/2, /*subarray=*/1,
        /*station=*/7, /*beam=*/5, /*frequency_id=*/3);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());

    EXPECT_EQ(metadata.beam_id[0],              5u);
    EXPECT_EQ(metadata.frequency_id[0],         3u);
    EXPECT_EQ(metadata.logical_channel_id[0],   1u);
    EXPECT_EQ(metadata.station_id,              7u);
    // In single-subarray mode, subarray_id is forced to 1.
    EXPECT_EQ(metadata.subarray_id[0],          1u);
    EXPECT_EQ(metadata.payload_length,          make_payload().size());
    // packet_counter=42, rollover=0 → effective counter = 42.
    EXPECT_EQ(metadata.packet_count[0],        42u);
}

TEST_F(StationDataConsumerTest, ProcessPacketHandlesUnknownSpeadItem)
{
    // Add item 0x9999 → hits the default: case + LOG(WARN).
    auto payload = make_payload();
    auto pkt = SpeadPacket()
        .item(ID_HEAP_COUNTER, 1)
        .item(ID_PAYLOAD_LEN,  payload.size())
        .item(ID_SYNC_TIME,    1000)
        .item(ID_TIMESTAMP,    5)
        .item(ID_FREQUENCY,    0)
        .item(0x9999,          0xDEAD)  // unknown → default case
        .item(ID_ANT_CHAN,     0)
        .item(ID_TILE_INFO,    uint64_t(1) << 32)  // subarray_id=1
        .item(ID_PAYLOAD_OFF,  0)
        .payload(std::move(payload))
        .build();
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());  // no crash
}

// ═══════════════════════════════════════════════════════════════════════════════
// processPacket: TAI time mode
// ═══════════════════════════════════════════════════════════════════════════════

// A packet with exactly 6 items sets tai_time=true: sync_time becomes TAI_2000,
// timestamp_scale becomes 2.21184e-3, and the heap counter supplies both the
// packet counter and the timestamp.
TEST_F(StationDataConsumerTest, ProcessPacketHandlesTaiTimeMode)
{
    auto pkt = make_tai_packet(/*tai_counter=*/5000, /*logi_ch=*/1,
                               /*subarray=*/1, /*station=*/9, /*beam=*/2, /*freq_id=*/4);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());

    // With tai_time: logical_channel_id is in ant_chan item bits[47:32].
    EXPECT_EQ(metadata.logical_channel_id[0], 1u);
    EXPECT_EQ(metadata.beam_id[0],            2u);
    EXPECT_EQ(metadata.frequency_id[0],       4u);
    EXPECT_EQ(metadata.station_id,            9u);
}

// ═══════════════════════════════════════════════════════════════════════════════
// processPacket: multi-subarray routing
// ═══════════════════════════════════════════════════════════════════════════════

// In multi-subarray mode, a packet from subarray_id=0 or subarray_id > nof_subarrays
// is dropped (pull_ready called, processPacket returns true but writes nothing).
TEST(StationDataMultiSubarrayTest, ProcessPacketDropsOutOfRangeSubarray)
{
    attachLogger([](int, const char *) {});
    g_cap.calls = 0;

    TestableStationData consumer;
    json config = {
        {"nof_channels",    NOF_CHANS},
        {"nof_samples",     NOF_SAMPLES},
        {"nof_subarrays",   2},
        {"max_packet_size", 512},
    };
    ASSERT_TRUE(consumer.initialiseConsumer(config));
    consumer.setCallback(capturing_callback);

    // subarray_id=3 is out of range [1..2] — packet should be dropped.
    auto pkt = make_station_packet(1, 0, /*substation=*/0, /*subarray=*/3, /*station=*/1);
    uint64_t before = metadata.packet_count[0];
    ASSERT_TRUE(consumer.push(pkt));
    EXPECT_TRUE(consumer.processPacket());  // returns true (packet consumed)
    // metadata.packet_count[0] must be unchanged: processPacket returned early.
    EXPECT_EQ(metadata.packet_count[0], before);

    consumer.cleanUp();
    attachLogger(nullptr);
}

TEST(StationDataMultiSubarrayTest, ProcessPacketAcceptsValidSubarray)
{
    attachLogger([](int, const char *) {});
    g_cap.calls = 0;

    TestableStationData consumer;
    json config = {
        {"nof_channels",    NOF_CHANS},
        {"nof_samples",     NOF_SAMPLES},
        {"nof_subarrays",   2},
        {"max_packet_size", 512},
    };
    ASSERT_TRUE(consumer.initialiseConsumer(config));
    consumer.setCallback(capturing_callback);

    // subarray_id=2 is valid; compound_channel = (2-1)*4 + 0 = 4.
    auto pkt = make_station_packet(1, 0, /*substation=*/0, /*subarray=*/2, /*station=*/1);
    ASSERT_TRUE(consumer.push(pkt));
    EXPECT_TRUE(consumer.processPacket());
    EXPECT_EQ(metadata.subarray_id[0], 2u);

    consumer.cleanUp();
    attachLogger(nullptr);
}

// ═══════════════════════════════════════════════════════════════════════════════
// processPacket: rollover counters
// ═══════════════════════════════════════════════════════════════════════════════

// When packet_counter==0 AND logical_channel_id==0 (both fields zero), a
// counter rollover is detected: rollover_counter is incremented and the
// effective counter is rollover_counter << 32.
TEST_F(StationDataConsumerTest, ProcessPacketHandlesCounterRolloverBothZero)
{
    // First call: rollover fires (counter=0, logi_ch=0).
    // rollover_counter becomes 1 → effective packet_counter = 1<<32.
    auto pkt = make_station_packet(/*pc=*/0, /*logi_ch=*/0);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    EXPECT_EQ(metadata.packet_count[0], uint64_t(1) << 32);
}

// When packet_counter==0 but logical_channel_id!=0, a per-channel rollover is
// applied: effective counter = (rollover_counter + 1) << 32.
TEST_F(StationDataConsumerTest, ProcessPacketHandlesCounterRolloverChannelOnly)
{
    // rollover_counter is 0 on first packet from this subarray.
    // counter=0, logi_ch=1 → effective = (0+1)<<32 = 2^32.
    auto pkt = make_station_packet(/*pc=*/0, /*logi_ch=*/1);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    EXPECT_EQ(metadata.packet_count[0], uint64_t(1) << 32);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Factory function, cleanUp, and initialise failure
// ═══════════════════════════════════════════════════════════════════════════════

TEST(StationDataFactoryTest, StationDataFactoryReturnsNonNull)
{
    DataConsumer *c = stationdata();
    ASSERT_NE(c, nullptr);
    delete c;
}

// cleanUp stops the persister thread and frees the double buffer.
TEST_F(StationDataConsumerTest, CleanUpStopsThreadWithoutCrash)
{
    consumer_.cleanUp();
    initialized_ = false;  // prevent double-clean in TearDown
}

// Missing "nof_channels" triggers the error path in initialiseConsumer.
TEST(StationDataInitTest, InitialiseConsumerReturnsFalseWhenKeyMissing)
{
    attachLogger([](int, const char *) {});
    TestableStationData consumer;
    json config = {
        // "nof_channels" intentionally omitted
        {"nof_samples",     8},
        {"max_packet_size", 512},
    };
    EXPECT_FALSE(consumer.initialiseConsumer(config));
    attachLogger(nullptr);
}

// ═══════════════════════════════════════════════════════════════════════════════
// StationPersister: threaded callback delivery
// ═══════════════════════════════════════════════════════════════════════════════

// Drive 7 packets through processPacket to mark buf[0] ready, then wait for the
// StationPersister thread to consume it and fire the callback.
// Counters 1..7 with SAMP_PKT=4 samples each produce N_SAMP/SAMP_PKT=2 advances
// per buffer, requiring 3 total advances before buf[0] is marked ready.
TEST_F(StationDataConsumerTest, PersisterFiresCallbackWhenBufferReady)
{
    // Push and process 7 packets (counters 1..7). Packet at counter 7 triggers
    // the advance that marks buf[0] ready; the persister thread then calls the
    // callback.
    for (uint32_t pc = 1; pc <= 7; ++pc) {
        auto pkt = make_station_packet(pc);
        ASSERT_TRUE(consumer_.push(pkt));
        EXPECT_TRUE(consumer_.processPacket());
    }

    // Wait up to 1 second for the persister thread to consume buf[0].
    std::unique_lock<std::mutex> lk(g_cap.mtx);
    bool fired = g_cap.cv.wait_for(lk, std::chrono::seconds(1),
                                   [&] { return g_cap.calls.load() >= 1; });
    EXPECT_TRUE(fired) << "StationPersister did not fire callback within 1s";
    EXPECT_GE(g_cap.calls.load(), 1);
}
