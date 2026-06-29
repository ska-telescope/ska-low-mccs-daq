// Unit tests for the antenna-buffer DAQ mode (AntennaBuffer.h).
//
// Exercises AntennaBufferDataContainer<T> against the REAL aavs-daq library
// (DAQ.h, LOG, allocate_aligned), not a stub. Packet payloads are laid out
// per-FPGA (each FPGA owns half the antennas) in blocks of four samples.

#include <gtest/gtest.h>
#include <cstring>
#include <vector>

#include "AntennaBuffer.h"

using Container = AntennaBufferDataContainer<uint8_t>;

// ── Constants ──────────────────────────────────────────────────────────────

static constexpr uint16_t NOF_TILES   = 1;
static constexpr uint16_t NOF_ANT     = 4;   // -> antennas_per_fpga = 2
static constexpr uint32_t NOF_SAMPLES = 8;
static constexpr uint8_t  NOF_POLS    = 2;
static constexpr uint16_t ANT_PER_FPGA = NOF_ANT / 2;
static constexpr size_t   TILE_BYTES  = NOF_ANT * NOF_POLS * NOF_SAMPLES;

// Per-antenna stride in the destination buffer ([antenna][sample][pol]) — the
// full antenna row, sized for all NOF_SAMPLES.
static constexpr size_t ANT_STRIDE = NOF_SAMPLES * NOF_POLS;
// Bytes a single 4-sample packet writes for one antenna (only part of the row).
static constexpr size_t PACKET_PER_ANT = 4 * NOF_POLS;

// ── Callback capture ─────────────────────────────────────────────────────────

namespace {
// We copy out individual metadata fields rather than the whole struct:
// AntennaBufferMetadata default-member-initialises its arrays with `= 0`, which
// only the test would ever instantiate, so we avoid constructing one.
struct Capture {
    int                  calls = 0;
    std::vector<uint8_t> data;
    double               timestamp = 0.0;
    uint64_t             nof_packets = 0;
    uint32_t             packet_counter[2] = {0, 0};
};
Capture g_capture;

void capturing_callback(void *data, double timestamp, void *userdata)
{
    const auto *meta = static_cast<const Container::AntennaBufferMetadata *>(userdata);
    g_capture.calls++;
    g_capture.timestamp = timestamp;
    g_capture.nof_packets = meta->nof_packets;
    g_capture.packet_counter[0] = meta->packet_counter[0];
    g_capture.packet_counter[1] = meta->packet_counter[1];
    auto *p = static_cast<uint8_t *>(data);
    g_capture.data.assign(p, p + TILE_BYTES);
}
}  // namespace

// ── Fixture & helper ─────────────────────────────────────────────────────────

class AntennaBufferTest : public ::testing::Test {
protected:
    void SetUp() override { g_capture = Capture{}; }
    Container c_{NOF_TILES, NOF_ANT, NOF_SAMPLES, NOF_POLS};
};

static void add(Container &c, uint16_t tile, uint8_t fpga_id,
                uint32_t start_sample, uint32_t samples, uint8_t *data,
                double timestamp, uint32_t packet_counter = 0)
{
    c.add_data(packet_counter, /*payload_length=*/0, /*sync_time=*/0,
               /*timestamp_field=*/0, /*station_id=*/0, /*payload_offset=*/0,
               /*antenna_0_id=*/0, /*antenna_1_id=*/1, /*antenna_2_id=*/2,
               /*antenna_3_id=*/3, /*nof_included_antennas=*/ANT_PER_FPGA, data,
               tile, start_sample, samples, timestamp, fpga_id);
}

// Build a payload of `samples` for the two antennas an FPGA owns, laid out as
// blocks of four samples: [block][antenna_in_fpga][4 samples][pol].
static std::vector<uint8_t> make_payload(uint32_t samples)
{
    std::vector<uint8_t> p(ANT_PER_FPGA * samples * NOF_POLS);
    for (size_t i = 0; i < p.size(); ++i)
        p[i] = static_cast<uint8_t>(i + 1);  // 1, 2, 3, ...
    return p;
}

// ── FPGA selects the antenna half ────────────────────────────────────────────

TEST_F(AntennaBufferTest, Fpga0LandsInFirstAntennaHalf)
{
    auto payload = make_payload(/*samples=*/4);  // one 4-sample block
    add(c_, /*tile=*/0, /*fpga_id=*/0, /*start_sample=*/0, /*samples=*/4,
        payload.data(), 1.0);

    c_.setCallback(capturing_callback);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);

    // Antenna 0 gets payload[0..7], antenna 1 gets payload[8..15] — each lands
    // at the start of its (longer) antenna row; the rest of the row stays zero.
    for (size_t k = 0; k < PACKET_PER_ANT; ++k) {
        EXPECT_EQ(g_capture.data[0 * ANT_STRIDE + k], payload[0 * PACKET_PER_ANT + k]);
        EXPECT_EQ(g_capture.data[1 * ANT_STRIDE + k], payload[1 * PACKET_PER_ANT + k]);
    }
    EXPECT_EQ(g_capture.data[0 * ANT_STRIDE + PACKET_PER_ANT], 0u);  // unwritten tail
    // The other FPGA's antennas (2, 3) stay zero.
    EXPECT_EQ(g_capture.data[2 * ANT_STRIDE], 0u);
    EXPECT_EQ(g_capture.data[3 * ANT_STRIDE], 0u);
}

TEST_F(AntennaBufferTest, Fpga1LandsInSecondAntennaHalf)
{
    auto payload = make_payload(4);
    add(c_, /*tile=*/0, /*fpga_id=*/1, /*start_sample=*/0, /*samples=*/4,
        payload.data(), 1.0);

    c_.setCallback(capturing_callback);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);

    // fpga_id 1 -> antennas 2 and 3.
    for (size_t k = 0; k < PACKET_PER_ANT; ++k) {
        EXPECT_EQ(g_capture.data[2 * ANT_STRIDE + k], payload[0 * PACKET_PER_ANT + k]);
        EXPECT_EQ(g_capture.data[3 * ANT_STRIDE + k], payload[1 * PACKET_PER_ANT + k]);
    }
    EXPECT_EQ(g_capture.data[0 * ANT_STRIDE], 0u);
}

// ── Multi-block (samples spanning two 4-sample groups) ───────────────────────

TEST_F(AntennaBufferTest, MultipleSampleBlocksAreContiguousPerAntenna)
{
    auto payload = make_payload(/*samples=*/NOF_SAMPLES);  // 8 samples = two blocks
    add(c_, 0, /*fpga_id=*/0, /*start_sample=*/0, /*samples=*/NOF_SAMPLES,
        payload.data(), 1.0);

    c_.setCallback(capturing_callback);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);

    // Antenna 0 occupies the whole first ANT_STRIDE bytes, drawn from the two
    // blocks of the payload that belong to antenna 0.
    // Block b, antenna a source offset = (b*4*ANT_PER_FPGA + a*4) * NOF_POLS.
    for (uint32_t b = 0; b < NOF_SAMPLES / 4; ++b) {
        const size_t src = (b * 4 * ANT_PER_FPGA + 0 * 4) * NOF_POLS;
        const size_t dst = b * 4 * NOF_POLS;  // antenna 0 base + block offset
        for (size_t k = 0; k < 4u * NOF_POLS; ++k)
            EXPECT_EQ(g_capture.data[dst + k], payload[src + k])
                << "block=" << b << " k=" << k;
    }
}

// ── Tile capacity guard ──────────────────────────────────────────────────────

TEST_F(AntennaBufferTest, TileBeyondCapacityIsDroppedSafely)
{
    auto payload = make_payload(4);
    add(c_, /*tile=*/0, 0, 0, 4, payload.data(), 1.0);   // fills the single slot
    add(c_, /*tile=*/9, 0, 0, 4, payload.data(), 1.0);   // dropped: map full

    c_.setCallback(capturing_callback);
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, NOF_TILES);
}

// ── Metadata & timestamp ─────────────────────────────────────────────────────

TEST_F(AntennaBufferTest, MetadataCountsPackets)
{
    auto payload = make_payload(4);
    add(c_, 0, 0, 0, 4, payload.data(), 1.0, /*packet_counter=*/11);
    add(c_, 0, 0, 4, 4, payload.data(), 1.0, /*packet_counter=*/12);

    c_.setCallback(capturing_callback);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.nof_packets, 2u);
    EXPECT_EQ(g_capture.packet_counter[0], 11u);
    EXPECT_EQ(g_capture.packet_counter[1], 12u);
}

TEST_F(AntennaBufferTest, TimestampKeepsEarliest)
{
    auto payload = make_payload(4);
    add(c_, 0, 0, 0, 4, payload.data(), /*timestamp=*/8.0);
    add(c_, 0, 0, 4, 4, payload.data(), /*timestamp=*/2.0);

    c_.setCallback(capturing_callback);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_DOUBLE_EQ(g_capture.timestamp, 2.0);
}

// ── clear / no-callback safety ───────────────────────────────────────────────

TEST_F(AntennaBufferTest, PersistWithoutCallbackDoesNotCrashAndClears)
{
    auto payload = make_payload(4);
    add(c_, 0, 0, 0, 4, payload.data(), 1.0);
    c_.persist_container();  // no callback: warns + clears

    c_.setCallback(capturing_callback);
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, 0);
}

TEST_F(AntennaBufferTest, PersistClearsBetweenIntegrations)
{
    auto payload = make_payload(4);
    c_.setCallback(capturing_callback);
    add(c_, 0, 0, 0, 4, payload.data(), 1.0);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);

    c_.persist_container();  // empty integration
    EXPECT_EQ(g_capture.calls, 1);
}
