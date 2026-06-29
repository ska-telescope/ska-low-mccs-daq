// Unit tests for the aavs-daq lock-free RingBuffer (RingBuffer.cpp).
//
// RingBuffer is the single-producer/single-consumer queue that sits between the
// network receiver and the data consumers. These tests drive it directly,
// against the REAL aavs-daq sources.
//
// Contract reminders:
//   * push(data, size) copies `size` bytes into the next cell; returns false
//     when the buffer is full.
//   * pull(&ptr) blocks until a cell is available and returns its size; the
//     caller must call pull_ready() to release the cell.
//   * pull_timeout(&ptr, secs) is the non-blocking variant, returning SIZE_MAX
//     on timeout.
//   * cell_size is rounded up to the cache line; nof_cells up to a power of two.

#include <gtest/gtest.h>
#include <cstdint>
#include <cstring>
#include <vector>

#include "RingBuffer.h"

static constexpr size_t CELL_SIZE = 64;

// Build a payload of CELL-fitting bytes tagged with `tag` so each push is
// distinguishable on pull.
static std::vector<uint8_t> make_payload(uint8_t tag, size_t size = 16)
{
    return std::vector<uint8_t>(size, tag);
}

// ── push / pull round-trip ───────────────────────────────────────────────────

TEST(RingBufferTest, PushThenPullReturnsSameData)
{
    RingBuffer rb(CELL_SIZE, /*nofcells=*/4);
    auto payload = make_payload(0x5A, /*size=*/16);

    ASSERT_TRUE(rb.push(payload.data(), payload.size()));

    uint8_t *out = nullptr;
    size_t   size = rb.pull(&out);
    EXPECT_EQ(size, payload.size());
    ASSERT_NE(out, nullptr);
    EXPECT_EQ(std::memcmp(out, payload.data(), payload.size()), 0);
    rb.pull_ready();
}

TEST(RingBufferTest, PreservesFifoOrderAcrossItems)
{
    RingBuffer rb(CELL_SIZE, 4);
    auto a = make_payload(0xAA);
    auto b = make_payload(0xBB);

    ASSERT_TRUE(rb.push(a.data(), a.size()));
    ASSERT_TRUE(rb.push(b.data(), b.size()));

    uint8_t *out = nullptr;
    rb.pull(&out);
    EXPECT_EQ(out[0], 0xAA);
    rb.pull_ready();

    rb.pull(&out);
    EXPECT_EQ(out[0], 0xBB);
    rb.pull_ready();
}

TEST(RingBufferTest, PreservesPerItemDataSize)
{
    RingBuffer rb(CELL_SIZE, 4);
    auto small = make_payload(0x11, /*size=*/8);
    auto large = make_payload(0x22, /*size=*/40);

    ASSERT_TRUE(rb.push(small.data(), small.size()));
    ASSERT_TRUE(rb.push(large.data(), large.size()));

    uint8_t *out = nullptr;
    EXPECT_EQ(rb.pull(&out), 8u);
    rb.pull_ready();
    EXPECT_EQ(rb.pull(&out), 40u);
    rb.pull_ready();
}

// ── Capacity & full behaviour ────────────────────────────────────────────────

TEST(RingBufferTest, PushReturnsFalseWhenFull)
{
    RingBuffer rb(CELL_SIZE, /*nofcells=*/4);
    auto payload = make_payload(0x01);

    // Fill every cell without consuming.
    for (int i = 0; i < 4; ++i)
        EXPECT_TRUE(rb.push(payload.data(), payload.size())) << "push " << i;

    // The buffer is now full; the next push is rejected.
    EXPECT_FALSE(rb.push(payload.data(), payload.size()));
}

TEST(RingBufferTest, CapacityRoundsUpToPowerOfTwo)
{
    // nofcells = 3 is rounded up to 4, so exactly four pushes succeed.
    RingBuffer rb(CELL_SIZE, /*nofcells=*/3);
    auto payload = make_payload(0x07);

    for (int i = 0; i < 4; ++i)
        EXPECT_TRUE(rb.push(payload.data(), payload.size())) << "push " << i;
    EXPECT_FALSE(rb.push(payload.data(), payload.size()));
}

TEST(RingBufferTest, SpaceFreesUpAfterPullReady)
{
    RingBuffer rb(CELL_SIZE, 4);
    auto payload = make_payload(0x09);

    for (int i = 0; i < 4; ++i)
        ASSERT_TRUE(rb.push(payload.data(), payload.size()));
    ASSERT_FALSE(rb.push(payload.data(), payload.size()));  // full

    // Consume one item, freeing a cell.
    uint8_t *out = nullptr;
    rb.pull(&out);
    rb.pull_ready();

    EXPECT_TRUE(rb.push(payload.data(), payload.size()));  // space available again
}

// ── Wrap-around (cells are reused) ───────────────────────────────────────────

TEST(RingBufferTest, WrapsAroundAndReusesCells)
{
    RingBuffer rb(CELL_SIZE, /*nofcells=*/2);  // tiny buffer to force wrapping

    // Push/pull more times than there are cells; data must stay intact.
    for (int i = 0; i < 6; ++i)
    {
        auto payload = make_payload(static_cast<uint8_t>(0x30 + i));
        ASSERT_TRUE(rb.push(payload.data(), payload.size())) << "iter " << i;

        uint8_t *out = nullptr;
        size_t   size = rb.pull(&out);
        EXPECT_EQ(size, payload.size());
        EXPECT_EQ(out[0], static_cast<uint8_t>(0x30 + i)) << "iter " << i;
        rb.pull_ready();
    }
}

// ── pull_timeout ─────────────────────────────────────────────────────────────

TEST(RingBufferTest, PullTimeoutReturnsSizeMaxWhenEmpty)
{
    RingBuffer rb(CELL_SIZE, 4);
    uint8_t *out = nullptr;
    EXPECT_EQ(rb.pull_timeout(&out, /*timeout_seconds=*/0.05), SIZE_MAX);
}

TEST(RingBufferTest, PullTimeoutReturnsDataWhenAvailable)
{
    RingBuffer rb(CELL_SIZE, 4);
    auto payload = make_payload(0xC3);
    ASSERT_TRUE(rb.push(payload.data(), payload.size()));

    uint8_t *out = nullptr;
    size_t   size = rb.pull_timeout(&out, 1.0);
    ASSERT_NE(size, SIZE_MAX);
    EXPECT_EQ(size, payload.size());
    EXPECT_EQ(out[0], 0xC3);
    rb.pull_ready();
}
