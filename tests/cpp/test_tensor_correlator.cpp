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

#include <atomic>
#include <chrono>
#include <complex>
#include <cuda_runtime.h>
#include <gtest/gtest.h>
#include <thread>
#include <vector>

#include "DAQ.h"
// The .cpp is #included directly (single TU) rather than declared via its
// header so the extern "C" consumer factory defined in TensorCorrelatorData.h
// (the pattern every cdaq consumer header uses, relied on by dlsym) is emitted
// exactly once. Compiling TensorCorrelatorData.cpp as a separate object as well
// would define that factory twice and break linking. Mirrors test_raw_data_consumer.
#include "TensorCorrelatorData.cpp" // NOLINT(bugprone-suspicious-include)
#include "spead_test_util.h"

namespace
{
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
            .item(0x0001, 0)    // slot 1: heap counter
            .item(0x0004, 0)    // slot 2: payload length
            .item(0x1027, 0)    // slot 3: sync time
            .item(0x1600, 0)    // slot 4: timestamp
            .item(0x2004, mode) // slot 5: capture mode  <-- read by packetFilter
            .build();
    }
} // namespace

// Expose the protected packet path and ring-buffer push for testing.
//
// DataCallbackDynamic is a plain function pointer (void(*)(void*,double,void*))
// so capturing lambdas cannot be used directly. setCapturingCallback() stores
// the std::function in a static slot and installs a trampoline — safe as long
// as only one test uses a capturing callback at a time (GTest is single-threaded
// between tests).
class TestableTensorCorrelator : public TensorCorrelatorData
{
public:
    using DataConsumer::cleanUp;
    using TensorCorrelatorData::packetFilter;
    using TensorCorrelatorData::processPacket;

    bool pushPacket(const std::vector<uint8_t> &pkt)
    {
        return ring_buffer->push(const_cast<uint8_t *>(pkt.data()), pkt.size());
    }

    void setCapturingCallback(std::function<void(void *, double, void *)> fn)
    {
        s_fn_ = std::move(fn);
        setCallback(&TestableTensorCorrelator::trampoline);
    }

private:
    static void trampoline(void *data, double ts, void *meta)
    {
        if (s_fn_)
            s_fn_(data, ts, meta);
    }
    static inline std::function<void(void *, double, void *)> s_fn_;
};

// ── packetFilter (no GPU required) ───────────────────────────────────────────

TEST(TensorCorrelatorFilterTest, AcceptsCorrelatorModes)
{
    TestableTensorCorrelator c;
    for (uint64_t mode : {0x4ull, 0x5ull, 0x7ull})
    {
        auto pkt = make_filter_packet(mode);
        EXPECT_TRUE(c.packetFilter(pkt.data())) << "mode=" << mode;
    }
}

TEST(TensorCorrelatorFilterTest, RejectsOtherModes)
{
    TestableTensorCorrelator c;
    for (uint64_t mode : {0x0ull, 0x1ull, 0x6ull})
    {
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

class TensorCorrelatorGpuTest : public ::testing::Test
{
protected:
    void SetUp() override
    {
        if (!gpu_visible())
            GTEST_SKIP() << "no CUDA device visible at run time";
    }
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
    c.cleanUp(); // stop the GPU thread before c is destroyed
}

// Visibility round-trip: push one SPEAD channelised-data packet carrying a
// constant DC signal (SIGNAL + 0j) on every antenna/pol/time sample, let the
// GPU correlator run one integration, and check the delivered visibilities.
//
// Packet format (from the LMC channelised-data SPEAD spec):
//   items: heap_counter(0x0001), pkt_len(0x0004), sync_time(0x1027),
//          timestamp(0x1600), capture_mode(0x2004), channel_info(0x2002),
//          tpm_info(0x2001), sample_offset(0x3300)
//   payload: [N_SAMPLES][N_ANT][N_POL] of uint16_t = complex<int8_t>(real, imag)
//
// TCC output layout: vis[ch=1][baseline][polY][polX] of complex<int32_t>
//   baseline = recvX*(recvX+1)/2 + recvY  (lower triangle, recvX >= recvY)
//
// With all samples = (SIGNAL, 0):
//   vis[any_baseline][any_pol][any_pol] = N_SAMPLES * SIGNAL^2 + 0i
TEST_F(TensorCorrelatorGpuTest, VisibilityRoundTrip)
{
    constexpr int8_t SIGNAL = 10;
    constexpr int N_ANT = 4;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256;
    constexpr int N_BASELINES = N_ANT * (N_ANT + 1) / 2;

    json config = {
        {"nof_antennas", N_ANT},
        {"nof_channels", 1},
        {"nof_fine_channels", 1},
        {"nof_tiles", 1},
        {"nof_active_tiles", 1},
        {"nof_samples", N_SAMPLES},
        {"nof_pols", N_POL},
        {"max_packet_size", 9000},
    };

    TestableTensorCorrelator c;

    ASSERT_TRUE(c.initialiseConsumer(config));

    // setCapturingCallback must come after initialiseConsumer: setCallback
    // dereferences cross_correlator which is only set by initialiseConsumer.
    std::vector<std::complex<int32_t>> vis_out;
    std::atomic<bool> got{false};
    c.setCapturingCallback([&](void *data, double, void *)
                           {
        auto *v = static_cast<std::complex<int32_t> *>(data);
        vis_out.assign(v, v + N_BASELINES * N_POL * N_POL);
        got.store(true, std::memory_order_release); });

    // Payload: N_SAMPLES × N_ANT × N_POL × uint16_t
    // Each uint16_t = complex<int8_t>(SIGNAL, 0): low byte = real, high byte = imag.
    const size_t payload_bytes = (size_t)N_SAMPLES * N_ANT * N_POL * sizeof(uint16_t);
    std::vector<uint8_t> payload_data(payload_bytes);
    for (size_t i = 0; i < payload_bytes; i += 2)
    {
        payload_data[i] = static_cast<uint8_t>(SIGNAL);
        payload_data[i + 1] = 0;
    }

    // item 0x2002: bits[39:24]=start_ch, [23:16]=nof_ch, [15:8]=start_ant, [7:0]=nof_ant
    const uint64_t chan_info = (uint64_t(1) << 16) | uint64_t(N_ANT);

    auto pkt = SpeadPacket()
                   .item(0x0001, 0)             // heap_counter: packet_index=0, counter=0
                   .item(0x0004, payload_bytes) // pkt_len
                   .item(0x1027, 0)             // sync_time
                   .item(0x1600, 0)             // timestamp
                   .item(0x2004, 0x4)           // capture_mode: burst channel
                   .item(0x2002, chan_info)     // channel/antenna info
                   .item(0x2001, 0)             // tpm_info: tile=0, station=0
                   .item(0x3300, 0)             // sample_offset
                   .payload(payload_data)
                   .build();

    ASSERT_TRUE(c.pushPacket(pkt));
    ASSERT_TRUE(c.processPacket());

    // Wait up to 5 s for the GPU thread to deliver the callback.
    for (int i = 0; i < 500 && !got.load(std::memory_order_acquire); ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));

    c.cleanUp(); // stop GPU thread before assertions (and before c is destroyed)

    ASSERT_TRUE(got.load()) << "callback never fired within 5 s";

    // vis[baseline][polY][polX] = N_SAMPLES * SIGNAL^2 + 0i for all entries.
    const int32_t expected_re = (int32_t)N_SAMPLES * SIGNAL * SIGNAL;
    for (int bl = 0; bl < N_BASELINES; ++bl)
        for (int py = 0; py < N_POL; ++py)
            for (int px = 0; px < N_POL; ++px)
            {
                auto v = vis_out[(bl * N_POL + py) * N_POL + px];
                EXPECT_EQ(v.real(), expected_re) << "bl=" << bl << " py=" << py << " px=" << px;
                EXPECT_EQ(v.imag(), 0) << "bl=" << bl << " py=" << py << " px=" << px;
            }
}

// Multi-split round-trip: two packets each covering half the integration span,
// mapped to two separate ring slots (nof_splits=2).  The GPU thread polls both
// slots, streams them in order, and accumulates visibilities across splits.
// This exercises the split > 0 accumulate path and the ring-slot release chain.
//
// Packet layout: each carries N_SAMPLES/2 samples per antenna, with
// heap_counter 0 and 1 so processPacket maps them to split 0 and split 1.
// Expected result is identical to the single-split case because the total
// number of correlated samples is still N_SAMPLES.
TEST_F(TensorCorrelatorGpuTest, VisibilityRoundTripMultiSplit)
{
    constexpr int8_t SIGNAL = 10;
    constexpr int N_ANT = 4;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256 * 16;
    constexpr int N_SPLITS = 64;
    constexpr int N_BASELINES = N_ANT * (N_ANT + 1) / 2;

    json config = {
        {"nof_antennas", N_ANT},
        {"nof_channels", 1},
        {"nof_fine_channels", 1},
        {"nof_tiles", 1},
        {"nof_active_tiles", 1},
        {"nof_samples", N_SAMPLES},
        {"nof_pols", N_POL},
        {"max_packet_size", 9000},
        {"nof_splits", N_SPLITS},
    };

    TestableTensorCorrelator c;
    ASSERT_TRUE(c.initialiseConsumer(config));

    std::vector<std::complex<int32_t>> vis_out;
    std::atomic<bool> got{false};
    c.setCapturingCallback([&](void *data, double, void *)
                           {
        auto *v = static_cast<std::complex<int32_t> *>(data);
        vis_out.assign(v, v + N_BASELINES * N_POL * N_POL);
        got.store(true, std::memory_order_release); });

    // Each packet carries half the integration's samples (N_SAMPLES/N_SPLITS = 128).
    // heap_counter 0 → split 0, heap_counter 1 → split 1.
    const int samples_per_pkt = N_SAMPLES / N_SPLITS;
    const size_t payload_bytes = (size_t)samples_per_pkt * N_ANT * N_POL * sizeof(uint16_t);
    std::vector<uint8_t> payload_data(payload_bytes);
    for (size_t i = 0; i < payload_bytes; i += 2)
    {
        payload_data[i] = static_cast<uint8_t>(SIGNAL);
        payload_data[i + 1] = 0;
    }

    const uint64_t chan_info = (uint64_t(1) << 16) | uint64_t(N_ANT);

    for (int pkt_idx = 0; pkt_idx < N_SPLITS; ++pkt_idx)
    {
        auto pkt = SpeadPacket()
                       .item(0x0001, pkt_idx) // heap_counter = pkt_idx (→ split pkt_idx)
                       .item(0x0004, payload_bytes)
                       .item(0x1027, 0)
                       .item(0x1600, 0)
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, 0)
                       .item(0x3300, 0)
                       .payload(payload_data)
                       .build();
        ASSERT_TRUE(c.pushPacket(pkt));
        ASSERT_TRUE(c.processPacket());
    }

    for (int i = 0; i < 500 && !got.load(std::memory_order_acquire); ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));

    c.cleanUp();

    ASSERT_TRUE(got.load()) << "callback never fired within 5 s";

    // TCC accumulates across splits: total = N_SAMPLES * SIGNAL^2 + 0i
    const int32_t expected_re = (int32_t)N_SAMPLES * SIGNAL * SIGNAL;
    for (int bl = 0; bl < N_BASELINES; ++bl)
        for (int py = 0; py < N_POL; ++py)
            for (int px = 0; px < N_POL; ++px)
            {
                auto v = vis_out[(bl * N_POL + py) * N_POL + px];
                EXPECT_EQ(v.real(), expected_re) << "bl=" << bl << " py=" << py << " px=" << px;
                EXPECT_EQ(v.imag(), 0) << "bl=" << bl << " py=" << py << " px=" << px;
            }
}
