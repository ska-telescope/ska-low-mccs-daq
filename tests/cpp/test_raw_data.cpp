// Unit tests for the raw-antenna DAQ mode (RawData.h).
//
// These exercise AntennaDataContainer<T> — the buffer that backs the
// `rawdata` consumer — against the REAL aavs-daq library (DAQ.h, LOG, etc.),
// not a stub. The container owns all of the de-interleaving, tile-mapping,
// metadata and callback logic, so it is the natural unit to test.

#include <gtest/gtest.h>
#include <cstring>
#include <vector>

#include "RawData.h"

using Container = AntennaDataContainer<uint8_t>;
using AdcMetadata = Container::AdcMetadata;

// ── Callback capture ───────────────────────────────────────────────────────
// DataCallbackDynamic is a plain C function pointer, so we route captures
// through a file-scope sink that each test resets in SetUp().

// ── Constants ──────────────────────────────────────────────────────────────

static constexpr uint16_t NOF_TILES   = 2;
static constexpr uint16_t NOF_ANT     = 4;
static constexpr uint32_t NOF_SAMPLES = 8;
static constexpr uint8_t  NOF_POLS    = 2;
static constexpr size_t   TILE_BYTES  = NOF_ANT * NOF_SAMPLES * NOF_POLS;

namespace {
struct Capture {
    int                  calls = 0;
    std::vector<uint8_t> data;   // copied during the callback (see note below)
    double               timestamp = 0.0;
    AdcMetadata          meta{};
};
Capture g_capture;

// persist_container() invokes the callback and then immediately clear()s the
// buffer, so the test must snapshot the bytes *inside* the callback rather than
// holding the pointer.
void capturing_callback(void *data, double timestamp, void *userdata)
{
    g_capture.calls++;
    g_capture.timestamp = timestamp;
    g_capture.meta = *static_cast<AdcMetadata *>(userdata);
    g_capture.data.assign(static_cast<uint8_t *>(data),
                          static_cast<uint8_t *>(data) + TILE_BYTES);
}
}  // namespace

// ── Fixture ────────────────────────────────────────────────────────────────

class RawDataTest : public ::testing::Test {
protected:
    void SetUp() override { g_capture = Capture{}; }

    Container c_{NOF_TILES, NOF_ANT, NOF_SAMPLES, NOF_POLS};
};

// Convenience wrapper around the (very wide) add_data signature so the tests
// read cleanly. Only the fields a test cares about are passed positionally.
static void add_burst(Container &c, uint8_t tile, uint8_t start_antenna,
                      uint32_t start_sample, uint32_t nsamp, uint8_t *data,
                      double timestamp, uint32_t packet_counter = 0)
{
    c.add_data(packet_counter, /*payload_length=*/nsamp * NOF_POLS,
               /*sync_time=*/0, /*timestamp_field=*/0, /*station_id=*/0,
               /*fpga_id=*/0, /*payload_offset=*/0, tile, start_antenna,
               start_sample, nsamp, /*nof_included_antennas=*/1, data, timestamp);
}

// ── Burst layout: one antenna per packet ─────────────────────────────────────

TEST_F(RawDataTest, BurstWriteLandsAtAntennaAndSampleOffset)
{
    // Single antenna 1, starting at sample 2, two samples (= 4 values w/ pols).
    std::vector<uint8_t> payload = {0x11, 0x22, 0x33, 0x44};
    add_burst(c_, /*tile=*/0, /*start_antenna=*/1, /*start_sample=*/2,
              /*nsamp=*/2, payload.data(), 1.0);

    c_.setCallback(capturing_callback);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    const auto *buf = g_capture.data.data();

    // Layout per tile is [antenna][sample][pol]. Offset for ant 1, sample 2:
    //   1 * NOF_SAMPLES * NOF_POLS + 2 * NOF_POLS = 16 + 4 = 20.
    const size_t offset = 1u * NOF_SAMPLES * NOF_POLS + 2u * NOF_POLS;
    EXPECT_EQ(buf[offset + 0], 0x11);
    EXPECT_EQ(buf[offset + 1], 0x22);
    EXPECT_EQ(buf[offset + 2], 0x33);
    EXPECT_EQ(buf[offset + 3], 0x44);

    // Untouched antenna 0 stays zero.
    EXPECT_EQ(buf[0], 0u);
}

// ── Synchronised layout: de-interleave multiple antennas ─────────────────────

TEST_F(RawDataTest, SynchronisedWriteDeinterleavesAntennas)
{
    // Source is [sample][antenna][pol] interleaved; 2 antennas, 2 samples.
    // Encode each value as antenna*10 + sample*2 + pol so we can read it back.
    constexpr uint8_t A = 2, S = 2;
    std::vector<uint8_t> src(S * A * NOF_POLS);
    for (uint8_t s = 0; s < S; ++s)
        for (uint8_t a = 0; a < A; ++a)
            for (uint8_t p = 0; p < NOF_POLS; ++p)
                src[s * A * NOF_POLS + a * NOF_POLS + p] = a * 10 + s * 2 + p;

    c_.add_data(/*packet_counter=*/0, /*payload_length=*/0, /*sync_time=*/0,
                /*timestamp_field=*/0, /*station_id=*/0, /*fpga_id=*/0,
                /*payload_offset=*/0, /*tile=*/0, /*start_antenna=*/0,
                /*start_sample_index=*/0, /*nsamp=*/S, /*nof_included_antennas=*/A,
                src.data(), 1.0);

    c_.setCallback(capturing_callback);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);
    const auto *buf = g_capture.data.data();

    // Destination layout [antenna][sample][pol]: contiguous per antenna.
    for (uint8_t a = 0; a < A; ++a)
        for (uint8_t s = 0; s < S; ++s)
            for (uint8_t p = 0; p < NOF_POLS; ++p) {
                const size_t off = a * NOF_SAMPLES * NOF_POLS + s * NOF_POLS + p;
                EXPECT_EQ(buf[off], a * 10 + s * 2 + p)
                    << "ant=" << +a << " samp=" << +s << " pol=" << +p;
            }
}

// ── Tile mapping ─────────────────────────────────────────────────────────────

TEST_F(RawDataTest, DistinctTilesGetSeparateBuffers)
{
    std::vector<uint8_t> a = {0xAA, 0xAA};
    std::vector<uint8_t> b = {0xBB, 0xBB};
    add_burst(c_, /*tile=*/3, 0, 0, 1, a.data(), 1.0);
    add_burst(c_, /*tile=*/7, 0, 0, 1, b.data(), 2.0);

    c_.setCallback(capturing_callback);
    c_.persist_container();
    // Two distinct tiles -> two callback invocations.
    EXPECT_EQ(g_capture.calls, 2);
}

TEST_F(RawDataTest, TileBeyondCapacityIsDropped)
{
    std::vector<uint8_t> d = {0x01, 0x02};
    // NOF_TILES distinct tiles fill the map; the next distinct tile is dropped.
    add_burst(c_, /*tile=*/10, 0, 0, 1, d.data(), 1.0);
    add_burst(c_, /*tile=*/20, 0, 0, 1, d.data(), 1.0);
    add_burst(c_, /*tile=*/30, 0, 0, 1, d.data(), 1.0);  // dropped: map full

    c_.setCallback(capturing_callback);
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, NOF_TILES);  // only the first two tiles persisted
}

// ── Metadata ─────────────────────────────────────────────────────────────────

TEST_F(RawDataTest, MetadataCountsPacketsAndRecordsCounter)
{
    std::vector<uint8_t> d = {0x01, 0x02};
    add_burst(c_, 0, 0, 0, 1, d.data(), 1.0, /*packet_counter=*/42);
    add_burst(c_, 0, 0, 1, 1, d.data(), 1.0, /*packet_counter=*/43);

    c_.setCallback(capturing_callback);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.meta.nof_packets, 2u);
    EXPECT_EQ(g_capture.meta.packet_counter[0], 42u);
    EXPECT_EQ(g_capture.meta.packet_counter[1], 43u);
}

// ── Timestamp: keep the earliest sample's timestamp ──────────────────────────

TEST_F(RawDataTest, TimestampTracksEarliestSampleIndex)
{
    std::vector<uint8_t> d = {0x01, 0x02};
    add_burst(c_, 0, 0, /*start_sample=*/4, 1, d.data(), /*timestamp=*/10.0);
    add_burst(c_, 0, 0, /*start_sample=*/0, 1, d.data(), /*timestamp=*/5.0);

    c_.setCallback(capturing_callback);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);
    // The lower start_sample_index (0, timestamp 5.0) wins.
    EXPECT_DOUBLE_EQ(g_capture.timestamp, 5.0);
}

// ── persist / clear semantics ────────────────────────────────────────────────

TEST_F(RawDataTest, PersistWithoutCallbackDoesNotCrashAndClears)
{
    std::vector<uint8_t> d = {0x01, 0x02};
    add_burst(c_, 0, 0, 0, 1, d.data(), 1.0);
    c_.persist_container();  // no callback set: warns + clears, must not crash

    // After the clear, a subsequent persist with a callback sees no data.
    c_.setCallback(capturing_callback);
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, 0);
}

TEST_F(RawDataTest, PersistClearsBetweenIntegrations)
{
    std::vector<uint8_t> d = {0x01, 0x02};
    c_.setCallback(capturing_callback);

    add_burst(c_, 0, 0, 0, 1, d.data(), 1.0);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);

    // Empty integration: nothing written, callback not fired again.
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, 1);
}
