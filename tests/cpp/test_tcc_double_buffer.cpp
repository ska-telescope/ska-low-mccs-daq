#include <gtest/gtest.h>
#include "TccDoubleBuffer.h"

#include <vector>

class TccDoubleBufferTest : public ::testing::Test
{
protected:
    TccDoubleBuffer buffer_{/*nof_antennas=*/1, /*nof_samples=*/16, /*nof_pols=*/2, /*nbuffers=*/2};
};

TEST_F(TccDoubleBufferTest, ExposesConfiguredBufferCount)
{
    EXPECT_EQ(buffer_.get_number_of_buffers(), 2);
}

TEST_F(TccDoubleBufferTest, WriteDataStoresSamplesInTccLayout)
{
    std::vector<uint16_t> payload(16 * 1 * 2);
    for (size_t i = 0; i < payload.size(); ++i)
        payload[i] = static_cast<uint16_t>(i + 1);

    buffer_.write_data(/*start_antenna=*/0,
                       /*nof_included_antennas=*/1,
                       /*channel=*/7,
                       /*start_sample_index=*/0,
                       /*samples=*/16,
                       payload.data(),
                       /*timestamp=*/1.0);

    Buffer *slot = buffer_.get_buffer_pointer(0);
    ASSERT_NE(slot, nullptr);
    EXPECT_EQ(slot->channel, 7);
    EXPECT_EQ(slot->read_samples, 16u);
    EXPECT_EQ(slot->nof_packets, 1u);
    EXPECT_DOUBLE_EQ(slot->ref_time, 1.0);

    // For one antenna, one 16-sample block, data is laid out as:
    // [pol0 times 0..15] followed by [pol1 times 0..15].
    EXPECT_EQ(slot->data[0], 1u);
    EXPECT_EQ(slot->data[16], 2u);
}

TEST_F(TccDoubleBufferTest, FinishWriteMarksCurrentBufferReady)
{
    std::vector<uint16_t> payload(16 * 1 * 2, 0);
    buffer_.write_data(/*start_antenna=*/0,
                       /*nof_included_antennas=*/1,
                       /*channel=*/3,
                       /*start_sample_index=*/0,
                       /*samples=*/16,
                       payload.data(),
                       /*timestamp=*/2.0);

    buffer_.finish_write();

    Buffer *slot = buffer_.get_buffer_pointer(0);
    ASSERT_NE(slot, nullptr);
    EXPECT_TRUE(slot->ready);
}
