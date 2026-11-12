// Raw antenna data consumer tests (RawData.cpp, class RawData).
//
// The raw consumer reassembles a burst of raw ADC samples per tile in an
// AntennaDataContainer and calls the registered callback once per tile when a
// full buffer has arrived (nof_tiles * nof_antennas * samples_per_buffer
// samples) or the stream ends.
//
// ── Packet layouts ───────────────────────────────────────────────────────────
// Burst (mode 0): one antenna per packet. The payload is [sample][pol] for that
// antenna, and the sample offset is (packet_counter * samples_in_packet) modulo
// samples_per_buffer. The counter runs over all antennas of an FPGA, so antenna
// a's k-th packet has counter a_local * packets_per_antenna + k.
// Synchronised (mode 1): several antennas per packet, payload
// [sample][antenna][pol].
//
// ── Delivered buffer layout ──────────────────────────────────────────────────
// One tile's buffer, [antenna][sample][pol] of 8-bit or 16-bit samples
// (configuration key "bitwidth").

#include <cstdint>
#include <cstring>
#include <gtest/gtest.h>
#include <vector>

#include "RawData.h"
#include "spead_test_util.h"

namespace
{
    // A deterministic sample value for a (tile, antenna, sample, pol)
    // coordinate. Compared after truncation to the sample width, so wrapping is
    // harmless; with 16-bit samples it also uses the high byte, so a consumer
    // that copies only one byte per sample fails.
    int32_t sample_value(size_t tile, size_t antenna, size_t sample, size_t pol)
    {
        return (int32_t)(tile * 7919 + antenna * 263 + sample * 3 + pol) - 20000;
    }

    // Item 0x2000 (antenna info): bits[15:8] = start antenna, [7:0] = count.
    uint64_t antenna_info(uint8_t start_antenna, uint8_t nof_antennas)
    {
        return ((uint64_t)start_antenna << 8) | nof_antennas;
    }

    // Item 0x2001 (tile info): tile_id at bits[39:32], station at [31:16],
    // fpga_id at [7:0].
    uint64_t tpm_info(uint8_t tile_id, uint16_t station_id, uint8_t fpga_id)
    {
        return ((uint64_t)tile_id << 32) | ((uint64_t)station_id << 16) | fpga_id;
    }

    // Payload [sample][antenna][pol] for antennas start..start+nof_antennas-1
    // and samples first_sample.., as bytes of the given bitwidth.
    std::vector<uint8_t> make_payload(int bitwidth, size_t tile, size_t start_antenna,
                                      size_t nof_antennas, size_t first_sample,
                                      size_t nof_samples, size_t nof_pols)
    {
        const size_t bytes_per_sample = bitwidth / 8;
        std::vector<uint8_t> bytes(nof_samples * nof_antennas * nof_pols * bytes_per_sample);
        size_t i = 0;
        for (size_t s = 0; s < nof_samples; ++s)
            for (size_t a = 0; a < nof_antennas; ++a)
                for (size_t p = 0; p < nof_pols; ++p, ++i)
                {
                    int32_t v = sample_value(tile, start_antenna + a, first_sample + s, p);
                    if (bitwidth == 16)
                    {
                        int16_t v16 = (int16_t)v;
                        std::memcpy(&bytes[i * 2], &v16, 2);
                    }
                    else
                        bytes[i] = (uint8_t)(int8_t)v;
                }
        return bytes;
    }

    std::vector<uint8_t> make_packet(uint64_t mode, uint32_t counter, uint64_t sync_time,
                                     uint64_t timestamp, uint8_t start_antenna,
                                     uint8_t nof_antennas, uint8_t tile_id, uint8_t fpga_id,
                                     std::vector<uint8_t> payload)
    {
        // Item order as sent by the iTPM firmware
        return SpeadPacket()
            .item(0x0001, counter)
            .item(0x0004, payload.size())
            .item(0x1027, sync_time)
            .item(0x1600, timestamp)
            .item(0x2004, mode)
            .item(0x2000, antenna_info(start_antenna, nof_antennas))
            .item(0x2001, tpm_info(tile_id, 3, fpga_id))
            .item(0x3300, 0)
            .payload(std::move(payload))
            .build();
    }
} // namespace

// Exposes the protected packet path and captures callbacks through a
// trampoline (DataCallbackDynamic is a bare function pointer).
class TestableRawData : public RawData
{
public:
    using RawData::cleanUp;
    using RawData::onStreamEnd;
    using RawData::packetFilter;
    using RawData::processPacket;

    bool feed(const std::vector<uint8_t> &pkt)
    {
        return ring_buffer->push(const_cast<uint8_t *>(pkt.data()), pkt.size()) &&
               processPacket();
    }

    struct Delivery
    {
        uint8_t              tile_id;
        uint16_t             station_id;
        double               timestamp;
        std::vector<int32_t> data; // samples widened to int32
    };

    void setCapturingCallback(size_t buffer_elems, int bitwidth)
    {
        s_buffer_elems_ = buffer_elems;
        s_bitwidth_ = bitwidth;
        s_deliveries_.clear();
        setCallback(&TestableRawData::trampoline);
    }

    static std::vector<Delivery> &deliveries() { return s_deliveries_; }

private:
    static void trampoline(void *data, double timestamp, void *meta)
    {
        // The metadata layout does not depend on the sample type
        auto *m = static_cast<AntennaDataContainer<uint8_t>::AdcMetadata *>(meta);
        std::vector<int32_t> values(s_buffer_elems_);
        for (size_t i = 0; i < s_buffer_elems_; ++i)
            values[i] = s_bitwidth_ == 16 ? static_cast<int16_t *>(data)[i]
                                          : static_cast<int8_t *>(data)[i];
        s_deliveries_.push_back({m->tile_id, m->station_id, timestamp, std::move(values)});
    }
    static inline std::vector<Delivery> s_deliveries_;
    static inline size_t                s_buffer_elems_ = 0;
    static inline int                   s_bitwidth_ = 8;
};

// ── packetFilter: accepts raw (0) and synchronised raw (1) only ───────────────

TEST(RawDataFilterTest, AcceptsOnlyRawModes)
{
    TestableRawData c;
    for (uint64_t mode : {0x0ull, 0x1ull, 0x4ull, 0x6ull, 0x7ull})
    {
        auto pkt = make_packet(mode, 0, 0, 0, 0, 1, 0, 0, make_payload(8, 0, 0, 1, 0, 16, 1));
        EXPECT_EQ(c.packetFilter(pkt.data()), mode <= 1) << "mode=" << mode;
    }
}

// ── initialiseConsumer ───────────────────────────────────────────────────────

// Without an attached logger LOG(FATAL) exits the process, so these tests
// attach one, as pydaq does.
class RawDataConfigTest : public ::testing::Test
{
protected:
    void SetUp() override { attachLogger([](int, const char *) {}); }
    void TearDown() override { attachLogger(nullptr); }
};

TEST_F(RawDataConfigTest, RejectsMissingKey)
{
    TestableRawData c;
    // nof_antennas present, samples_per_buffer missing
    EXPECT_FALSE(c.initialiseConsumer(json{{"nof_antennas", 16}, {"nof_tiles", 1},
                                           {"nof_pols", 2}, {"max_packet_size", 9000}}));
}

TEST_F(RawDataConfigTest, RejectsUnsupportedBitwidth)
{
    TestableRawData c;
    EXPECT_FALSE(c.initialiseConsumer(json{{"nof_antennas", 16}, {"samples_per_buffer", 64},
                                           {"nof_tiles", 1}, {"nof_pols", 2},
                                           {"max_packet_size", 9000}, {"bitwidth", 12}}));
}

// ── Delivery, parametrised on (bitwidth, nof_pols) ─────────────────────────────
//
// Two tiles of two FPGAs, each FPGA sending half of the tile's antennas, as the
// iTPM does.
class RawDataDeliveryTest : public ::testing::TestWithParam<std::tuple<int, int>>
{
protected:
    static constexpr size_t NOF_TILES = 2;
    static constexpr size_t NOF_FPGAS = 2;
    static constexpr size_t SAMPLES = 64;          // samples per antenna per buffer
    static constexpr uint64_t SYNC_TIME = 1000;
    static constexpr uint64_t TIMESTAMP = 5000;
    static constexpr double SAMPLING_TIME = 6.912e-5;

    int bitwidth() const { return std::get<0>(GetParam()); }
    size_t nof_pols() const { return std::get<1>(GetParam()); }
    // 32 single-pol signals (BIRALES) or 16 dual-pol antennas (SKA)
    size_t nof_antennas() const { return nof_pols() == 1 ? 32 : 16; }
    size_t antennas_per_fpga() const { return nof_antennas() / NOF_FPGAS; }
    size_t buffer_elems() const { return nof_antennas() * SAMPLES * nof_pols(); }

    void init(TestableRawData &c)
    {
        ASSERT_TRUE(c.initialiseConsumer(json{
            {"nof_antennas", nof_antennas()}, {"samples_per_buffer", SAMPLES},
            {"nof_tiles", NOF_TILES}, {"nof_pols", nof_pols()},
            {"max_packet_size", 9000}, {"bitwidth", bitwidth()},
            {"sampling_time", SAMPLING_TIME}}));
        c.setCapturingCallback(buffer_elems(), bitwidth());
    }

    void check_deliveries()
    {
        auto &d = TestableRawData::deliveries();
        ASSERT_EQ(d.size(), NOF_TILES);
        for (size_t t = 0; t < NOF_TILES; ++t)
        {
            EXPECT_EQ(d[t].tile_id, t);
            EXPECT_EQ(d[t].station_id, 3);
            EXPECT_DOUBLE_EQ(d[t].timestamp, SYNC_TIME + TIMESTAMP * SAMPLING_TIME);
            size_t mismatches = 0;
            for (size_t a = 0; a < nof_antennas(); ++a)
                for (size_t s = 0; s < SAMPLES; ++s)
                    for (size_t p = 0; p < nof_pols(); ++p)
                    {
                        int32_t expected = sample_value(t, a, s, p);
                        expected = bitwidth() == 16 ? (int16_t)expected : (int8_t)expected;
                        size_t idx = (a * SAMPLES + s) * nof_pols() + p;
                        if (d[t].data[idx] != expected && mismatches++ < 5)
                            ADD_FAILURE() << "tile " << t << " antenna " << a << " sample " << s
                                          << " pol " << p << ": got " << d[t].data[idx]
                                          << ", expected " << expected;
                    }
            EXPECT_EQ(mismatches, 0u);
        }
    }
};

// Burst mode: one antenna per packet, 16 samples per packet. The buffer is
// complete after the last packet, so the callbacks fire without onStreamEnd.
TEST_P(RawDataDeliveryTest, BurstOneAntennaPerPacket)
{
    TestableRawData c;
    init(c);
    constexpr size_t SAMPLES_PER_PKT = 16;
    constexpr size_t PKTS_PER_ANT = SAMPLES / SAMPLES_PER_PKT;
    for (size_t t = 0; t < NOF_TILES; ++t)
        for (size_t f = 0; f < NOF_FPGAS; ++f)
            for (size_t al = 0; al < antennas_per_fpga(); ++al)
                for (size_t k = 0; k < PKTS_PER_ANT; ++k)
                {
                    size_t a = f * antennas_per_fpga() + al;
                    ASSERT_TRUE(c.feed(make_packet(
                        0, al * PKTS_PER_ANT + k, SYNC_TIME, TIMESTAMP + k, a, 1, t, f,
                        make_payload(bitwidth(), t, a, 1, k * SAMPLES_PER_PKT,
                                     SAMPLES_PER_PKT, nof_pols()))));
                }
    check_deliveries();
    c.cleanUp();
}

// Synchronised mode: all antennas of an FPGA in each packet, 4 samples per
// packet.
TEST_P(RawDataDeliveryTest, SynchronisedAllAntennasPerPacket)
{
    TestableRawData c;
    init(c);
    constexpr size_t SAMPLES_PER_PKT = 4;
    for (size_t t = 0; t < NOF_TILES; ++t)
        for (size_t f = 0; f < NOF_FPGAS; ++f)
            for (size_t k = 0; k < SAMPLES / SAMPLES_PER_PKT; ++k)
            {
                size_t a0 = f * antennas_per_fpga();
                ASSERT_TRUE(c.feed(make_packet(
                    1, k, SYNC_TIME, TIMESTAMP, a0, antennas_per_fpga(), t, f,
                    make_payload(bitwidth(), t, a0, antennas_per_fpga(), k * SAMPLES_PER_PKT,
                                 SAMPLES_PER_PKT, nof_pols()))));
            }
    check_deliveries();
    c.cleanUp();
}

// A packet for antennas outside the configured range is dropped, not written
// past the end of the buffer.
TEST_P(RawDataDeliveryTest, DropsAntennasOutOfRange)
{
    TestableRawData c;
    init(c);
    ASSERT_TRUE(c.feed(make_packet(0, 0, SYNC_TIME, TIMESTAMP, nof_antennas(), 1, 0, 0,
                                   make_payload(bitwidth(), 0, nof_antennas(), 1, 0, 16,
                                                nof_pols()))));
    c.onStreamEnd();
    // The tile was registered but received no samples in range, so its buffer
    // is still empty and nothing is delivered.
    EXPECT_TRUE(TestableRawData::deliveries().empty());
    c.cleanUp();
}

// Dropped packets do not count towards a full buffer. A synchronised stream
// with a dropped packet of the same size in the middle (antennas out of range,
// then a tile beyond nof_tiles) is delivered once, complete, after its last
// valid packet; counting the dropped packets would save a partial buffer early.
TEST_P(RawDataDeliveryTest, DroppedPacketsDoNotCompleteBuffer)
{
    TestableRawData c;
    init(c);
    constexpr size_t SAMPLES_PER_PKT = 4;
    const size_t nof_pkts = SAMPLES / SAMPLES_PER_PKT;
    for (size_t t = 0; t < NOF_TILES; ++t)
        for (size_t f = 0; f < NOF_FPGAS; ++f)
            for (size_t k = 0; k < nof_pkts; ++k)
            {
                size_t a0 = f * antennas_per_fpga();
                ASSERT_TRUE(c.feed(make_packet(
                    1, k, SYNC_TIME, TIMESTAMP, a0, antennas_per_fpga(), t, f,
                    make_payload(bitwidth(), t, a0, antennas_per_fpga(), k * SAMPLES_PER_PKT,
                                 SAMPLES_PER_PKT, nof_pols()))));
                if (k != 0 || f != 0)
                    continue;
                // After tile 0's first packet: antennas past the configured range
                if (t == 0)
                    ASSERT_TRUE(c.feed(make_packet(
                        1, 1, SYNC_TIME, TIMESTAMP, nof_antennas(), antennas_per_fpga(), 0, 0,
                        make_payload(bitwidth(), 0, nof_antennas(), antennas_per_fpga(),
                                     SAMPLES_PER_PKT, SAMPLES_PER_PKT, nof_pols()))));
                // After tile 1's first packet (both tiles now mapped): a third tile
                else
                    ASSERT_TRUE(c.feed(make_packet(
                        1, 1, SYNC_TIME, TIMESTAMP, 0, antennas_per_fpga(), NOF_TILES, 0,
                        make_payload(bitwidth(), NOF_TILES, 0, antennas_per_fpga(),
                                     SAMPLES_PER_PKT, SAMPLES_PER_PKT, nof_pols()))));
            }
    check_deliveries();
    c.cleanUp();
}

INSTANTIATE_TEST_SUITE_P(BitwidthAndPols, RawDataDeliveryTest,
                         ::testing::Combine(::testing::Values(8, 16), ::testing::Values(1, 2)),
                         [](const auto &info) {
                             return std::to_string(std::get<0>(info.param)) + "bit_" +
                                    std::to_string(std::get<1>(info.param)) + "pol";
                         });
