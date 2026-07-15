// Integrated channelised-data (bandpass-monitoring) consumer tests
// (ChannelisedData.cpp, class IntegratedChannelisedData).
//
// The integrated-channel consumer accumulates one integration per tile in an
// IntegratedChannelDataContainer and, on completion, fires the registered
// callback once for every tile that received a full integration. This is the
// path the bandpass monitor consumes: one delivered buffer == one tile's
// integrated spectrum for the current integration.
//
// ── When the callback fires ──────────────────────────────────────────────────
// processPacket() persists the container as soon as the whole integration has
// arrived:
//   total_packets = (nof_antennas      / nof_included_antennas)
//                 * (nof_channels      / nof_included_channels)
//                 * nof_pols * nof_tiles
// and persist_container() then calls the callback for each tile whose packet
// count reached IntegratedChannelDataContainer::PACKETS_PER_TILE (32). So a
// complete integration across N tiles yields exactly N callbacks.
//
// ── Delivered buffer layout ──────────────────────────────────────────────────
// The callback receives one tile's buffer, laid out (nof_samples == 1 for
// integrated data) as [channel][antenna][pol] of uint16_t, i.e. element
//   index(channel, antenna, pol) = channel*(nof_antennas*nof_pols)
//                                + antenna*nof_pols + pol.
// Each packet's payload is [included_channels][included_antennas][pols], copied
// into that buffer at (start_channel+i, start_antenna+ant, pol). The data tests
// stamp every sample with a value derived from its coordinate and check it comes
// back at exactly the right slot.

#include <cstdint>
#include <cstring>
#include <functional>
#include <gtest/gtest.h>
#include <vector>

#include "ChannelisedData.h"
#include "spead_test_util.h"

#define SMALL_NUMBER 2
#define BIG_NUMBER 32
#define BIGGER_NUMBER 4099
#define BIGGEST_NUMBER 26137

namespace
{
    // SPEAD capture-mode marker for integrated channel data (item 0x2004/slot 5,
    // read by packetFilter). See IntegratedChannelisedData::packetFilter.
    constexpr uint64_t MODE_INTEGRATED_CHANNEL = 0x6;

    // A deterministic 16-bit value for a sample's full coordinate (integration
    // generation, tile, channel, antenna, pol). It only needs to change when any
    // coordinate changes, so a sample written to the wrong slot - wrong tile,
    // channel, antenna, pol, or left over from a previous integration - gives a
    // mismatching value. Each slot is compared against its own recomputed value,
    // so wrapping past 16 bits is harmless.
    uint16_t sample_value(int gen, int tile, int channel, int antenna, int pol)
    {
        return (uint16_t)(1
                          + gen * BIGGEST_NUMBER
                          + tile * BIGGER_NUMBER
                          + channel * BIG_NUMBER
                          + antenna * SMALL_NUMBER
                          + pol);
    }

    // Pack item 0x2002 (antenna/channel info):
    //   bits[39:24]=start_channel, [23:16]=nof_channels,
    //   bits[15:8] =start_antenna, [7:0] =nof_antennas.
    // For integrated data nof_included_channels is recomputed from the payload
    // length, so the channel-count field here is informational only.
    uint64_t chan_info(uint16_t start_channel, uint8_t nof_channels,
                       uint8_t start_antenna, uint8_t nof_antennas)
    {
        return ((uint64_t)start_channel << 24) | ((uint64_t)nof_channels << 16) |
               ((uint64_t)start_antenna << 8) | (uint64_t)nof_antennas;
    }

    // Pack item 0x2001 (tile/tpm info): tile_id at bits[39:32], station at
    // [31:16], fpga_id at [7:0] (see the 0x2001 case in processPacket).
    uint64_t tpm_info(uint8_t tile_id, uint16_t station_id = 0, uint8_t fpga_id = 0)
    {
        return ((uint64_t)tile_id << 32) | ((uint64_t)station_id << 16) | (uint64_t)fpga_id;
    }

    // Build the payload for one packet: [nof_channels][nof_antennas][nof_pols] of
    // uint16_t, each element stamped with sample_value() for its global
    // coordinate.
    std::vector<uint8_t> make_payload(int gen, int tile,
                                      int start_channel, int nof_channels,
                                      int start_antenna, int nof_antennas, int nof_pols)
    {
        const size_t n = (size_t)nof_channels * nof_antennas * nof_pols;
        std::vector<uint16_t> samples(n);
        for (int c = 0; c < nof_channels; ++c)
            for (int a = 0; a < nof_antennas; ++a)
                for (int p = 0; p < nof_pols; ++p)
                    samples[((size_t)c * nof_antennas + a) * nof_pols + p] =
                        sample_value(gen, tile, start_channel + c, start_antenna + a, p);

        std::vector<uint8_t> bytes(n * sizeof(uint16_t));
        std::memcpy(bytes.data(), samples.data(), bytes.size());
        return bytes;
    }

    // Build one integrated-channel data packet from an already-built payload.
    std::vector<uint8_t> make_data_packet(uint32_t counter, uint64_t timestamp,
                                          uint16_t start_channel, uint8_t nof_channels,
                                          uint8_t start_antenna, uint8_t nof_antennas,
                                          uint8_t tile_id, std::vector<uint8_t> payload)
    {
        return SpeadPacket()
            .item(0x0001, counter)                    // heap counter
            .item(0x0004, payload.size())             // payload length
            .item(0x1027, 0)                          // sync time
            .item(0x1600, timestamp)                  // timestamp
            .item(0x2004, MODE_INTEGRATED_CHANNEL)    // capture mode (slot 5)
            .item(0x2002, chan_info(start_channel, nof_channels, start_antenna, nof_antennas))
            .item(0x2001, tpm_info(tile_id))          // tile info
            .item(0x3300, 0)                          // payload offset
            .payload(std::move(payload))
            .build();
    }
} // namespace

// Exposes the protected packet path and ring-buffer push, and installs a
// capturing callback via a trampoline (DataCallbackDynamic is a bare function
// pointer, so a capturing lambda cannot be used directly).
class TestableIntegratedChannel : public IntegratedChannelisedData
{
public:
    using DataConsumer::cleanUp;
    using IntegratedChannelisedData::packetFilter;
    using IntegratedChannelisedData::processPacket;

    bool pushPacket(const std::vector<uint8_t> &pkt)
    {
        return ring_buffer->push(const_cast<uint8_t *>(pkt.data()), pkt.size());
    }

    // Push one packet and process it. Delivery is synchronous, so any callbacks
    // triggered by this packet have run by the time feed() returns.
    bool feed(const std::vector<uint8_t> &pkt)
    {
        return pushPacket(pkt) && processPacket();
    }

    // One record per callback invocation, captured in arrival order.
    struct Delivery
    {
        uint8_t               tile_id;
        uint64_t              nof_packets; // packets that landed in this tile's integration
        std::vector<uint16_t> data;        // a copy of the delivered tile buffer
    };

    // buffer_elems = nof_channels * nof_antennas * nof_pols (nof_samples == 1).
    void setCapturingCallback(size_t buffer_elems)
    {
        s_buffer_elems_ = buffer_elems;
        s_deliveries_.clear();
        setCallback(&TestableIntegratedChannel::trampoline);
    }

    static std::vector<Delivery> &deliveries() { return s_deliveries_; }

private:
    static void trampoline(void *data, double /*ts*/, void *meta)
    {
        // Copy everything out now: persist_container() clears the metadata and
        // the buffer immediately after the callback returns.
        auto *m = static_cast<ChannelMetadata *>(meta);
        auto *buf = static_cast<uint16_t *>(data); // integrated samples are uint16_t
        s_deliveries_.push_back({m->tile_id, m->nof_packets,
                                 std::vector<uint16_t>(buf, buf + s_buffer_elems_)});
    }
    static inline std::vector<Delivery> s_deliveries_;
    static inline size_t                s_buffer_elems_ = 0;
};

// ── packetFilter (accepts only integrated-channel mode 0x6) ───────────────────

TEST(IntegratedChannelFilterTest, AcceptsIntegratedChannelMode)
{
    TestableIntegratedChannel c;
    auto pkt = make_data_packet(0, 0, 0, 64, 0, 8, 0,
                                make_payload(0, 0, 0, 64, 0, 8, 2));
    EXPECT_TRUE(c.packetFilter(pkt.data()));
}

TEST(IntegratedChannelFilterTest, RejectsOtherModes)
{
    TestableIntegratedChannel c;
    for (uint64_t mode : {0x0ull, 0x4ull, 0x5ull, 0x7ull})
    {
        auto pkt = SpeadPacket()
                       .item(0x0001, 0)
                       .item(0x0004, 0)
                       .item(0x1027, 0)
                       .item(0x1600, 0)
                       .item(0x2004, mode) // slot 5: capture mode
                       .build();
        EXPECT_FALSE(c.packetFilter(pkt.data())) << "mode=" << mode;
    }
}

// ── Bandpass delivery: one callback per tile, carrying the right samples ───────
//
// The scenario the bandpass monitor runs against: 16 TPMs, coarse channels
// 0..511, each packet carrying 8 antennas. With nof_antennas=16 / 8-per-packet
// (2 antenna groups), nof_channels=512 / 64-per-packet (8 channel groups) and
// nof_pols=2, one full integration is
//     per tile  = (16/8) * (512/64) * 2         = 32 packets  (== PACKETS_PER_TILE)
//     total     = 32 * 16 tiles                 = 512 packets
// so feeding exactly 512 packets must complete the integration and deliver one
// callback for each of the 16 tiles, each carrying that tile's full spectrum.
class BandpassDeliveryTest : public ::testing::Test
{
protected:
    static constexpr int NOF_TILES = 16;
    static constexpr int NOF_CHANNELS = 512;   // coarse channels 0..511
    static constexpr int NOF_ANTENNAS = 16;    // per tile
    static constexpr int NOF_POLS = 2;
    static constexpr int ANT_PER_PKT = 8;      // 8 antennas per packet
    static constexpr int CH_PER_PKT = 64;      // -> 8 channel groups over 512
    static constexpr int NOF_ANT_GROUPS = NOF_ANTENNAS / ANT_PER_PKT; // 2
    static constexpr int NOF_CH_GROUPS = NOF_CHANNELS / CH_PER_PKT;   // 8
    static constexpr int PKTS_PER_TILE = NOF_ANT_GROUPS * NOF_CH_GROUPS * NOF_POLS; // 32
    static constexpr int PKTS_PER_INTEGRATION = PKTS_PER_TILE * NOF_TILES;          // 512
    static constexpr size_t BUFFER_ELEMS =
        (size_t)NOF_CHANNELS * NOF_ANTENNAS * NOF_POLS; // 16384 uint16_t per tile

    json config()
    {
        return json{
            {"nof_tiles", NOF_TILES},
            {"nof_channels", NOF_CHANNELS},
            {"nof_antennas", NOF_ANTENNAS},
            {"nof_pols", NOF_POLS},
            {"bitwidth", 16},
            {"sampling_time", 1.08e-6},
            {"max_packet_size", 9000},
        };
    }

    // Delivered-buffer index for a (channel, antenna, pol) sample.
    static size_t buf_index(int channel, int antenna, int pol)
    {
        return ((size_t)channel * NOF_ANTENNAS + antenna) * NOF_POLS + pol;
    }

    // Feed one complete integration (all tiles) sharing a single timestamp so it
    // is treated as one integration, with samples stamped for integration `gen`.
    // Note: the pol axis is a packet dimension here - each (antenna group, channel
    // group) is sent once per pol - so the payload spans both pols and the two
    // pol packets carry identical content, matching the consumer's
    // total_packets *= nof_pols accounting. Returns the number of packets fed.
    int feed_full_integration(TestableIntegratedChannel &c, int gen,
                              uint64_t timestamp, uint32_t &counter)
    {
        int fed = 0;
        for (int tile = 0; tile < NOF_TILES; ++tile)
            for (int ag = 0; ag < NOF_ANT_GROUPS; ++ag)
                for (int cg = 0; cg < NOF_CH_GROUPS; ++cg)
                    for (int pol = 0; pol < NOF_POLS; ++pol)
                    {
                        const uint16_t sc = (uint16_t)(cg * CH_PER_PKT);
                        const uint8_t sa = (uint8_t)(ag * ANT_PER_PKT);
                        auto pkt = make_data_packet(
                            counter++, timestamp, sc, CH_PER_PKT, sa, ANT_PER_PKT, (uint8_t)tile,
                            make_payload(gen, tile, sc, CH_PER_PKT, sa, ANT_PER_PKT, NOF_POLS));
                        EXPECT_TRUE(c.feed(pkt)) << "feed failed at tile=" << tile
                                                 << " ant_group=" << ag << " ch_group=" << cg
                                                 << " pol=" << pol;
                        ++fed;
                    }
        return fed;
    }

    // Assert one delivered buffer holds the complete, correctly-placed spectrum
    // for `tile` in integration `gen`. Stops after the first mismatch to avoid
    // flooding output.
    void expect_full_spectrum(const std::vector<uint16_t> &data, int gen, int tile)
    {
        ASSERT_EQ(data.size(), BUFFER_ELEMS) << "tile " << tile << " buffer wrong size";
        for (int ch = 0; ch < NOF_CHANNELS; ++ch)
            for (int a = 0; a < NOF_ANTENNAS; ++a)
                for (int p = 0; p < NOF_POLS; ++p)
                {
                    const uint16_t expected = sample_value(gen, tile, ch, a, p);
                    const uint16_t actual = data[buf_index(ch, a, p)];
                    ASSERT_EQ(actual, expected)
                        << "tile=" << tile << " gen=" << gen << " ch=" << ch
                        << " ant=" << a << " pol=" << p;
                }
    }
};

TEST_F(BandpassDeliveryTest, OneIntegrationFiresOneCallbackPerTile)
{
    TestableIntegratedChannel c;
    ASSERT_TRUE(c.initialiseConsumer(config()));
    c.setCapturingCallback(BUFFER_ELEMS); // after initialiseConsumer: needs the container

    uint32_t counter = 0;
    const int fed = feed_full_integration(c, /*gen=*/0, /*timestamp=*/1000, counter);
    ASSERT_EQ(fed, PKTS_PER_INTEGRATION) << "test harness fed the wrong packet count";

    c.cleanUp();

    // Exactly one callback per tile.
    auto &d = TestableIntegratedChannel::deliveries();
    ASSERT_EQ((int)d.size(), NOF_TILES) << "expected one callback per tile for a full integration";

    // Every tile 0..15 delivered exactly once, each having received a full
    // PACKETS_PER_TILE integration whose samples all land in the right slot.
    std::vector<int> per_tile(NOF_TILES, 0);
    for (const auto &del : d)
    {
        ASSERT_LT(del.tile_id, NOF_TILES) << "callback reported an out-of-range tile id";
        per_tile[del.tile_id]++;
        EXPECT_EQ(del.nof_packets, (uint64_t)PKTS_PER_TILE)
            << "tile " << (int)del.tile_id << " delivered a partial integration";
        expect_full_spectrum(del.data, /*gen=*/0, del.tile_id);
    }
    for (int tile = 0; tile < NOF_TILES; ++tile)
        EXPECT_EQ(per_tile[tile], 1) << "tile " << tile << " was not delivered exactly once";
}

TEST_F(BandpassDeliveryTest, BackToBackIntegrationsFirePerTileEachTime)
{
    TestableIntegratedChannel c;
    ASSERT_TRUE(c.initialiseConsumer(config()));
    c.setCapturingCallback(BUFFER_ELEMS);
    auto &d = TestableIntegratedChannel::deliveries();

    // First integration (gen 0): delivered when its 512th packet completes it,
    // which also resets the consumer for the next integration.
    uint32_t counter = 0;
    feed_full_integration(c, /*gen=*/0, /*timestamp=*/1000, counter);

    ASSERT_EQ((int)d.size(), NOF_TILES) << "first integration: expected one callback per tile";
    for (const auto &del : d)
        expect_full_spectrum(del.data, /*gen=*/0, del.tile_id);

    // Second integration (gen 1): distinct samples and a distinct, advancing
    // timestamp. Its buffers must carry gen-1 data, proving nothing leaked from
    // the first integration.
    d.clear();
    feed_full_integration(c, /*gen=*/1, /*timestamp=*/2000, counter);

    ASSERT_EQ((int)d.size(), NOF_TILES) << "second integration: expected one callback per tile";
    std::vector<int> per_tile(NOF_TILES, 0);
    for (const auto &del : d)
    {
        ASSERT_LT(del.tile_id, NOF_TILES);
        per_tile[del.tile_id]++;
        EXPECT_EQ(del.nof_packets, (uint64_t)PKTS_PER_TILE);
        expect_full_spectrum(del.data, /*gen=*/1, del.tile_id);
    }
    for (int tile = 0; tile < NOF_TILES; ++tile)
        EXPECT_EQ(per_tile[tile], 1) << "tile " << tile << " not delivered in second integration";
}

// An incomplete integration (one packet short of total_packets) is not yet
// delivered: with no completion and no flush, the callback must not fire.
TEST_F(BandpassDeliveryTest, IncompleteIntegrationDoesNotFire)
{
    TestableIntegratedChannel c;
    ASSERT_TRUE(c.initialiseConsumer(config()));
    c.setCapturingCallback(BUFFER_ELEMS);

    // Feed one short of a full integration: (512 - 1) packets. total_packets is
    // never reached so persist_container() is not invoked.
    uint32_t counter = 0;
    int fed = 0;
    for (int tile = 0; tile < NOF_TILES && fed < PKTS_PER_INTEGRATION - 1; ++tile)
        for (int ag = 0; ag < NOF_ANT_GROUPS && fed < PKTS_PER_INTEGRATION - 1; ++ag)
            for (int cg = 0; cg < NOF_CH_GROUPS && fed < PKTS_PER_INTEGRATION - 1; ++cg)
                for (int pol = 0; pol < NOF_POLS && fed < PKTS_PER_INTEGRATION - 1; ++pol)
                {
                    const uint16_t sc = (uint16_t)(cg * CH_PER_PKT);
                    const uint8_t sa = (uint8_t)(ag * ANT_PER_PKT);
                    auto pkt = make_data_packet(
                        counter++, /*timestamp=*/1000, sc, CH_PER_PKT, sa, ANT_PER_PKT, (uint8_t)tile,
                        make_payload(0, tile, sc, CH_PER_PKT, sa, ANT_PER_PKT, NOF_POLS));
                    ASSERT_TRUE(c.feed(pkt));
                    ++fed;
                }
    ASSERT_EQ(fed, PKTS_PER_INTEGRATION - 1);

    c.cleanUp();

    EXPECT_TRUE(TestableIntegratedChannel::deliveries().empty())
        << "an incomplete integration must not fire the callback";
}

// A tile that received fewer than PACKETS_PER_TILE packets when an integration is
// flushed must be excluded: persist_container() only fires the callback for tiles
// that reached the threshold.
//
// The expected count is hardcoded to the firmware fact ("a complete integration is
// 32 packets per TPM") rather than read from the constant, deliberately: feeding
// 32 and 31 packets, exactly one tile clears a threshold of 32, but *two* clear a
// lowered threshold and *none* clear a raised one - so a change to PACKETS_PER_TILE
// is caught here.
//
// The flush is driven the way a dropped packet triggers it in production: a packet
// from a later integration (timestamp beyond integration_lookahead_cutoff) arrives
// before total_packets is reached, forcing the partial set to be persisted.
TEST_F(BandpassDeliveryTest, TileBelowPacketThresholdIsExcluded)
{
    constexpr int EXPECTED_PACKETS_PER_TILE = 32; // firmware: 32 packets complete a TPM integration
    constexpr int FULL_TILE = 3;      // gets EXPECTED_PACKETS_PER_TILE     -> should fire
    constexpr int SHORT_TILE = 7;     // gets one packet short              -> excluded
    constexpr int TRIGGER_TILE = 11;  // only carries the flush-triggering packet
    constexpr double LOOKAHEAD = 0.5; // seconds

    json cfg = config();
    cfg["integration_lookahead_cutoff"] = LOOKAHEAD;

    TestableIntegratedChannel c;
    ASSERT_TRUE(c.initialiseConsumer(cfg));
    c.setCapturingCallback(BUFFER_ELEMS);

    // Feed n packets to one tile, all in the same integration (shared timestamp).
    uint32_t counter = 0;
    auto feed_tile = [&](int tile, int n, uint64_t timestamp)
    {
        for (int i = 0; i < n; ++i)
        {
            const uint16_t sc = (uint16_t)((i % NOF_CH_GROUPS) * CH_PER_PKT);
            auto pkt = make_data_packet(
                counter++, timestamp, sc, CH_PER_PKT, /*start_antenna=*/0, ANT_PER_PKT, (uint8_t)tile,
                make_payload(0, tile, sc, CH_PER_PKT, 0, ANT_PER_PKT, NOF_POLS));
            ASSERT_TRUE(c.feed(pkt));
        }
    };

    const uint64_t t0 = 1000;
    feed_tile(FULL_TILE, EXPECTED_PACKETS_PER_TILE, t0);
    feed_tile(SHORT_TILE, EXPECTED_PACKETS_PER_TILE - 1, t0);

    // Nothing delivered yet: the integration is incomplete (total_packets not hit)
    // and no flush has been triggered.
    ASSERT_TRUE(TestableIntegratedChannel::deliveries().empty());

    // A packet from a later integration, > LOOKAHEAD seconds ahead, forces the
    // partial set to be flushed. packet_time = timestamp * sampling_time (1.08e-6),
    // so a 1e6-count jump is ~1.08 s, comfortably past the 0.5 s cutoff.
    const uint64_t t1 = t0 + 1000000;
    auto trigger = make_data_packet(
        counter++, t1, /*start_channel=*/0, CH_PER_PKT, /*start_antenna=*/0, ANT_PER_PKT,
        (uint8_t)TRIGGER_TILE, make_payload(1, TRIGGER_TILE, 0, CH_PER_PKT, 0, ANT_PER_PKT, NOF_POLS));
    ASSERT_TRUE(c.feed(trigger));

    c.cleanUp();

    // Exactly the tile that reached the threshold was delivered; the short tile
    // (and the trigger tile, still mid-integration) were not.
    const auto &d = TestableIntegratedChannel::deliveries();
    ASSERT_EQ((int)d.size(), 1) << "only the tile at/above PACKETS_PER_TILE should be delivered";
    EXPECT_EQ((int)d[0].tile_id, FULL_TILE);
    EXPECT_EQ(d[0].nof_packets, (uint64_t)EXPECTED_PACKETS_PER_TILE);
}
