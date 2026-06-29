// Consumer-path tests for the antenna-buffer mode (AntennaBuffer.cpp).
//
// These drive the real SPEAD parsing in AntennaBuffer::processPacket(): a
// crafted packet is pushed into the consumer's ring buffer, processPacket()
// parses it into a container, and onStreamEnd() flushes the container through
// the callback so we can assert on the parsed metadata and payload placement.
//
// The .cpp is #included directly so the test compiles AntennaBuffer's methods
// (and the lone consumer factory) in a single translation unit — no separate
// link, no duplicate-symbol clash with the factory defined in the header.
#include "AntennaBuffer.cpp"  // NOLINT(bugprone-suspicious-include)

#include <gtest/gtest.h>
#include <vector>

#include "DAQ.h"
#include "spead_test_util.h"

// ── Constants matching the consumer configuration ────────────────────────────

static constexpr uint16_t NOF_TILES     = 1;
static constexpr uint16_t NOF_ANT       = 4;   // antennas_per_fpga = 2
static constexpr uint8_t  NOF_POLS      = 2;
static constexpr uint32_t NOF_SAMPLES   = 8;
static constexpr uint32_t PACKET_SAMPLES = 4;  // one 4-sample block per antenna
static constexpr size_t   ANT_STRIDE    = NOF_SAMPLES * NOF_POLS;     // dest row
static constexpr size_t   PACKET_PER_ANT = PACKET_SAMPLES * NOF_POLS; // 8 bytes
static constexpr size_t   TILE_BYTES    = NOF_ANT * NOF_POLS * NOF_SAMPLES;

// ── Callback capture ─────────────────────────────────────────────────────────

namespace {
struct Capture {
    int                  calls = 0;
    std::vector<uint8_t> data;
    uint64_t             nof_packets = 0;
    uint32_t             packet_counter0 = 0;
    uint8_t              tile_id = 0;
    uint16_t             station_id = 0;
    uint8_t              antenna_0_id = 0;
    uint8_t              nof_included_antennas = 0;
    uint8_t              fpga_id0 = 0;
    uint64_t             payload_length = 0;
};
Capture g_capture;

void capturing_callback(void *data, double /*timestamp*/, void *userdata)
{
    using Meta = AntennaBufferDataContainer<uint8_t>::AntennaBufferMetadata;
    const auto *m = static_cast<const Meta *>(userdata);
    g_capture.calls++;
    g_capture.nof_packets = m->nof_packets;
    g_capture.packet_counter0 = m->packet_counter[0];
    g_capture.tile_id = m->tile_id;
    g_capture.station_id = m->station_id;
    g_capture.antenna_0_id = m->antenna_0_id;
    g_capture.nof_included_antennas = m->nof_included_antennas;
    g_capture.fpga_id0 = m->fpga_id[0];
    g_capture.payload_length = m->payload_length;
    auto *p = static_cast<uint8_t *>(data);
    g_capture.data.assign(p, p + TILE_BYTES);
}

// SPEAD item ids used by AntennaBuffer::processPacket.
constexpr int ID_HEAP_COUNTER = 0x0001;
constexpr int ID_PAYLOAD_LEN  = 0x0004;
constexpr int ID_SYNC_TIME    = 0x1027;
constexpr int ID_TIMESTAMP    = 0x1600;
constexpr int ID_ANTENNA_INFO = 0x2006;
constexpr int ID_TILE_INFO    = 0x2001;
constexpr int ID_PAYLOAD_OFF  = 0x3300;
constexpr int ID_MODE         = 0x2004;
}  // namespace

// ── Testable subclass exposing the protected packet path ─────────────────────

class TestableAntennaBuffer : public AntennaBuffer {
public:
    using AntennaBuffer::processPacket;
    using AntennaBuffer::onStreamEnd;
    using AntennaBuffer::packetFilter;

    // ring_buffer is protected in DataConsumer; expose a push for the test.
    bool push(std::vector<uint8_t> &pkt) { return ring_buffer->push(pkt.data(), pkt.size()); }
};

// ── Fixture ──────────────────────────────────────────────────────────────────

class AntennaBufferConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_capture = Capture{};
        // Attach a logger so any LOG(FATAL) forwards instead of exiting.
        attachLogger([](int, const char *) {});
        json config = {
            {"nof_antennas", NOF_ANT},
            {"nof_samples", NOF_SAMPLES},
            {"nof_tiles", NOF_TILES},
            {"max_packet_size", 512},
        };
        ASSERT_TRUE(consumer_.initialiseConsumer(config));
        consumer_.setCallback(capturing_callback);
    }
    void TearDown() override { attachLogger(nullptr); }

    // Build a valid antenna-buffer packet. Defaults give packet_index 0.
    static std::vector<uint8_t> make_packet(uint32_t packet_counter,
                                            uint8_t fpga_id,
                                            std::vector<uint8_t> payload,
                                            uint8_t tile_id = 3,
                                            uint16_t station_id = 17,
                                            uint64_t mode = 0xC)
    {
        const uint64_t tile_info = (uint64_t(tile_id) << 32) |
                                   (uint64_t(station_id) << 16) | fpga_id;
        const uint64_t antenna_info = uint64_t(10) | (uint64_t(11) << 8) |
                                      (uint64_t(12) << 16) | (uint64_t(13) << 24) |
                                      (uint64_t(4) << 32);  // nof_included_antennas = 4
        // NB: the mode item (0x2004) is placed first. packetFilter scans item
        // slots [0, nitems) — slot 0 is the header and the final item slot is
        // not scanned — so the mode marker must not be last.
        return SpeadPacket()
            .item(ID_MODE, mode)
            .item(ID_HEAP_COUNTER, packet_counter)
            .item(ID_PAYLOAD_LEN, payload.size())  // payload_offset = 0
            .item(ID_SYNC_TIME, 1000)
            .item(ID_TIMESTAMP, 5)
            .item(ID_ANTENNA_INFO, antenna_info)
            .item(ID_TILE_INFO, tile_info)
            .item(ID_PAYLOAD_OFF, 0)
            .payload(std::move(payload))
            .build();
    }

    TestableAntennaBuffer consumer_;
};

// A 16-byte payload: antenna 0 -> bytes 1..8, antenna 1 -> bytes 9..16.
static std::vector<uint8_t> make_payload()
{
    std::vector<uint8_t> p(NOF_ANT / 2 * PACKET_SAMPLES * NOF_POLS);
    for (size_t i = 0; i < p.size(); ++i)
        p[i] = static_cast<uint8_t>(i + 1);
    return p;
}

// ── packetFilter ─────────────────────────────────────────────────────────────

TEST_F(AntennaBufferConsumerTest, PacketFilterAcceptsAntennaBufferMode)
{
    auto pkt = make_packet(/*packet_counter=*/0, /*fpga_id=*/0, make_payload());
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(AntennaBufferConsumerTest, PacketFilterRejectsWrongMode)
{
    // A well-formed packet whose mode marker (0x2004) is not 0xC is rejected.
    auto pkt = make_packet(/*packet_counter=*/0, /*fpga_id=*/0, make_payload(),
                           /*tile_id=*/3, /*station_id=*/17, /*mode=*/0x5);
    EXPECT_FALSE(consumer_.packetFilter(pkt.data()));
}

TEST_F(AntennaBufferConsumerTest, PacketFilterRejectsNonSpead)
{
    std::vector<uint8_t> garbage(64, 0xFF);
    EXPECT_FALSE(consumer_.packetFilter(garbage.data()));
}

// ── processPacket: parsing + placement ───────────────────────────────────────

TEST_F(AntennaBufferConsumerTest, ProcessPacketParsesMetadata)
{
    auto pkt = make_packet(/*packet_counter=*/4, /*fpga_id=*/0, make_payload());
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    consumer_.onStreamEnd();  // flush container through the callback

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.nof_packets, 1u);
    EXPECT_EQ(g_capture.packet_counter0, 4u);
    EXPECT_EQ(g_capture.tile_id, 3u);
    EXPECT_EQ(g_capture.station_id, 17u);
    EXPECT_EQ(g_capture.antenna_0_id, 10u);
    EXPECT_EQ(g_capture.nof_included_antennas, 4u);
    EXPECT_EQ(g_capture.fpga_id0, 0u);
    EXPECT_EQ(g_capture.payload_length, 16u);
}

TEST_F(AntennaBufferConsumerTest, ProcessPacketPlacesPayloadForFpga0)
{
    auto payload = make_payload();
    auto pkt = make_packet(/*packet_counter=*/0, /*fpga_id=*/0, payload);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    consumer_.onStreamEnd();

    ASSERT_EQ(g_capture.calls, 1);
    // fpga 0 -> antennas 0 and 1; each gets PACKET_PER_ANT bytes at its row start.
    for (size_t k = 0; k < PACKET_PER_ANT; ++k) {
        EXPECT_EQ(g_capture.data[0 * ANT_STRIDE + k], payload[0 * PACKET_PER_ANT + k]);
        EXPECT_EQ(g_capture.data[1 * ANT_STRIDE + k], payload[1 * PACKET_PER_ANT + k]);
    }
    // The fpga-1 antennas (2, 3) are untouched by this packet.
    EXPECT_EQ(g_capture.data[2 * ANT_STRIDE], 0u);
}

TEST_F(AntennaBufferConsumerTest, ProcessPacketPlacesPayloadForFpga1)
{
    auto payload = make_payload();
    auto pkt = make_packet(/*packet_counter=*/0, /*fpga_id=*/1, payload);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    consumer_.onStreamEnd();

    ASSERT_EQ(g_capture.calls, 1);
    // fpga 1 -> antennas 2 and 3.
    for (size_t k = 0; k < PACKET_PER_ANT; ++k) {
        EXPECT_EQ(g_capture.data[2 * ANT_STRIDE + k], payload[0 * PACKET_PER_ANT + k]);
        EXPECT_EQ(g_capture.data[3 * ANT_STRIDE + k], payload[1 * PACKET_PER_ANT + k]);
    }
    EXPECT_EQ(g_capture.data[0 * ANT_STRIDE], 0u);
}

TEST_F(AntennaBufferConsumerTest, ProcessPacketTimesOutWhenRingEmpty)
{
    // No packet pushed: processPacket should hit the pull timeout and return false.
    EXPECT_FALSE(consumer_.processPacket());
    EXPECT_EQ(g_capture.calls, 0);
}

TEST_F(AntennaBufferConsumerTest, MultiplePacketsAccumulateInContainer)
{
    auto payload = make_payload();
    auto p0 = make_packet(/*packet_counter=*/0, /*fpga_id=*/0, payload);
    auto p1 = make_packet(/*packet_counter=*/0, /*fpga_id=*/1, payload);
    ASSERT_TRUE(consumer_.push(p0));
    ASSERT_TRUE(consumer_.processPacket());
    ASSERT_TRUE(consumer_.push(p1));
    ASSERT_TRUE(consumer_.processPacket());
    consumer_.onStreamEnd();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.nof_packets, 2u);
    // Both FPGA halves were written.
    EXPECT_EQ(g_capture.data[0 * ANT_STRIDE], payload[0]);
    EXPECT_EQ(g_capture.data[2 * ANT_STRIDE], payload[0]);
}
