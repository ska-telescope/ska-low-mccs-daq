// Consumer-path tests for the beamformed DAQ modes (BeamformedData.cpp).
//
// BeamformedData::processPacket + onStreamEnd (burst beam, mode 0x8) and
// IntegratedBeamformedData::processPacket (integrated beam, modes 0x9/0x11)
// are driven through crafted SPEAD packets pushed into the consumer ring buffer.
//
// The .cpp is #included directly so both consumer classes and their factories
// compile in a single TU — no duplicate-symbol clash with the factories defined
// in the header.
#include "BeamformedData.cpp"  // NOLINT(bugprone-suspicious-include)

#include <gtest/gtest.h>
#include <cstring>
#include <vector>

#include "DAQ.h"
#include "spead_test_util.h"

// ── SPEAD item IDs used by BeamformedData / IntegratedBeamformedData ──────────

namespace {
constexpr int ID_HEAP_COUNTER = 0x0001;
constexpr int ID_PAYLOAD_LEN  = 0x0004;
constexpr int ID_SYNC_TIME    = 0x1027;
constexpr int ID_TIMESTAMP    = 0x1600;
// 0x2005: bits[39:32]=beam_id, bits[31:16]=start_channel_id, bits[15:0]=nof_included_channels
constexpr int ID_CHANNEL_INFO = 0x2005;
// 0x2003: bits[39:32]=tile_id, bits[31:16]=station_id, bits[15:0]=nof_contributing_antennas
constexpr int ID_TILE_INFO    = 0x2003;
constexpr int ID_PAYLOAD_OFF  = 0x3300;
constexpr int ID_MODE         = 0x2004;
}  // namespace

// ── Callback capture ─────────────────────────────────────────────────────────

namespace {
struct BeamCapture {
    int      calls = 0;
    uint64_t nof_packets = 0;
    uint32_t packet_counter0 = 0;
    uint8_t  tile_id = 0;
    uint16_t station_id = 0;
    uint8_t  beam_id0 = 0;
    uint16_t start_channel_id0 = 0;
    uint16_t nof_included_channels = 0;
    uint16_t nof_contributing_antennas = 0;
};
BeamCapture g_burst_cap;
BeamCapture g_integ_cap;

void burst_callback(void * /*data*/, double /*ts*/, void *ud)
{
    using Meta = BurstBeamDataContainer<uint32_t>::BeamMetadata;
    const auto *m = static_cast<const Meta *>(ud);
    g_burst_cap.calls++;
    g_burst_cap.nof_packets               = m->nof_packets;
    g_burst_cap.packet_counter0           = m->packet_counter[0];
    g_burst_cap.tile_id                   = m->tile_id;
    g_burst_cap.station_id                = m->station_id;
    g_burst_cap.beam_id0                  = m->beam_id[0];
    g_burst_cap.start_channel_id0         = m->start_channel_id[0];
    g_burst_cap.nof_included_channels     = m->nof_included_channels;
    g_burst_cap.nof_contributing_antennas = m->nof_contributing_antennas;
}

void integ_callback(void * /*data*/, double /*ts*/, void *ud)
{
    using Meta = IntegratedBeamDataContainer<uint32_t>::BeamMetadata;
    const auto *m = static_cast<const Meta *>(ud);
    g_integ_cap.calls++;
    g_integ_cap.nof_packets               = m->nof_packets;
    g_integ_cap.packet_counter0           = m->packet_counter[0];
    g_integ_cap.tile_id                   = m->tile_id;
    g_integ_cap.station_id                = m->station_id;
    g_integ_cap.beam_id0                  = m->beam_id[0];
    g_integ_cap.start_channel_id0         = m->start_channel_id[0];
    g_integ_cap.nof_included_channels     = m->nof_included_channels;
    g_integ_cap.nof_contributing_antennas = m->nof_contributing_antennas;
}
}  // namespace

// ── Testable subclasses ───────────────────────────────────────────────────────

class TestableBurst : public BeamformedData {
public:
    using BeamformedData::processPacket;
    using BeamformedData::onStreamEnd;
    using BeamformedData::packetFilter;
    bool push(std::vector<uint8_t> &pkt) { return ring_buffer->push(pkt.data(), pkt.size()); }
};

class TestableInteg : public IntegratedBeamformedData {
public:
    using IntegratedBeamformedData::processPacket;
    using IntegratedBeamformedData::packetFilter;
    bool push(std::vector<uint8_t> &pkt) { return ring_buffer->push(pkt.data(), pkt.size()); }
};

// ── Geometry ─────────────────────────────────────────────────────────────────

// Burst beam: one packet per test, one tile, two polarisations, four channels.
static constexpr uint16_t B_NOF_TILES   = 1;
static constexpr uint8_t  B_NOF_POLS    = 2;
static constexpr uint16_t B_NOF_CHANS   = 4;
static constexpr uint32_t B_NOF_SAMPLES = 2;
// Burst payload: nof_channels * nof_pols uint32_t values (one "sample" slice).
static constexpr size_t   B_PAYLOAD_BYTES = B_NOF_CHANS * B_NOF_POLS * sizeof(uint32_t);

// Integrated beam geometry.
// nof_pols=2 is required: the container stores pol0 and pol1 in separate halves of
// beam_data[i].data, and pol1_ptr = pol0_ptr + nof_channels*nof_samples.  With
// nof_pols=1 the buffer has only nof_channels elements and pol1_ptr lands past it.
// nof_included_channels=1 keeps the inner-loop index (2*j) within nof_channels.
// total_packets = nof_pols * nof_tiles * nof_samples * nof_beams = 2, so the
// THIRD processPacket call triggers persist_container with the first two packets' data.
static constexpr uint16_t I_NOF_TILES    = 1;
static constexpr uint16_t I_NOF_BEAMS    = 1;
static constexpr uint8_t  I_NOF_POLS     = 2;
static constexpr uint16_t I_NOF_CHANS    = 4;
static constexpr uint32_t I_NOF_SAMPLES  = 1;
static constexpr uint16_t I_INC_CHANS    = 1;  // nof_included_channels per packet
// payload: I_INC_CHANS * I_NOF_POLS uint32_t values (one time sample, two pols)
static constexpr size_t   I_PAYLOAD_BYTES = I_INC_CHANS * I_NOF_POLS * sizeof(uint32_t);

// ── Packet builder ────────────────────────────────────────────────────────────

// Builds a beam packet. packetFilter for both classes scans item slots [0, nitems) for
// item ID 0x2004, so the mode item can be placed first (position independent).
static std::vector<uint8_t> build_beam_packet(uint32_t packet_counter,
                                               uint8_t  beam_id,
                                               uint16_t start_channel,
                                               uint16_t nof_included_channels,
                                               uint8_t  tile_id,
                                               uint16_t station_id,
                                               uint16_t nof_contributing,
                                               std::vector<uint8_t> payload,
                                               uint64_t mode)
{
    const uint64_t chan_info = (uint64_t(beam_id) << 32) |
                               (uint64_t(start_channel) << 16) |
                               uint64_t(nof_included_channels);
    const uint64_t tile_info = (uint64_t(tile_id) << 32) |
                               (uint64_t(station_id) << 16) |
                               uint64_t(nof_contributing);
    return SpeadPacket()
        .item(ID_MODE,         mode)
        .item(ID_HEAP_COUNTER, packet_counter)
        .item(ID_PAYLOAD_LEN,  payload.size())
        .item(ID_SYNC_TIME,    1000)
        .item(ID_TIMESTAMP,    5)
        .item(ID_CHANNEL_INFO, chan_info)
        .item(ID_TILE_INFO,    tile_info)
        .item(ID_PAYLOAD_OFF,  0)
        .payload(std::move(payload))
        .build();
}

static std::vector<uint8_t> dummy_payload(size_t nbytes)
{
    std::vector<uint8_t> p(nbytes);
    for (size_t i = 0; i < nbytes; ++i)
        p[i] = static_cast<uint8_t>(i + 1);
    return p;
}

// ═══════════════════════════════════════════════════════════════════════════════
// BeamformedData (burst beam, mode 0x8)
// ═══════════════════════════════════════════════════════════════════════════════

class BurstBeamConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_burst_cap = BeamCapture{};
        attachLogger([](int, const char *) {});
        json config = {
            {"nof_tiles",    B_NOF_TILES},
            {"nof_samples",  B_NOF_SAMPLES},
            {"nof_channels", B_NOF_CHANS},
            {"nof_pols",     B_NOF_POLS},
            {"max_packet_size", 512},
        };
        ASSERT_TRUE(consumer_.initialiseConsumer(config));
        consumer_.setCallback(burst_callback);
    }
    void TearDown() override { attachLogger(nullptr); }

    TestableBurst consumer_;
};

TEST_F(BurstBeamConsumerTest, PacketFilterAcceptsBurstBeamMode)
{
    auto pkt = build_beam_packet(0, 0, 0, B_NOF_CHANS, 0, 1, 1,
                                 dummy_payload(B_PAYLOAD_BYTES), 0x8);
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(BurstBeamConsumerTest, PacketFilterRejectsWrongMode)
{
    auto pkt = build_beam_packet(0, 0, 0, B_NOF_CHANS, 0, 1, 1,
                                 dummy_payload(B_PAYLOAD_BYTES), 0x4);
    EXPECT_FALSE(consumer_.packetFilter(pkt.data()));
}

TEST_F(BurstBeamConsumerTest, PacketFilterRejectsNonSpead)
{
    std::vector<uint8_t> garbage(64, 0xFF);
    EXPECT_FALSE(consumer_.packetFilter(garbage.data()));
}

TEST_F(BurstBeamConsumerTest, ProcessPacketTimesOutWhenRingEmpty)
{
    EXPECT_FALSE(consumer_.processPacket());
    EXPECT_EQ(g_burst_cap.calls, 0);
}

TEST_F(BurstBeamConsumerTest, ProcessPacketParsesMetadata)
{
    // packet_counter must be 0: add_data places data at offset=pc*payload_length,
    // which overflows the container buffer for any pc > 0 given our geometry.
    auto pkt = build_beam_packet(/*pc=*/0, /*beam=*/1, /*start_ch=*/0, B_NOF_CHANS,
                                  /*tile=*/5, /*station=*/11, /*nof_ant=*/16,
                                  dummy_payload(B_PAYLOAD_BYTES), 0x8);
    ASSERT_TRUE(consumer_.push(pkt));
    EXPECT_TRUE(consumer_.processPacket());
    consumer_.onStreamEnd();

    ASSERT_EQ(g_burst_cap.calls, 1);
    EXPECT_EQ(g_burst_cap.nof_packets, 1u);
    EXPECT_EQ(g_burst_cap.packet_counter0, 0u);
    EXPECT_EQ(g_burst_cap.tile_id, 5u);
    EXPECT_EQ(g_burst_cap.station_id, 11u);
    EXPECT_EQ(g_burst_cap.beam_id0, 1u);
    EXPECT_EQ(g_burst_cap.start_channel_id0, 0u);
    EXPECT_EQ(g_burst_cap.nof_included_channels, B_NOF_CHANS);
    EXPECT_EQ(g_burst_cap.nof_contributing_antennas, 16u);
}

TEST_F(BurstBeamConsumerTest, OnStreamEndWithoutDataDoesNotFireCallback)
{
    consumer_.onStreamEnd();
    EXPECT_EQ(g_burst_cap.calls, 0);
}

TEST_F(BurstBeamConsumerTest, MultiplePacketsAccumulateBeforeFlush)
{
    // Both packets use pc=0 to avoid the buffer-overflow in add_data.
    // The second packet overwrites the same data region but still increments nof_packets.
    auto p0 = build_beam_packet(0, 0, 0, B_NOF_CHANS, 0, 1, 1,
                                 dummy_payload(B_PAYLOAD_BYTES), 0x8);
    auto p1 = build_beam_packet(0, 0, 0, B_NOF_CHANS, 0, 1, 1,
                                 dummy_payload(B_PAYLOAD_BYTES), 0x8);
    ASSERT_TRUE(consumer_.push(p0));
    EXPECT_TRUE(consumer_.processPacket());
    ASSERT_TRUE(consumer_.push(p1));
    EXPECT_TRUE(consumer_.processPacket());
    consumer_.onStreamEnd();

    ASSERT_EQ(g_burst_cap.calls, 1);
    EXPECT_EQ(g_burst_cap.nof_packets, 2u);
}

// ═══════════════════════════════════════════════════════════════════════════════
// IntegratedBeamformedData (modes 0x9 / 0x11)
// ═══════════════════════════════════════════════════════════════════════════════

class IntegBeamConsumerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        g_integ_cap = BeamCapture{};
        attachLogger([](int, const char *) {});
        // total_packets = nof_pols * nof_tiles * nof_samples * nof_beams = 2,
        // so persist fires when received_packets reaches 2, i.e. on the THIRD packet.
        json config = {
            {"nof_tiles",    I_NOF_TILES},
            {"nof_beams",    I_NOF_BEAMS},
            {"nof_samples",  I_NOF_SAMPLES},
            {"nof_channels", I_NOF_CHANS},
            {"nof_pols",     I_NOF_POLS},
            {"max_packet_size", 512},
        };
        ASSERT_TRUE(consumer_.initialiseConsumer(config));
        consumer_.setCallback(integ_callback);
    }
    void TearDown() override { attachLogger(nullptr); }

    TestableInteg consumer_;
};

TEST_F(IntegBeamConsumerTest, PacketFilterAcceptsMode9)
{
    auto pkt = build_beam_packet(0, 0, 0, I_INC_CHANS, 0, 1, 1,
                                 dummy_payload(I_PAYLOAD_BYTES), 0x9);
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(IntegBeamConsumerTest, PacketFilterAcceptsMode11)
{
    auto pkt = build_beam_packet(0, 0, 0, I_INC_CHANS, 0, 1, 1,
                                 dummy_payload(I_PAYLOAD_BYTES), 0x11);
    EXPECT_TRUE(consumer_.packetFilter(pkt.data()));
}

TEST_F(IntegBeamConsumerTest, PacketFilterRejectsBurstMode)
{
    auto pkt = build_beam_packet(0, 0, 0, I_INC_CHANS, 0, 1, 1,
                                 dummy_payload(I_PAYLOAD_BYTES), 0x8);
    EXPECT_FALSE(consumer_.packetFilter(pkt.data()));
}

TEST_F(IntegBeamConsumerTest, ProcessPacketTimesOutWhenRingEmpty)
{
    EXPECT_FALSE(consumer_.processPacket());
    EXPECT_EQ(g_integ_cap.calls, 0);
}

TEST_F(IntegBeamConsumerTest, ProcessPacketParsesMetadataOnFlush)
{
    // total_packets=2: packets p0 and p1 fill the buffer; the third processPacket
    // (p2) finds received_packets==total and triggers persist_container with p0+p1's data.
    auto p0 = build_beam_packet(/*pc=*/0, /*beam=*/0, /*start_ch=*/0, I_INC_CHANS,
                                 /*tile=*/0, /*station=*/3, /*nof_ant=*/8,
                                 dummy_payload(I_PAYLOAD_BYTES), 0x9);
    ASSERT_TRUE(consumer_.push(p0));
    EXPECT_TRUE(consumer_.processPacket());
    EXPECT_EQ(g_integ_cap.calls, 0);

    auto p1 = build_beam_packet(1, 0, 0, I_INC_CHANS, 0, 3, 8,
                                 dummy_payload(I_PAYLOAD_BYTES), 0x9);
    ASSERT_TRUE(consumer_.push(p1));
    EXPECT_TRUE(consumer_.processPacket());
    EXPECT_EQ(g_integ_cap.calls, 0);  // still buffering

    auto p2 = build_beam_packet(2, 0, 0, I_INC_CHANS, 0, 0, 0,
                                 dummy_payload(I_PAYLOAD_BYTES), 0x9);
    ASSERT_TRUE(consumer_.push(p2));
    EXPECT_TRUE(consumer_.processPacket());

    ASSERT_EQ(g_integ_cap.calls, 1);
    EXPECT_EQ(g_integ_cap.nof_packets, 2u);  // p0 and p1 were both stored
    EXPECT_EQ(g_integ_cap.packet_counter0, 0u);
    EXPECT_EQ(g_integ_cap.tile_id, 0u);
    EXPECT_EQ(g_integ_cap.station_id, 3u);
    EXPECT_EQ(g_integ_cap.nof_contributing_antennas, 8u);
}
