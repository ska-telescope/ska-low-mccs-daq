// GPU correlator tests (TensorCorrelatorData.cpp).
//
// This target is only built when the CUDA toolkit, cudawrappers, libtcc AND a
// physical GPU are present (see tests/cpp/CMakeLists.txt, BUILD_GPU_TESTS). It
// links the real cudawrappers/libtcc — not the cudawrappers stub the
// TccSplitRing test uses.
//
// packetFilter is pure SPEAD parsing and needs no device. The correlation
// round-trip needs a GPU at run time; it GTEST_SKIPs if none is visible (the
// build node and run node may differ), so the binary is safe to run anywhere.

#include <cuda_runtime.h>
#include <gtest/gtest.h>
#include <vector>

#include "DAQ.h"
#include "TensorCorrelatorData.h"
#include "spead_test_util.h"

namespace {
bool gpu_visible()
{
    int count = 0;
    return cudaGetDeviceCount(&count) == cudaSuccess && count > 0;
}

// Mode marker lives at SPEAD item slot 5 (packetFilter reads SPEAD_ITEM(pkt, 5)
// directly). Build a packet with the marker as the 5th item.
std::vector<uint8_t> make_filter_packet(uint64_t mode)
{
    return SpeadPacket()
        .item(0x0001, 0)     // slot 1: heap counter
        .item(0x0004, 0)     // slot 2: payload length
        .item(0x1027, 0)     // slot 3: sync time
        .item(0x1600, 0)     // slot 4: timestamp
        .item(0x2004, mode)  // slot 5: capture mode  <-- read by packetFilter
        .build();
}
}  // namespace

// Expose the protected packet path.
class TestableTensorCorrelator : public TensorCorrelatorData {
public:
    using TensorCorrelatorData::packetFilter;
    using TensorCorrelatorData::processPacket;
};

// ── packetFilter (no GPU required) ───────────────────────────────────────────

TEST(TensorCorrelatorFilterTest, AcceptsCorrelatorModes)
{
    TestableTensorCorrelator c;
    for (uint64_t mode : {0x4ull, 0x5ull, 0x7ull}) {
        auto pkt = make_filter_packet(mode);
        EXPECT_TRUE(c.packetFilter(pkt.data())) << "mode=" << mode;
    }
}

TEST(TensorCorrelatorFilterTest, RejectsOtherModes)
{
    TestableTensorCorrelator c;
    for (uint64_t mode : {0x0ull, 0x1ull, 0x6ull}) {
        auto pkt = make_filter_packet(mode);
        EXPECT_FALSE(c.packetFilter(pkt.data())) << "mode=" << mode;
    }
}

TEST(TensorCorrelatorFilterTest, RejectsNonSpead)
{
    TestableTensorCorrelator c;
    std::vector<uint8_t> garbage(64, 0xFF);
    EXPECT_FALSE(c.packetFilter(garbage.data()));
}

// ── Correlation round-trip (requires a GPU at run time) ──────────────────────

class TensorCorrelatorGpuTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        if (!gpu_visible())
            GTEST_SKIP() << "no CUDA device visible at run time";
        attachLogger([](int, const char *) {});
    }
    void TearDown() override { attachLogger(nullptr); }
};

TEST_F(TensorCorrelatorGpuTest, InitialiseConsumerAllocatesGpuCorrelator)
{
    TestableTensorCorrelator c;
    json config = {
        {"nof_antennas", 4},
        {"nof_channels", 1},
        {"nof_fine_channels", 1},
        {"nof_tiles", 1},
        {"nof_active_tiles", 1},
        {"nof_samples", 256},
        {"nof_pols", 2},
        {"max_packet_size", 9000},
    };
    // Smoke test: building the TCC correlator + CUDA context must succeed on a GPU.
    EXPECT_TRUE(c.initialiseConsumer(config));
}

// TODO (GPU machine): drive a full visibility round-trip — push voltage packets
// for a known signal through processPacket, let the Tensor-Core Correlator run,
// and assert the auto-correlations/cross-correlations delivered to the callback.
// Needs the correlator's SPEAD voltage-packet layout and TCC output ordering,
// which should be pinned down on real hardware rather than guessed here.
