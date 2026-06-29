// Unit tests for the beamformed DAQ modes (BeamformedData.h).
//
// Exercises both beam containers against the REAL aavs-daq library:
//   * IntegratedBeamDataContainer<T>  — integrated-beam consumer
//   * BurstBeamDataContainer<T>        — burst-beam consumer
//
// The BeamMetadata structs default-initialise their arrays with `= 0` (only
// ever instantiated by a default-construction the production code avoids via
// malloc), so the capture reads metadata fields through the pointer rather than
// copying the whole struct.

#include <gtest/gtest.h>
#include <cstring>
#include <vector>

#include "BeamformedData.h"

using Integrated = IntegratedBeamDataContainer<uint16_t>;
using Burst      = BurstBeamDataContainer<uint16_t>;

// ── Geometry (shared by both containers) ─────────────────────────────────────

static constexpr uint16_t NOF_TILES   = 1;
static constexpr uint32_t NOF_BEAMS   = 1;
static constexpr uint32_t NOF_SAMPLES = 2;
static constexpr uint16_t NOF_CHANS   = 4;
static constexpr uint8_t  NOF_POLS    = 2;
// Both containers expose a NOF_BEAMS*NOF_POLS*NOF_SAMPLES*NOF_CHANS buffer (the
// integrated one with NOF_BEAMS=1) and the burst callback reorders into a
// buffer of the same element count.
static constexpr size_t   BUF_ELEMS   = NOF_BEAMS * NOF_POLS * NOF_SAMPLES * NOF_CHANS;
// Offset of the pol-1 plane in each callback buffer.
static constexpr size_t   POL1_BASE   = NOF_CHANS * NOF_SAMPLES;

// ── Callback capture ─────────────────────────────────────────────────────────

namespace {
struct Capture {
    int                   calls = 0;
    std::vector<uint16_t> data;
    double                timestamp = 0.0;
    uint64_t              nof_packets = 0;
    uint32_t              packet_counter[2] = {0, 0};
};
Capture g_capture;

template <class Meta>
void capture(void *data, double timestamp, void *userdata)
{
    const auto *m = static_cast<const Meta *>(userdata);
    g_capture.calls++;
    g_capture.timestamp = timestamp;
    g_capture.nof_packets = m->nof_packets;
    g_capture.packet_counter[0] = m->packet_counter[0];
    g_capture.packet_counter[1] = m->packet_counter[1];
    auto *p = static_cast<uint16_t *>(data);
    g_capture.data.assign(p, p + BUF_ELEMS);
}

void integrated_cb(void *d, double t, void *u) { capture<Integrated::BeamMetadata>(d, t, u); }
void burst_cb(void *d, double t, void *u)      { capture<Burst::BeamMetadata>(d, t, u); }
}  // namespace

// ─────────────────────────────────────────────────────────────────────────────
// Integrated beam
// ─────────────────────────────────────────────────────────────────────────────

class IntegratedBeamTest : public ::testing::Test {
protected:
    void SetUp() override { g_capture = Capture{}; }
    Integrated c_{NOF_TILES, NOF_BEAMS, NOF_SAMPLES, NOF_CHANS, NOF_POLS};
};

static void add_int(Integrated &c, uint8_t tile, uint8_t beam, uint16_t start_channel,
                    uint16_t included_channels, uint32_t start_sample, uint32_t samples,
                    uint16_t *data, double timestamp, uint32_t packet_counter = 0)
{
    c.add_data(packet_counter, /*payload_length=*/0, /*sync_time=*/0,
               /*timestamp_field=*/0, /*station_id=*/0, /*nof_contributing_antennas=*/0,
               /*payload_offset=*/0, tile, beam, start_channel, included_channels,
               start_sample, samples, data, timestamp);
}

TEST_F(IntegratedBeamTest, SingleChannelSampleRoundTrip)
{
    // One channel, one sample: pol0 lands at index 0, pol1 in the pol-1 plane.
    std::vector<uint16_t> src = {0xAAAA, 0x5555};
    c_.setCallback(integrated_cb);
    add_int(c_, /*tile=*/0, /*beam=*/0, /*start_channel=*/0, /*included_channels=*/1,
            /*start_sample=*/0, /*samples=*/1, src.data(), 1.0);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.data[0], 0xAAAA);            // pol 0
    EXPECT_EQ(g_capture.data[POL1_BASE], 0x5555);    // pol 1
}

TEST_F(IntegratedBeamTest, MetadataCountsPackets)
{
    std::vector<uint16_t> src = {1, 2};
    c_.setCallback(integrated_cb);
    add_int(c_, 0, 0, 0, 1, 0, 1, src.data(), 1.0, /*packet_counter=*/7);
    add_int(c_, 0, 0, 0, 1, 1, 1, src.data(), 1.0, /*packet_counter=*/8);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.nof_packets, 2u);
    EXPECT_EQ(g_capture.packet_counter[0], 7u);
    EXPECT_EQ(g_capture.packet_counter[1], 8u);
}

TEST_F(IntegratedBeamTest, TileBeyondCapacityIsDroppedSafely)
{
    std::vector<uint16_t> src = {1, 2};
    c_.setCallback(integrated_cb);
    add_int(c_, /*tile=*/0, 0, 0, 1, 0, 1, src.data(), 1.0);  // fills the slot
    add_int(c_, /*tile=*/9, 0, 0, 1, 0, 1, src.data(), 1.0);  // dropped
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, NOF_TILES);
}

TEST_F(IntegratedBeamTest, TimestampKeepsEarliestSample)
{
    std::vector<uint16_t> src = {1, 2};
    c_.setCallback(integrated_cb);
    add_int(c_, 0, 0, 0, 1, /*start_sample=*/1, 1, src.data(), /*timestamp=*/9.0);
    add_int(c_, 0, 0, 0, 1, /*start_sample=*/0, 1, src.data(), /*timestamp=*/4.0);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_DOUBLE_EQ(g_capture.timestamp, 4.0);  // lowest start_sample_index wins
}

TEST_F(IntegratedBeamTest, PersistWithoutCallbackDoesNotCrash)
{
    std::vector<uint16_t> src = {1, 2};
    add_int(c_, 0, 0, 0, 1, 0, 1, src.data(), 1.0);
    c_.persist_container();  // no callback: warns, must not crash
    SUCCEED();
}

TEST_F(IntegratedBeamTest, PersistClearsBetweenIntegrations)
{
    std::vector<uint16_t> src = {1, 2};
    c_.setCallback(integrated_cb);
    add_int(c_, 0, 0, 0, 1, 0, 1, src.data(), 1.0);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);
    c_.persist_container();  // empty integration
    EXPECT_EQ(g_capture.calls, 1);
}

// ─────────────────────────────────────────────────────────────────────────────
// Burst beam
// ─────────────────────────────────────────────────────────────────────────────

class BurstBeamTest : public ::testing::Test {
protected:
    void SetUp() override { g_capture = Capture{}; }
    Burst c_{NOF_TILES, NOF_SAMPLES, NOF_CHANS, NOF_POLS};
};

static void add_burst(Burst &c, uint8_t tile, uint8_t beam, uint64_t offset,
                      uint16_t start_channel, uint64_t size, uint16_t included_channels,
                      uint16_t *data, double timestamp, uint32_t packet_counter = 0)
{
    c.add_data(packet_counter, /*payload_length=*/0, /*sync_time=*/0,
               /*timestamp_field=*/0, beam, /*station_id=*/0,
               /*nof_contributing_antennas=*/0, /*payload_offset=*/0,
               included_channels, tile, offset, start_channel, size, data, timestamp);
}

TEST_F(BurstBeamTest, SingleChannelPairRoundTrip)
{
    // One (pol0, pol1) pair at channel 0, sample 0. persist_container reorders
    // the interleaved store into separate pol planes for the callback.
    std::vector<uint16_t> src = {0x1234, 0x5678};
    c_.setCallback(burst_cb);
    add_burst(c_, /*tile=*/0, /*beam=*/0, /*offset=*/0, /*start_channel=*/0,
              /*size=*/2, /*included_channels=*/1, src.data(), 1.0);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.data[0], 0x1234);          // pol 0 plane
    EXPECT_EQ(g_capture.data[POL1_BASE], 0x5678);  // pol 1 plane
}

TEST_F(BurstBeamTest, MetadataCountsPackets)
{
    std::vector<uint16_t> src = {1, 2};
    c_.setCallback(burst_cb);
    add_burst(c_, 0, 0, 0, 0, 2, 1, src.data(), 1.0, /*packet_counter=*/21);
    add_burst(c_, 0, 0, 0, 0, 2, 1, src.data(), 1.0, /*packet_counter=*/22);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.nof_packets, 2u);
    EXPECT_EQ(g_capture.packet_counter[0], 21u);
    EXPECT_EQ(g_capture.packet_counter[1], 22u);
}

TEST_F(BurstBeamTest, TileBeyondCapacityIsDroppedSafely)
{
    std::vector<uint16_t> src = {1, 2};
    c_.setCallback(burst_cb);
    add_burst(c_, /*tile=*/0, 0, 0, 0, 2, 1, src.data(), 1.0);
    add_burst(c_, /*tile=*/9, 0, 0, 0, 2, 1, src.data(), 1.0);  // dropped
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, NOF_TILES);
}

TEST_F(BurstBeamTest, PersistWithoutCallbackDoesNotCrashAndClears)
{
    std::vector<uint16_t> src = {1, 2};
    add_burst(c_, 0, 0, 0, 0, 2, 1, src.data(), 1.0);
    c_.persist_container();  // no callback: clears + warns

    c_.setCallback(burst_cb);
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, 0);
}

TEST_F(BurstBeamTest, PersistClearsBetweenIntegrations)
{
    std::vector<uint16_t> src = {1, 2};
    c_.setCallback(burst_cb);
    add_burst(c_, 0, 0, 0, 0, 2, 1, src.data(), 1.0);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);
    c_.persist_container();  // empty integration
    EXPECT_EQ(g_capture.calls, 1);
}
