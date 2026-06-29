// Consumer-path tests for the raw-antenna mode (RawData.cpp).
//
// A crafted SPEAD packet is pushed into the consumer's ring buffer,
// RawData::processPacket() parses it into the AntennaDataContainer, and
// onStreamEnd() flushes it through the callback for assertions.
//
// The .cpp is #included directly so RawData's methods and its lone consumer
// factory compile in a single TU (no separate link, no duplicate factory).
#include "RawData.cpp"  // NOLINT(bugprone-suspicious-include)

#include <gtest/gtest.h>
#include <vector>

#include "DAQ.h"
#include "spead_test_util.h"

// ── Configuration constants ──────────────────────────────────────────────────

static constexpr uint16_t NOF_TILES   = 1;
static constexpr uint16_t NOF_ANT     = 2;
static constexpr uint8_t  NOF_POLS    = 2;
static constexpr uint32_t SAMPLES_PER_BUFFER = 8;
static constexpr uint32_t PKT_SAMPLES = 2;  // (payload_length - offset) / (ant*pol)
static constexpr size_t   ANT_STRIDE  = SAMPLES_PER_BUFFER * NOF_POLS;  // dest row
static constexpr size_t   TILE_BYTES  = NOF_ANT * SAMPLES_PER_BUFFER * NOF_POLS;

// ── Callback capture ─────────────────────────────────────────────────────────

namespace {
struct Capture {
    int                  calls = 0;
    std::vector<uint8_t> data;
    uint64_t             nof_packets = 0;
    uint32_t             packet_counter0 = 0;
    uint8_t              tile_id = 0;
    uint16_t             station_id = 0;
    uint8_t              nof_antennas = 0;
    uint8_t              start_antenna0 = 0;
};
Capture g_capture;

void capturing_callback(void *data, double /*timestamp*/, void *userdata)
{
    using Meta = AntennaDataContainer<uint8_t>::AdcMetadata;
    const auto *m = static_cast<const Meta *>(userdata);
    g_capture.calls++;
    g_capture.nof_packets = m->nof_packets;
    g_capture.packet_counter0 = m->packet_counter[0];
    g_capture.tile_id = m->tile_id;
    g_capture.station_id = m->station_id;
    g_capture.nof_antennas = m->nof_antennas;
    g_capture.start_antenna0 = m->start_antenna_id[0];
    auto *p = static_cast<uint8_t *>(data);
    g_capture.data.assign(p, p + TILE_BYTES);
}

// SPEAD item ids used by RawData::processPacket.
constexpr int ID_HEAP_COUNTER = 0x0001;
constexpr int ID_PAYLOAD_LEN  = 0x0004;
constexpr int ID_SYNC_TIME    = 0x1027;
constexpr int ID_TIMESTAMP    = 0x1600;
constexpr int ID_ANTENNA_INFO = 0x2000;
constexpr int ID_TILE_INFO    = 0x2001;
constexpr int ID_PAYLOAD_OFF  = 0x3300;
constexpr int ID_MODE         = 0x2004;
}  // namespace

// ── Testable subclass ────────────────────────────────────────────────────────

class TestableRawData : public RawData {
public:
    using RawData::processPacket;
    using RawData::onStreamEnd;
    using RawData::packetFilter;
    bool push(std::vector<uint8_t> &pkt) { return ring_buffer->push(pkt.data(), pkt.size()); }
};

// ── Fixture ──────────────────────────────────────────────────────────────────

class RawDataConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_capture = Capture{};
        attachLogger([](int, const char *) {});
        json config = {
            {"nof_antennas", NOF_ANT},
            {"samples_per_buffer", SAMPLES_PER_BUFFER},
            {"nof_tiles", NOF_TILES},
            {"nof_pols", NOF_POLS},
            {"max_packet_size", 512},
        };
        ASSERT_TRUE(consumer_.initialiseConsumer(config));
        consumer_.setCallback(capturing_callback);
    }
    void TearDown() override { attachLogger(nullptr); }

    // Build a synchronised raw packet (nof_antennas antennas interleaved).
    // payload layout is [sample][antenna][pol].
    static std::vector<uint8_t> make_packet(uint32_t packet_counter,
                                            uint8_t start_antenna,
                                            uint8_t nof_antennas,
                                            std::vector<uint8_t> payload,
                                            uint8_t tile_id = 2,
                                            uint16_t station_id = 9,
                                            uint64_t mode = 0x0)
    {
        const uint64_t antenna_info = uint64_t(nof_antennas) | (uint64_t(start_antenna) << 8);
        const uint64_t tile_info = (uint64_t(tile_id) << 32) |
                                   (uint64_t(station_id) << 16) | /*fpga=*/0;
        // Mode item first — packetFilter scans slots [0, nitems) and skips the
        // header (slot 0) and the final slot, so the marker must not be last.
        return SpeadPacket()
            .item(ID_MODE, mode)
            .item(ID_HEAP_COUNTER, packet_counter)
            .item(ID_PAYLOAD_LEN, payload.size())
            .item(ID_SYNC_TIME, 1000)
            .item(ID_TIMESTAMP, 5)
            .item(ID_ANTENNA_INFO, antenna_info)
            .item(ID_TILE_INFO, tile_info)
            .item(ID_PAYLOAD_OFF, 0)
            .payload(std::move(payload))
            .build();
    }

    TestableRawData consumer_;
};

// Interleaved [sample][antenna][pol] payload; value encodes antenna*10 + sample*2 + pol.
static std::vector<uint8_t> make_payload()
{
    std::vector<uint8_t> src(PKT_SAMPLES * NOF_ANT * NOF_POLS);
    for (uint8_t s = 0; s < PKT_SAMPLES; ++s)
        for (uint8_t a = 0; a < NOF_ANT; ++a)
            for (uint8_t p = 0; p < NOF_POLS; ++p)
                src[s * NOF_ANT * NOF_POLS + a * NOF_POLS + p] = a * 10 + s * 2 + p;
    return src;
}

// ── packetFilter ─────────────────────────────────────────────────────────────

TEST_F(RawDataConsumerTest, PacketFilterAcceptsRawModes)
{
    auto burst = make_packet(0, 0, NOF_ANT, make_payload(), 2, 9, /*mode=*/0x0);
    auto cont  = make_packet(0, 0, NOF_ANT, make_payload(), 2, 9, /*mode=*/0x1);
    EXPECT_TRUE(consumer_.packetFilter(burst.data()));
    EXPECT_TRUE(consumer_.packetFilter(cont.data()));
}

TEST_F(RawDataConsumerTest, PacketFilterRejectsWrongMode)
{
    auto pkt = make_packet(0, 0, NOF_ANT, make_payload(), 2, 9, /*mode=*/0x7);
    EXPECT_FALSE(consumer_.packetFilter(pkt.data()));
}

// ── processPacket: parsing + de-interleaving ─────────────────────────────────

TEST_F(RawDataConsumerTest, ProcessPacketParsesMetadata)
{
    auto pkt = make_packet(/*packet_counter=*/0, /*start_antenna=*/0, NOF_ANT, make_payload());
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    consumer_.onStreamEnd();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.nof_packets, 1u);
    EXPECT_EQ(g_capture.packet_counter0, 0u);
    EXPECT_EQ(g_capture.tile_id, 2u);
    EXPECT_EQ(g_capture.station_id, 9u);
    EXPECT_EQ(g_capture.nof_antennas, NOF_ANT);
    EXPECT_EQ(g_capture.start_antenna0, 0u);
}

TEST_F(RawDataConsumerTest, ProcessPacketDeinterleavesAntennas)
{
    auto pkt = make_packet(/*packet_counter=*/0, /*start_antenna=*/0, NOF_ANT, make_payload());
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    consumer_.onStreamEnd();

    ASSERT_EQ(g_capture.calls, 1);
    // Container layout [antenna][sample][pol]; each antenna is contiguous.
    for (uint8_t a = 0; a < NOF_ANT; ++a)
        for (uint8_t s = 0; s < PKT_SAMPLES; ++s)
            for (uint8_t p = 0; p < NOF_POLS; ++p) {
                const size_t off = a * ANT_STRIDE + s * NOF_POLS + p;
                EXPECT_EQ(g_capture.data[off], a * 10 + s * 2 + p)
                    << "ant=" << +a << " samp=" << +s << " pol=" << +p;
            }
}

TEST_F(RawDataConsumerTest, ProcessPacketTimesOutWhenRingEmpty)
{
    EXPECT_FALSE(consumer_.processPacket());
    EXPECT_EQ(g_capture.calls, 0);
}

TEST_F(RawDataConsumerTest, OnStreamEndWithoutDataDoesNotFireCallback)
{
    // No packet processed -> nof_received_samples == 0 -> no persist.
    consumer_.onStreamEnd();
    EXPECT_EQ(g_capture.calls, 0);
}
