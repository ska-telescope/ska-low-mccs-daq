// Consumer-path tests for the three channelised DAQ modes (ChannelisedData.cpp).
//
// Exercises ChannelisedData (mode 0x4), ContinuousChannelisedData (modes 0x5/0x7)
// and IntegratedChannelisedData (mode 0x6) by pushing crafted SPEAD packets into
// the consumer ring buffer and asserting on parsed metadata and callback behaviour.
//
// IMPORTANT — mode item placement: all three consumers use
//   uint64_t mode = SPEAD_ITEM_ADDR(SPEAD_ITEM(udp_packet, 5));
// which reads item-pointer slot 5 unconditionally (not a loop scan).  SpeadPacket
// places item k at slot k+1, so the mode must be the 5th item added (k=4, slot 5).
// The packet layout below respects this ordering:
//   [slot 1] 0x0001  heap counter
//   [slot 2] 0x0004  payload length
//   [slot 3] 0x1027  sync time
//   [slot 4] 0x1600  timestamp
//   [slot 5] 0x2004  mode  ← packetFilter reads this slot directly
//   [slot 6] 0x2002  antenna/channel info
//   [slot 7] 0x2001  tile info
//   [slot 8] 0x3300  payload offset
//
// The .cpp is #included directly so all three consumer classes and their factories
// compile in one TU (no duplicate factory symbols).
#include "ChannelisedData.cpp"  // NOLINT(bugprone-suspicious-include)

#include <gtest/gtest.h>
#include <vector>

#include "DAQ.h"
#include "spead_test_util.h"

// ── SPEAD item IDs ────────────────────────────────────────────────────────────

namespace {
constexpr int ID_HEAP_COUNTER = 0x0001;
constexpr int ID_PAYLOAD_LEN  = 0x0004;
constexpr int ID_SYNC_TIME    = 0x1027;
constexpr int ID_TIMESTAMP    = 0x1600;
constexpr int ID_MODE         = 0x2004;
// 0x2002: bits[39:24]=start_channel, bits[23:16]=nof_included_channels,
//         bits[15:8]=start_antenna, bits[7:0]=nof_included_antennas
constexpr int ID_ANT_CHAN     = 0x2002;
// 0x2001: bits[39:32]=tile_id, bits[31:16]=station_id, bits[7:0]=fpga_id
constexpr int ID_TILE_INFO    = 0x2001;
constexpr int ID_PAYLOAD_OFF  = 0x3300;
}  // namespace

// ── Packet builder ────────────────────────────────────────────────────────────

// Construct a channelised-data SPEAD packet. The mode item sits at slot 5 so that
// SPEAD_ITEM(udp_packet, 5) returns it (required by all three packetFilter impls).
static std::vector<uint8_t> build_chan_packet(uint32_t packet_counter,
                                               uint16_t start_channel,
                                               uint8_t  nof_included_channels,
                                               uint8_t  start_antenna,
                                               uint8_t  nof_included_antennas,
                                               uint8_t  tile_id,
                                               uint16_t station_id,
                                               uint8_t  fpga_id,
                                               std::vector<uint8_t> payload,
                                               uint64_t mode)
{
    const uint64_t ant_chan = (uint64_t(start_channel) << 24) |
                              (uint64_t(nof_included_channels) << 16) |
                              (uint64_t(start_antenna) << 8) |
                              uint64_t(nof_included_antennas);
    const uint64_t tile_info = (uint64_t(tile_id) << 32) |
                               (uint64_t(station_id) << 16) |
                               uint64_t(fpga_id);
    return SpeadPacket()
        .item(ID_HEAP_COUNTER, packet_counter)  // slot 1
        .item(ID_PAYLOAD_LEN,  payload.size())  // slot 2
        .item(ID_SYNC_TIME,    1000)             // slot 3
        .item(ID_TIMESTAMP,    5)                // slot 4
        .item(ID_MODE,         mode)             // slot 5 — read by packetFilter
        .item(ID_ANT_CHAN,     ant_chan)          // slot 6
        .item(ID_TILE_INFO,    tile_info)        // slot 7
        .item(ID_PAYLOAD_OFF,  0)                // slot 8
        .payload(std::move(payload))
        .build();
}

static std::vector<uint8_t> make_chan_payload(unsigned nof_antennas, unsigned nof_pols,
                                              unsigned nof_channels, unsigned samples = 1)
{
    size_t nbytes = nof_antennas * nof_pols * nof_channels * samples * sizeof(uint16_t);
    std::vector<uint8_t> p(nbytes);
    for (size_t i = 0; i < nbytes; ++i)
        p[i] = static_cast<uint8_t>(i + 1);
    return p;
}

// ── Testable subclasses ───────────────────────────────────────────────────────

class TestableChannel : public ChannelisedData {
public:
    using ChannelisedData::processPacket;
    using ChannelisedData::onStreamEnd;
    using ChannelisedData::packetFilter;
    using ChannelisedData::cleanUp;
    bool push(std::vector<uint8_t> &pkt) { return ring_buffer->push(pkt.data(), pkt.size()); }
};

class TestableContinuous : public ContinuousChannelisedData {
public:
    using ContinuousChannelisedData::processPacket;
    using ContinuousChannelisedData::packetFilter;
    using ContinuousChannelisedData::cleanUp;
    bool push(std::vector<uint8_t> &pkt) { return ring_buffer->push(pkt.data(), pkt.size()); }
};

class TestableIntegrated : public IntegratedChannelisedData {
public:
    using IntegratedChannelisedData::processPacket;
    using IntegratedChannelisedData::packetFilter;
    using IntegratedChannelisedData::cleanUp;
    bool push(std::vector<uint8_t> &pkt) { return ring_buffer->push(pkt.data(), pkt.size()); }
};

// ═══════════════════════════════════════════════════════════════════════════════
// ChannelisedData (burst channel, mode 0x4)
// ═══════════════════════════════════════════════════════════════════════════════

// Geometry: 1 tile, 2 antennas, 4 channels, 2 samples, 1 pol.
// persist_container fires when a tile accumulates >= nof_tiles * nof_pols * 2 = 2 packets.
static constexpr uint16_t BC_NOF_TILES   = 1;
static constexpr uint16_t BC_NOF_ANT     = 2;
static constexpr uint16_t BC_NOF_CHANS   = 4;
static constexpr uint32_t BC_NOF_SAMPLES = 2;
static constexpr uint8_t  BC_NOF_POLS    = 1;
static constexpr uint8_t  BC_NOF_INC_CH  = 1;  // channels per packet
static constexpr unsigned BC_PERSIST_THRESHOLD = BC_NOF_TILES * BC_NOF_POLS * 2;

namespace {
struct BurstChanCapture {
    int      calls = 0;
    uint64_t nof_packets = 0;
    uint8_t  tile_id = 0;
    uint16_t station_id = 0;
    uint32_t packet_counter0 = 0;
    uint8_t  fpga_id0 = 0;
    uint16_t nof_included_channels = 0;
    uint16_t nof_included_antennas = 0;
};
BurstChanCapture g_burst_chan;

void burst_chan_callback(void * /*data*/, double /*ts*/, void *ud)
{
    const auto *m = static_cast<const ChannelMetadata *>(ud);
    g_burst_chan.calls++;
    g_burst_chan.nof_packets          = m->nof_packets;
    g_burst_chan.tile_id              = m->tile_id;
    g_burst_chan.station_id           = m->station_id;
    g_burst_chan.packet_counter0      = m->packet_counter[0];
    g_burst_chan.fpga_id0             = m->fpga_id[0];
    g_burst_chan.nof_included_channels  = m->nof_included_channels;
    g_burst_chan.nof_included_antennas  = m->nof_included_antennas;
}
}  // namespace

class ChannelisedDataConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_burst_chan = BurstChanCapture{};
        attachLogger([](int, const char *) {});
        json config = {
            {"nof_tiles",    BC_NOF_TILES},
            {"nof_antennas", BC_NOF_ANT},
            {"nof_channels", BC_NOF_CHANS},
            {"nof_samples",  BC_NOF_SAMPLES},
            {"nof_pols",     BC_NOF_POLS},
            {"max_packet_size", 512},
        };
        ASSERT_TRUE(consumer_.initialiseConsumer(config));
        consumer_.setCallback(burst_chan_callback);
    }
    void TearDown() override { attachLogger(nullptr); }

    // Build a burst-channel packet for tile_id=0, station_id=7, fpga=0, one channel.
    std::vector<uint8_t> make_pkt(uint32_t pc)
    {
        // 1 sample * 2 antennas * 1 pol * 1 channel * 2 bytes = 4 bytes payload.
        auto payload = make_chan_payload(BC_NOF_ANT, BC_NOF_POLS, BC_NOF_INC_CH);
        return build_chan_packet(pc,
                                  /*start_ch=*/0, /*nof_inc_ch=*/BC_NOF_INC_CH,
                                  /*start_ant=*/0, /*nof_inc_ant=*/BC_NOF_ANT,
                                  /*tile=*/0, /*station=*/7, /*fpga=*/0,
                                  std::move(payload), /*mode=*/0x4);
    }

    TestableChannel consumer_;
};

TEST_F(ChannelisedDataConsumerTest, PacketFilterAcceptsBurstChannelMode)
{
    auto pkt = make_pkt(0);
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(ChannelisedDataConsumerTest, PacketFilterRejectsWrongMode)
{
    auto payload = make_chan_payload(BC_NOF_ANT, BC_NOF_POLS, BC_NOF_INC_CH);
    auto pkt = build_chan_packet(0, 0, BC_NOF_INC_CH, 0, BC_NOF_ANT,
                                  0, 7, 0, std::move(payload), /*mode=*/0x9);
    EXPECT_FALSE(consumer_.packetFilter(pkt.data()));
}

TEST_F(ChannelisedDataConsumerTest, PacketFilterRejectsNonSpead)
{
    std::vector<uint8_t> garbage(64, 0xFF);
    EXPECT_FALSE(consumer_.packetFilter(garbage.data()));
}

TEST_F(ChannelisedDataConsumerTest, ProcessPacketTimesOutWhenRingEmpty)
{
    EXPECT_FALSE(consumer_.processPacket());
    EXPECT_EQ(g_burst_chan.calls, 0);
}

TEST_F(ChannelisedDataConsumerTest, ProcessPacketParsesMetadata)
{
    // Accumulate BC_PERSIST_THRESHOLD=2 packets so persist_container fires the callback.
    for (unsigned i = 0; i < BC_PERSIST_THRESHOLD; ++i) {
        auto pkt = make_pkt(i);
        ASSERT_TRUE(consumer_.push(pkt));
        EXPECT_TRUE(consumer_.processPacket());
    }
    consumer_.onStreamEnd();

    ASSERT_EQ(g_burst_chan.calls, 1);
    EXPECT_EQ(g_burst_chan.nof_packets, BC_PERSIST_THRESHOLD);
    EXPECT_EQ(g_burst_chan.tile_id, 0u);
    EXPECT_EQ(g_burst_chan.station_id, 7u);
    EXPECT_EQ(g_burst_chan.packet_counter0, 0u);
    EXPECT_EQ(g_burst_chan.fpga_id0, 0u);
    EXPECT_EQ(g_burst_chan.nof_included_channels, BC_NOF_INC_CH);
    EXPECT_EQ(g_burst_chan.nof_included_antennas, BC_NOF_ANT);
}

TEST_F(ChannelisedDataConsumerTest, OnStreamEndBelowThresholdDoesNotFireCallback)
{
    // Only one packet — below the persist threshold.
    auto pkt = make_pkt(0);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    consumer_.onStreamEnd();
    EXPECT_EQ(g_burst_chan.calls, 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
// ContinuousChannelisedData (modes 0x5 and 0x7)
// ═══════════════════════════════════════════════════════════════════════════════

namespace {
bool g_cont_callback_fired = false;
void cont_callback(void * /*data*/, double /*ts*/, void * /*ud*/)
{
    g_cont_callback_fired = true;
}
}  // namespace

class ContinuousChannelisedDataConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_cont_callback_fired = false;
        attachLogger([](int, const char *) {});
        json config = {
            {"nof_tiles",       1},
            {"nof_antennas",    2},
            {"nof_channels",    4},
            {"nof_samples",     4},
            {"nof_pols",        1},
            {"bitwidth",        16},
            {"sampling_time",   1.08e-6},
            {"nof_buffer_skips",0},
            {"start_time",      1000.0},
            {"max_packet_size", 512},
        };
        ASSERT_TRUE(consumer_.initialiseConsumer(config));
        consumer_.setCallback(cont_callback);
    }
    void TearDown() override { attachLogger(nullptr); }

    // 1 sample, 2 antennas, 1 pol, 1 channel.
    std::vector<uint8_t> make_pkt(uint32_t pc, uint64_t mode = 0x5)
    {
        auto payload = make_chan_payload(2, 1, 1);
        return build_chan_packet(pc, 0, 1, 0, 2, 0, 5, 0, std::move(payload), mode);
    }

    TestableContinuous consumer_;
};

TEST_F(ContinuousChannelisedDataConsumerTest, PacketFilterAcceptsMode5)
{
    auto pkt = make_pkt(0, 0x5);
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(ContinuousChannelisedDataConsumerTest, PacketFilterAcceptsMode7)
{
    auto pkt = make_pkt(0, 0x7);
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(ContinuousChannelisedDataConsumerTest, PacketFilterRejectsMode4)
{
    auto pkt = make_pkt(0, 0x4);
    EXPECT_FALSE(consumer_.packetFilter(pkt.data()));
}

TEST_F(ContinuousChannelisedDataConsumerTest, PacketFilterRejectsNonSpead)
{
    std::vector<uint8_t> garbage(64, 0xFF);
    EXPECT_FALSE(consumer_.packetFilter(garbage.data()));
}

TEST_F(ContinuousChannelisedDataConsumerTest, ProcessPacketTimesOutWhenRingEmpty)
{
    EXPECT_FALSE(consumer_.processPacket());
}

TEST_F(ContinuousChannelisedDataConsumerTest, ProcessPacketReturnsTrueOnValidPacket)
{
    auto pkt = make_pkt(0);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    // The first packet initialises reference_time_ns but does not trigger a persist
    // (the container stays below its flush threshold).
    EXPECT_FALSE(g_cont_callback_fired);
}

// ═══════════════════════════════════════════════════════════════════════════════
// IntegratedChannelisedData (mode 0x6)
// ═══════════════════════════════════════════════════════════════════════════════

// Geometry chosen so total_packets = (nof_ant/inc_ant) * (nof_ch/inc_ch) * nof_pols * nof_tiles
//                                  = (4/2) * (4/4) * 1 * 1 = 2
// and the persist threshold = nof_tiles * nof_pols * 2 = 2.
// Two packets therefore satisfy both conditions, firing the callback.
static constexpr uint16_t IC_NOF_TILES   = 1;
static constexpr uint16_t IC_NOF_ANT     = 4;
static constexpr uint16_t IC_NOF_CHANS   = 4;
static constexpr uint8_t  IC_NOF_POLS    = 1;
// Packet parameters: 2 antennas per packet, 4 channels (derived from payload length).
static constexpr uint8_t  IC_INC_ANT     = 2;
// payload_length = IC_INC_ANT * IC_NOF_POLS * 1(sample) * IC_NOF_CHANS * sizeof(uint16_t) = 16
static constexpr size_t   IC_PAYLOAD_BYTES = IC_INC_ANT * IC_NOF_POLS * IC_NOF_CHANS * sizeof(uint16_t);

namespace {
struct IntegChanCapture {
    int      calls = 0;
    uint64_t nof_packets = 0;
    uint8_t  tile_id = 0;
    uint16_t station_id = 0;
    uint32_t packet_counter0 = 0;
};
IntegChanCapture g_integ_chan;

void integ_chan_callback(void * /*data*/, double /*ts*/, void *ud)
{
    const auto *m = static_cast<const ChannelMetadata *>(ud);
    g_integ_chan.calls++;
    g_integ_chan.nof_packets     = m->nof_packets;
    g_integ_chan.tile_id         = m->tile_id;
    g_integ_chan.station_id      = m->station_id;
    g_integ_chan.packet_counter0 = m->packet_counter[0];
}
}  // namespace

class IntegratedChannelisedDataConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_integ_chan = IntegChanCapture{};
        attachLogger([](int, const char *) {});
        json config = {
            {"nof_tiles",    IC_NOF_TILES},
            {"nof_antennas", IC_NOF_ANT},
            {"nof_channels", IC_NOF_CHANS},
            {"nof_pols",     IC_NOF_POLS},
            {"bitwidth",     16},
            {"sampling_time",1.08e-6},
            {"max_packet_size", 512},
        };
        ASSERT_TRUE(consumer_.initialiseConsumer(config));
        consumer_.setCallback(integ_chan_callback);
    }
    void TearDown() override { attachLogger(nullptr); }

    // Build a packet for tile_id=0, station_id=9, fpga_id=0.
    // nof_included_channels is derived from payload_length inside processPacket,
    // so the value encoded in ID_ANT_CHAN is irrelevant; nof_included_antennas must
    // match the payload size.
    std::vector<uint8_t> make_pkt(uint32_t pc, uint8_t start_ant)
    {
        std::vector<uint8_t> payload(IC_PAYLOAD_BYTES);
        for (size_t i = 0; i < IC_PAYLOAD_BYTES; ++i)
            payload[i] = static_cast<uint8_t>(i + 1);
        return build_chan_packet(pc,
                                  /*start_ch=*/0, /*nof_inc_ch=*/0,
                                  /*start_ant=*/start_ant, /*nof_inc_ant=*/IC_INC_ANT,
                                  /*tile=*/0, /*station=*/9, /*fpga=*/0,
                                  std::move(payload), /*mode=*/0x6);
    }

    TestableIntegrated consumer_;
};

TEST_F(IntegratedChannelisedDataConsumerTest, PacketFilterAcceptsMode6)
{
    auto pkt = make_pkt(0, 0);
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(IntegratedChannelisedDataConsumerTest, PacketFilterRejectsMode4)
{
    std::vector<uint8_t> payload(IC_PAYLOAD_BYTES);
    auto pkt = build_chan_packet(0, 0, 0, 0, IC_INC_ANT, 0, 9, 0,
                                  std::move(payload), /*mode=*/0x4);
    EXPECT_FALSE(consumer_.packetFilter(pkt.data()));
}

TEST_F(IntegratedChannelisedDataConsumerTest, PacketFilterRejectsNonSpead)
{
    std::vector<uint8_t> garbage(64, 0xFF);
    EXPECT_FALSE(consumer_.packetFilter(garbage.data()));
}

TEST_F(IntegratedChannelisedDataConsumerTest, ProcessPacketTimesOutWhenRingEmpty)
{
    EXPECT_FALSE(consumer_.processPacket());
    EXPECT_EQ(g_integ_chan.calls, 0);
}

TEST_F(IntegratedChannelisedDataConsumerTest, ProcessPacketFiresCallbackAfterTotalPackets)
{
    // Packet 0 (start_ant=0): num_packets→1, total=2, no flush yet.
    auto p0 = make_pkt(0, /*start_ant=*/0);
    ASSERT_TRUE(consumer_.push(p0));
    EXPECT_TRUE(consumer_.processPacket());
    EXPECT_EQ(g_integ_chan.calls, 0);

    // Packet 1 (start_ant=2): num_packets→2 == total=2 → persist_container →
    // metadata[tile].nof_packets=2 >= threshold=2 → callback fires.
    auto p1 = make_pkt(1, /*start_ant=*/2);
    ASSERT_TRUE(consumer_.push(p1));
    EXPECT_TRUE(consumer_.processPacket());

    ASSERT_EQ(g_integ_chan.calls, 1);
    EXPECT_EQ(g_integ_chan.nof_packets, 2u);
    EXPECT_EQ(g_integ_chan.tile_id, 0u);
    EXPECT_EQ(g_integ_chan.station_id, 9u);
    EXPECT_EQ(g_integ_chan.packet_counter0, 0u);
}

TEST_F(IntegratedChannelisedDataConsumerTest, NewIntegrationAfterFlush)
{
    // Send a full integration (2 packets) to flush, then one more to start the next.
    auto p0 = make_pkt(0, 0);
    auto p1 = make_pkt(1, 2);
    ASSERT_TRUE(consumer_.push(p0)); consumer_.processPacket();
    ASSERT_TRUE(consumer_.push(p1)); consumer_.processPacket();
    ASSERT_EQ(g_integ_chan.calls, 1);

    // After the flush, num_packets resets to 0.  A new packet should not trigger
    // another callback by itself.
    auto p2 = make_pkt(2, 0);
    ASSERT_TRUE(consumer_.push(p2));
    EXPECT_TRUE(consumer_.processPacket());
    EXPECT_EQ(g_integ_chan.calls, 1);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Factory functions (ChannelisedData.h lines 412-414)
//
// burstchannel / continuouschannel / integratedchannel are defined inline in
// the header and not otherwise called from any test.  Constructing and
// immediately destroying each object is sufficient to record coverage for those
// three lines.  ~DataConsumer() is empty (ring_buffer deletion is commented out)
// so this is safe without calling initialiseConsumer first.
// ═══════════════════════════════════════════════════════════════════════════════

TEST(ChannelisedDataFactoryTest, BurstChannelFactoryReturnsNonNull)
{
    DataConsumer *c = burstchannel();
    ASSERT_NE(c, nullptr);
    delete c;
}

TEST(ChannelisedDataFactoryTest, ContinuousChannelFactoryReturnsNonNull)
{
    DataConsumer *c = continuouschannel();
    ASSERT_NE(c, nullptr);
    delete c;
}

TEST(ChannelisedDataFactoryTest, IntegratedChannelFactoryReturnsNonNull)
{
    DataConsumer *c = integratedchannel();
    ASSERT_NE(c, nullptr);
    delete c;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Additional burst-channel coverage
// ═══════════════════════════════════════════════════════════════════════════════

TEST_F(ChannelisedDataConsumerTest, CleanUpFreesContainer)
{
    consumer_.cleanUp();
}

// A packet with an extra unknown item ID exercises the default: branch of the
// processPacket item-loop, covering the LOG(INFO, ...) line.
TEST_F(ChannelisedDataConsumerTest, ProcessPacketLogsUnknownItem)
{
    auto payload = make_chan_payload(BC_NOF_ANT, BC_NOF_POLS, BC_NOF_INC_CH);
    const uint64_t ant_chan = (0ULL << 24) | (uint64_t(BC_NOF_INC_CH) << 16) |
                              (0ULL << 8)  | uint64_t(BC_NOF_ANT);
    const uint64_t tile_info = (0ULL << 32) | (uint64_t(7) << 16) | 0ULL;
    auto pkt = SpeadPacket()
        .item(ID_HEAP_COUNTER, 0)
        .item(ID_PAYLOAD_LEN, payload.size())
        .item(ID_SYNC_TIME,   1000)
        .item(ID_TIMESTAMP,   5)
        .item(ID_MODE,        0x4)
        .item(ID_ANT_CHAN,    ant_chan)
        .item(ID_TILE_INFO,   tile_info)
        .item(ID_PAYLOAD_OFF, 0)
        .item(0x9999,         0)  // unknown item ID → hits default: case
        .payload(std::move(payload))
        .build();
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
}

// ═══════════════════════════════════════════════════════════════════════════════
// Additional continuous-channel (16-bit) coverage
// ═══════════════════════════════════════════════════════════════════════════════

// Packet builder with configurable sync_time and timestamp for continuous tests.
static std::vector<uint8_t> make_cont_pkt_ts(uint32_t pc, uint64_t sync, uint64_t ts)
{
    auto payload = make_chan_payload(2, 1, 1);
    const uint64_t ant_chan = (0ULL << 24) | (1ULL << 16) | (0ULL << 8) | 2ULL;
    return SpeadPacket()
        .item(ID_HEAP_COUNTER, pc)
        .item(ID_PAYLOAD_LEN, payload.size())
        .item(ID_SYNC_TIME, sync)
        .item(ID_TIMESTAMP, ts)
        .item(ID_MODE, 0x5)
        .item(ID_ANT_CHAN, ant_chan)
        .item(ID_TILE_INFO, 0)
        .item(ID_PAYLOAD_OFF, 0)
        .payload(std::move(payload))
        .build();
}

TEST_F(ContinuousChannelisedDataConsumerTest, CleanUpFreesContainers)
{
    consumer_.cleanUp();
}

// Sending a second packet with counter=0 exercises the rollover branch
// (packet_counter_information[idx][1]++; and the updated counter calculation).
TEST_F(ContinuousChannelisedDataConsumerTest, ProcessPacketHandlesCounterRollover)
{
    auto p1 = make_pkt(5);
    ASSERT_TRUE(consumer_.push(p1));
    EXPECT_TRUE(consumer_.processPacket());

    auto p2 = make_pkt(0);  // counter=0 triggers the rollover path
    ASSERT_TRUE(consumer_.push(p2));
    EXPECT_TRUE(consumer_.processPacket());
}

// A packet whose computed packet_time_ns is less than reference_time_ns is
// treated as a late packet and written to the previous container (index-1).
// With nof_buffer_skips=0 the write is performed; with nof_buffer_skips>0 it
// is silently dropped.
TEST_F(ContinuousChannelisedDataConsumerTest, ProcessPacketLatePacketGoesToPreviousContainer)
{
    // First packet (ts=10): establishes reference_time_ns.
    auto p1 = make_cont_pkt_ts(5, 1000, 10);
    ASSERT_TRUE(consumer_.push(p1));
    EXPECT_TRUE(consumer_.processPacket());

    // Second packet (ts=3): packet_time_ns < reference_time_ns → late path.
    auto p2 = make_cont_pkt_ts(3, 1000, 3);
    ASSERT_TRUE(consumer_.push(p2));
    EXPECT_TRUE(consumer_.processPacket());
}

// ═══════════════════════════════════════════════════════════════════════════════
// ContinuousChannelisedData with bitwidth=32
// ═══════════════════════════════════════════════════════════════════════════════

namespace {
bool g_cont32_callback_fired = false;
void cont32_callback(void *, double, void *) { g_cont32_callback_fired = true; }
}  // namespace

class ContinuousChannelisedData32ConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_cont32_callback_fired = false;
        attachLogger([](int, const char *) {});
        json config = {
            {"nof_tiles",       1},
            {"nof_antennas",    2},
            {"nof_channels",    4},
            {"nof_samples",     4},
            {"nof_pols",        1},
            {"bitwidth",        32},
            {"sampling_time",   1.08e-6},
            {"nof_buffer_skips",0},
            {"start_time",      1000.0},
            {"max_packet_size", 512},
        };
        initialized_ = consumer_.initialiseConsumer(config);
        ASSERT_TRUE(initialized_);
        consumer_.setCallback(cont32_callback);
    }
    void TearDown() override
    {
        if (initialized_) consumer_.cleanUp();
        attachLogger(nullptr);
    }

    // 1 sample * 2 antennas * 1 pol * 1 channel * 4 bytes (32-bit)
    std::vector<uint8_t> make_pkt32(uint32_t pc)
    {
        size_t nbytes = 2 * 1 * 1 * sizeof(uint32_t);
        std::vector<uint8_t> payload(nbytes);
        for (size_t i = 0; i < nbytes; ++i) payload[i] = static_cast<uint8_t>(i + 1);
        return build_chan_packet(pc, 0, 1, 0, 2, 0, 5, 0, std::move(payload), 0x5);
    }

    TestableContinuous consumer_;
    bool initialized_ = false;
};

TEST_F(ContinuousChannelisedData32ConsumerTest, ProcessPacketReturnsTrueOnValidPacket)
{
    auto pkt = make_pkt32(0);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    EXPECT_FALSE(g_cont32_callback_fired);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Additional integrated-channel (16-bit) coverage
// ═══════════════════════════════════════════════════════════════════════════════

TEST_F(IntegratedChannelisedDataConsumerTest, CleanUpDoesNotCrash)
{
    consumer_.cleanUp();
}

// Packet builder with configurable timestamp for integrated lookahead tests.
static std::vector<uint8_t> make_integ_pkt_ts(uint64_t ts, uint8_t start_ant)
{
    std::vector<uint8_t> payload(IC_PAYLOAD_BYTES);
    for (size_t i = 0; i < IC_PAYLOAD_BYTES; ++i)
        payload[i] = static_cast<uint8_t>(i + 1);
    const uint64_t ant_chan = (0ULL << 24) | (0ULL << 16) |
                              (uint64_t(start_ant) << 8) | uint64_t(IC_INC_ANT);
    return SpeadPacket()
        .item(ID_HEAP_COUNTER, 0)
        .item(ID_PAYLOAD_LEN, payload.size())
        .item(ID_SYNC_TIME, 1000)
        .item(ID_TIMESTAMP, ts)
        .item(ID_MODE, 0x6)
        .item(ID_ANT_CHAN, ant_chan)
        .item(ID_TILE_INFO, (uint64_t(0) << 32) | (uint64_t(9) << 16) | 0ULL)
        .item(ID_PAYLOAD_OFF, 0)
        .payload(std::move(payload))
        .build();
}

// When a packet from the next integration period arrives before the current one
// is complete (lookahead cutoff exceeded), the current container is persisted
// and integration_timestamp is reset.
TEST(IntegratedChannelisedDataLookaheadTest, LookaheadFlushPersistsOnNextIntegrationPacket)
{
    attachLogger([](int, const char *) {});
    g_integ_chan = IntegChanCapture{};
    json config = {
        {"nof_tiles",    IC_NOF_TILES},
        {"nof_antennas", IC_NOF_ANT},
        {"nof_channels", IC_NOF_CHANS},
        {"nof_pols",     IC_NOF_POLS},
        {"bitwidth",     16},
        {"sampling_time", 1.08e-6},
        {"max_packet_size", 512},
        {"integration_lookahead_cutoff", 1.0e-5},
    };
    TestableIntegrated consumer;
    ASSERT_TRUE(consumer.initialiseConsumer(config));
    consumer.setCallback(integ_chan_callback);

    // First packet: ts=5 → integration_timestamp = 1000 + 5*1.08e-6
    auto p1 = make_integ_pkt_ts(5, 0);
    ASSERT_TRUE(consumer.push(p1));
    EXPECT_TRUE(consumer.processPacket());
    EXPECT_EQ(g_integ_chan.calls, 0);

    // Second packet: ts=15 → packet_time > integration_timestamp + 1e-5 → lookahead fires.
    auto p2 = make_integ_pkt_ts(15, 0);
    ASSERT_TRUE(consumer.push(p2));
    EXPECT_TRUE(consumer.processPacket());
    // After the lookahead flush, integration_timestamp is reset and the second
    // packet starts a new integration (num_packets=1, no callback yet).
    EXPECT_EQ(g_integ_chan.calls, 0);
    attachLogger(nullptr);
}

// ═══════════════════════════════════════════════════════════════════════════════
// IntegratedChannelisedData with bitwidth=32
// ═══════════════════════════════════════════════════════════════════════════════

namespace {
static constexpr size_t IC32_PAYLOAD_BYTES = IC_INC_ANT * IC_NOF_POLS * IC_NOF_CHANS * sizeof(uint32_t);

struct IntegChan32Capture { int calls = 0; };
IntegChan32Capture g_integ32_chan;
void integ32_callback(void *, double, void *) { g_integ32_chan.calls++; }
}  // namespace

class IntegratedChannelisedData32ConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_integ32_chan = IntegChan32Capture{};
        attachLogger([](int, const char *) {});
        json config = {
            {"nof_tiles",    IC_NOF_TILES},
            {"nof_antennas", IC_NOF_ANT},
            {"nof_channels", IC_NOF_CHANS},
            {"nof_pols",     IC_NOF_POLS},
            {"bitwidth",     32},
            {"sampling_time", 1.08e-6},
            {"max_packet_size", 512},
        };
        ASSERT_TRUE(consumer_.initialiseConsumer(config));
        consumer_.setCallback(integ32_callback);
    }
    void TearDown() override
    {
        consumer_.cleanUp();
        attachLogger(nullptr);
    }

    std::vector<uint8_t> make_pkt32(uint32_t pc, uint8_t start_ant)
    {
        std::vector<uint8_t> payload(IC32_PAYLOAD_BYTES);
        for (size_t i = 0; i < IC32_PAYLOAD_BYTES; ++i)
            payload[i] = static_cast<uint8_t>(i + 1);
        return build_chan_packet(pc,
                                  /*start_ch=*/0, /*nof_inc_ch=*/0,
                                  /*start_ant=*/start_ant, /*nof_inc_ant=*/IC_INC_ANT,
                                  /*tile=*/0, /*station=*/9, /*fpga=*/0,
                                  std::move(payload), /*mode=*/0x6);
    }

    TestableIntegrated consumer_;
};

TEST_F(IntegratedChannelisedData32ConsumerTest, ProcessPacketFiresCallbackAfterTotalPackets)
{
    // total_packets = (IC_NOF_ANT/IC_INC_ANT) * (IC_NOF_CHANS/nof_inc_ch) * nof_pols * nof_tiles
    // nof_inc_ch = IC32_PAYLOAD_BYTES / (IC_INC_ANT * IC_NOF_POLS * 1 * 4) = 32/(2*1*4) = 4
    // total_packets = 2 * (4/4) * 1 * 1 = 2
    auto p0 = make_pkt32(0, 0);
    ASSERT_TRUE(consumer_.push(p0));
    EXPECT_TRUE(consumer_.processPacket());
    EXPECT_EQ(g_integ32_chan.calls, 0);

    auto p1 = make_pkt32(1, 2);
    ASSERT_TRUE(consumer_.push(p1));
    EXPECT_TRUE(consumer_.processPacket());
    EXPECT_EQ(g_integ32_chan.calls, 1);
}
