// Unit tests for the channelised DAQ mode (ChannelisedData.h).
//
// Exercises ChannelDataContainer<T> — the buffer behind the channel
// consumers — against the REAL aavs-daq library (DAQ.h, LOG, mmap-backed
// allocation), not a stub.

#include <gtest/gtest.h>
#include <cstring>
#include <vector>

#include "ChannelisedData.h"

using Container   = ChannelDataContainer<uint16_t>;
using Container32 = ChannelDataContainer<uint32_t>;

// ── Constants ──────────────────────────────────────────────────────────────

static constexpr uint16_t NOF_TILES   = 1;
static constexpr uint16_t NOF_ANT     = 2;
static constexpr uint32_t NOF_SAMPLES = 4;
static constexpr uint16_t NOF_CHANS   = 8;
static constexpr uint8_t  NOF_POLS    = 2;
static constexpr size_t   TILE_ELEMS  = NOF_CHANS * NOF_ANT * NOF_POLS * NOF_SAMPLES;

// Layout strides for [channel][sample][antenna][pol].
static constexpr long CH_STRIDE  = NOF_SAMPLES * NOF_ANT * NOF_POLS;
static constexpr long SMP_STRIDE = NOF_ANT * NOF_POLS;

// persist_container() only fires the callback once a tile has accumulated at
// least nof_tiles * nof_pols * 2 packets.
static constexpr unsigned PERSIST_THRESHOLD = NOF_TILES * NOF_POLS * 2;

// ── Callback capture ─────────────────────────────────────────────────────────

namespace {
struct Capture {
    int                   calls = 0;
    std::vector<uint16_t> data;
    double                timestamp = 0.0;
    ChannelMetadata       meta{};
};
Capture g_capture;

// Snapshot inside the callback — persist_container() clear()s the buffer right
// after invoking it.
void capturing_callback(void *data, double timestamp, void *userdata)
{
    g_capture.calls++;
    g_capture.timestamp = timestamp;
    g_capture.meta = *static_cast<ChannelMetadata *>(userdata);
    auto *p = static_cast<uint16_t *>(data);
    g_capture.data.assign(p, p + TILE_ELEMS);
}
}  // namespace

// ── Fixture & helper ─────────────────────────────────────────────────────────

class ChannelisedDataTest : public ::testing::Test {
protected:
    void SetUp() override { g_capture = Capture{}; }
    Container c_{NOF_TILES, NOF_ANT, NOF_SAMPLES, NOF_CHANS, NOF_POLS};
};

// Thin wrapper over the wide add_data signature.
static void add(Container &c, uint8_t tile, uint16_t channel,
                uint32_t start_sample, uint32_t samples, uint16_t start_antenna,
                uint16_t included_channels, uint16_t included_antennas,
                uint16_t *data, double timestamp, uint32_t packet_counter = 0)
{
    c.add_data(/*timestamp_field=*/0, packet_counter, /*sync_time=*/0,
               /*station_id=*/0, /*payload_offset=*/0, tile, /*fpga_id=*/0,
               channel, start_sample, samples, start_antenna, data, timestamp,
               included_channels, included_antennas, /*payload_length=*/0);
}

// ── Round-trip a packet at the buffer origin ─────────────────────────────────

TEST_F(ChannelisedDataTest, SinglePacketRoundTripsAtOrigin)
{
    // channel 0, sample 0, both antennas, both pols -> 4 contiguous values.
    std::vector<uint16_t> payload = {0x1111, 0x2222, 0x3333, 0x4444};

    // Need PERSIST_THRESHOLD packets before persist fires; re-send the same one.
    c_.setCallback(capturing_callback);
    for (unsigned i = 0; i < PERSIST_THRESHOLD; ++i)
        add(c_, /*tile=*/0, /*channel=*/0, /*start_sample=*/0, /*samples=*/1,
            /*start_antenna=*/0, /*included_channels=*/1, /*included_antennas=*/NOF_ANT,
            payload.data(), 1.0);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.data[0], 0x1111);
    EXPECT_EQ(g_capture.data[1], 0x2222);
    EXPECT_EQ(g_capture.data[2], 0x3333);
    EXPECT_EQ(g_capture.data[3], 0x4444);
}

TEST_F(ChannelisedDataTest, WriteLandsAtChannelSampleAntennaOffset)
{
    // Single antenna (1) at channel 2, sample 1 -> a non-trivial destination.
    std::vector<uint16_t> payload = {0xDEAD, 0xBEEF};  // one antenna, two pols
    c_.setCallback(capturing_callback);
    for (unsigned i = 0; i < PERSIST_THRESHOLD; ++i)
        add(c_, /*tile=*/0, /*channel=*/2, /*start_sample=*/1, /*samples=*/1,
            /*start_antenna=*/1, /*included_channels=*/1, /*included_antennas=*/1,
            payload.data(), 1.0);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    const long off = 2 * CH_STRIDE + 1 * SMP_STRIDE + 1 * NOF_POLS;  // = 32+4+2 = 38
    EXPECT_EQ(g_capture.data[off + 0], 0xDEAD);
    EXPECT_EQ(g_capture.data[off + 1], 0xBEEF);
    EXPECT_EQ(g_capture.data[0], 0u);  // origin untouched
}

// ── persist gating ───────────────────────────────────────────────────────────

TEST_F(ChannelisedDataTest, PersistGatedByPacketThreshold)
{
    std::vector<uint16_t> payload = {1, 2, 3, 4};
    c_.setCallback(capturing_callback);
    // One short of the threshold -> callback must not fire.
    for (unsigned i = 0; i < PERSIST_THRESHOLD - 1; ++i)
        add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0);
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, 0);
}

// ── Tile capacity guard ──────────────────────────────────────────────────────

TEST_F(ChannelisedDataTest, TileBeyondCapacityIsDroppedSafely)
{
    std::vector<uint16_t> payload = {1, 2, 3, 4};
    // tile >= nof_tiles is rejected up front; must not crash or persist.
    for (unsigned i = 0; i < PERSIST_THRESHOLD; ++i)
        add(c_, /*tile=*/5, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0);
    c_.setCallback(capturing_callback);
    c_.persist_container();
    EXPECT_EQ(g_capture.calls, 0);
}

// ── Metadata ─────────────────────────────────────────────────────────────────

TEST_F(ChannelisedDataTest, MetadataTracksPacketsAndFirstCounter)
{
    std::vector<uint16_t> payload = {1, 2, 3, 4};
    c_.setCallback(capturing_callback);
    add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0, /*packet_counter=*/100);
    add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0, /*packet_counter=*/50);
    add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0, /*packet_counter=*/200);
    add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0, /*packet_counter=*/75);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_EQ(g_capture.meta.nof_packets, PERSIST_THRESHOLD);
    EXPECT_EQ(g_capture.meta.first_packet_counter, 50u);  // smallest seen
}

// ── Timestamp: earliest wins ─────────────────────────────────────────────────

TEST_F(ChannelisedDataTest, TimestampKeepsEarliest)
{
    std::vector<uint16_t> payload = {1, 2, 3, 4};
    c_.setCallback(capturing_callback);
    add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), /*timestamp=*/9.0);
    add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), /*timestamp=*/3.0);
    add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), /*timestamp=*/7.0);
    add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), /*timestamp=*/5.0);
    c_.persist_container();

    ASSERT_EQ(g_capture.calls, 1);
    EXPECT_DOUBLE_EQ(g_capture.timestamp, 3.0);
}

// ── clear / no-callback safety ───────────────────────────────────────────────

TEST_F(ChannelisedDataTest, PersistWithoutCallbackDoesNotCrashAndClears)
{
    std::vector<uint16_t> payload = {1, 2, 3, 4};
    for (unsigned i = 0; i < PERSIST_THRESHOLD; ++i)
        add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0);
    c_.persist_container();  // no callback: warns + clears

    c_.setCallback(capturing_callback);
    c_.persist_container();  // buffer was cleared -> nothing to emit
    EXPECT_EQ(g_capture.calls, 0);
}

TEST_F(ChannelisedDataTest, PersistClearsBetweenIntegrations)
{
    std::vector<uint16_t> payload = {1, 2, 3, 4};
    c_.setCallback(capturing_callback);
    for (unsigned i = 0; i < PERSIST_THRESHOLD; ++i)
        add(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0);
    c_.persist_container();
    ASSERT_EQ(g_capture.calls, 1);

    c_.persist_container();  // empty integration
    EXPECT_EQ(g_capture.calls, 1);
}

// ══════════════════════════════════════════════════════════════════════════════
// ChannelDataContainer<uint32_t> — 32-bit (integrated) variant
//
// The consumer can be configured with bitwidth=32, which selects a
// ChannelDataContainer<uint32_t> instead of the 16-bit default.  These tests
// exercise the same template code paths with uint32_t to ensure full
// instantiation coverage.
// ══════════════════════════════════════════════════════════════════════════════

namespace {
struct Capture32 {
    int                   calls = 0;
    std::vector<uint32_t> data;
    double                timestamp = 0.0;
    ChannelMetadata       meta{};
};
Capture32 g_capture32;

void capturing_callback32(void *data, double timestamp, void *userdata)
{
    g_capture32.calls++;
    g_capture32.timestamp = timestamp;
    g_capture32.meta = *static_cast<ChannelMetadata *>(userdata);
    // persist_container always casts channel_data to uint32_t*; for T=uint32_t
    // this is an identity cast — read TILE_ELEMS uint32_t values directly.
    auto *p = static_cast<uint32_t *>(data);
    g_capture32.data.assign(p, p + TILE_ELEMS);
}
}  // namespace

static void add32(Container32 &c, uint8_t tile, uint16_t channel,
                  uint32_t start_sample, uint32_t samples, uint16_t start_antenna,
                  uint16_t included_channels, uint16_t included_antennas,
                  uint32_t *data, double timestamp, uint32_t packet_counter = 0)
{
    c.add_data(/*timestamp_field=*/0, packet_counter, /*sync_time=*/0,
               /*station_id=*/0, /*payload_offset=*/0, tile, /*fpga_id=*/0,
               channel, start_sample, samples, start_antenna, data, timestamp,
               included_channels, included_antennas, /*payload_length=*/0);
}

class ChannelisedDataTest32 : public ::testing::Test {
protected:
    void SetUp() override { g_capture32 = Capture32{}; }
    Container32 c_{NOF_TILES, NOF_ANT, NOF_SAMPLES, NOF_CHANS, NOF_POLS};
};

// Round-trip through a 32-bit container — constructor, add_data, persist_container
// and destructor are all exercised, covering the <uint32_t> template instantiation.
TEST_F(ChannelisedDataTest32, U32SinglePacketRoundTripsAtOrigin)
{
    std::vector<uint32_t> payload = {0x11111111u, 0x22222222u, 0x33333333u, 0x44444444u};
    c_.setCallback(capturing_callback32);
    for (unsigned i = 0; i < PERSIST_THRESHOLD; ++i)
        add32(c_, /*tile=*/0, /*channel=*/0, /*start_sample=*/0, /*samples=*/1,
              /*start_antenna=*/0, /*included_channels=*/1, /*included_antennas=*/NOF_ANT,
              payload.data(), 1.0);
    c_.persist_container();

    ASSERT_EQ(g_capture32.calls, 1);
    EXPECT_EQ(g_capture32.data[0], 0x11111111u);
    EXPECT_EQ(g_capture32.data[1], 0x22222222u);
    EXPECT_EQ(g_capture32.data[2], 0x33333333u);
    EXPECT_EQ(g_capture32.data[3], 0x44444444u);
}

TEST_F(ChannelisedDataTest32, U32PersistGatedByPacketThreshold)
{
    std::vector<uint32_t> payload = {1u, 2u, 3u, 4u};
    c_.setCallback(capturing_callback32);
    // One short of the threshold — callback must not fire.
    for (unsigned i = 0; i < PERSIST_THRESHOLD - 1; ++i)
        add32(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0);
    c_.persist_container();
    EXPECT_EQ(g_capture32.calls, 0);
}

TEST_F(ChannelisedDataTest32, U32MetadataTracksPackets)
{
    std::vector<uint32_t> payload = {1u, 2u, 3u, 4u};
    c_.setCallback(capturing_callback32);
    add32(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0, /*pc=*/10);
    add32(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0, /*pc=*/5);
    add32(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0, /*pc=*/20);
    add32(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0, /*pc=*/15);
    c_.persist_container();

    ASSERT_EQ(g_capture32.calls, 1);
    EXPECT_EQ(g_capture32.meta.nof_packets, PERSIST_THRESHOLD);
    EXPECT_EQ(g_capture32.meta.first_packet_counter, 5u);
}

TEST_F(ChannelisedDataTest32, U32TileBeyondCapacityIsDroppedSafely)
{
    std::vector<uint32_t> payload = {1u, 2u, 3u, 4u};
    for (unsigned i = 0; i < PERSIST_THRESHOLD; ++i)
        add32(c_, /*tile=*/5, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0);
    c_.setCallback(capturing_callback32);
    c_.persist_container();
    EXPECT_EQ(g_capture32.calls, 0);
}

TEST_F(ChannelisedDataTest32, U32ClearResetsState)
{
    std::vector<uint32_t> payload = {1u, 2u, 3u, 4u};
    c_.setCallback(capturing_callback32);
    for (unsigned i = 0; i < PERSIST_THRESHOLD; ++i)
        add32(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0);
    c_.persist_container();
    ASSERT_EQ(g_capture32.calls, 1);

    // After persist the buffer is cleared — a second persist emits nothing.
    c_.persist_container();
    EXPECT_EQ(g_capture32.calls, 1);
}

// Covers the "No callback defined" warn-and-return path for <uint32_t>.
TEST_F(ChannelisedDataTest32, U32PersistWithoutCallbackDoesNotCrash)
{
    std::vector<uint32_t> payload = {1u, 2u, 3u, 4u};
    for (unsigned i = 0; i < PERSIST_THRESHOLD; ++i)
        add32(c_, 0, 0, 0, 1, 0, 1, NOF_ANT, payload.data(), 1.0);
    c_.persist_container();
    EXPECT_EQ(g_capture32.calls, 0);
}

// ── Factory functions ─────────────────────────────────────────────────────────
// burstchannel/continuouschannel/integratedchannel are defined inline in the
// header.  Calling them exercises lines 412-414 in ChannelisedData.h.
// The objects are only constructed and destroyed (no initialiseConsumer), so
// the container pointer stays at its default (unset) and cleanUp is a no-op.
//
// NOTE: ChannelisedData.cpp methods (processPacket etc.) are NOT available in
// this TU (we include only the .h), so the tests below are kept in
// test_channelised_data_consumer.cpp which does include the full .cpp.
// The lines-412-414 coverage is therefore attributed to that binary.
