#include <gtest/gtest.h>
#include "DoubleBuffer.h"

#include <cstdint>
#include <utility>
#include <vector>

// A buffer holds packets from many tiles, so it must keep the station ID of each
// tile. Keeping only the last packet's ID would hide a tile that sends a
// different station ID.
TEST(DoubleBufferStationIdTest, KeepsStationIdPerTile)
{
    DoubleBuffer buffer(/*nof_antennas=*/2, /*nof_samples=*/4, /*nof_pols=*/2, /*nbuffers=*/2);
    std::vector<uint16_t> payload(4 * 2, 0);

    // One packet per tile, each with one antenna. The wrong station comes first.
    for (const auto &[tile_id, station_id] :
         std::vector<std::pair<uint8_t, uint16_t>>{{0, 352}, {1, 345}})
        buffer.write_data(/*start_antenna=*/tile_id, /*nof_included_antennas=*/1, /*channel=*/3,
                          /*start_sample_index=*/0, /*samples=*/4, payload.data(),
                          /*timestamp=*/1.0, tile_id, station_id);

    Buffer *slot = buffer.get_buffer_pointer(0);
    ASSERT_NE(slot, nullptr);
    EXPECT_EQ(slot->station_ids[0], 352u);
    EXPECT_EQ(slot->station_ids[1], 345u);
    EXPECT_EQ(slot->station_ids[2], 0u);
}

TEST(DoubleBufferStationIdTest, ReleaseResetsStationIds)
{
    DoubleBuffer buffer(/*nof_antennas=*/1, /*nof_samples=*/4, /*nof_pols=*/2, /*nbuffers=*/2);
    std::vector<uint16_t> payload(4 * 2, 0);
    buffer.write_data(0, 1, /*channel=*/3, 0, 4, payload.data(), 1.0, /*tile_id=*/0,
                      /*station_id=*/352);
    buffer.finish_write();

    ASSERT_NE(buffer.read_buffer(), nullptr);
    buffer.release_buffer();

    Buffer *slot = buffer.get_buffer_pointer(0);
    EXPECT_EQ(slot->station_ids[0], 0u);
}
