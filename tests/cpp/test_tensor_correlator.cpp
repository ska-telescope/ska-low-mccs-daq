// GPU correlator tests (TensorCorrelatorData.cpp).
//
// This target is only built when the CUDA toolkit, cudawrappers, libtcc AND a
// physical GPU are present (see tests/cpp/CMakeLists.txt, BUILD_GPU_TESTS). It
// links the real cudawrappers/libtcc - not the cudawrappers stub the
// TccSplitRing test uses.
//
// packetFilter is pure SPEAD parsing and needs no device. The correlation
// round-trip needs a GPU at run time; it GTEST_SKIPs if none is visible (the
// build node and run node may differ), so the binary is safe to run anywhere.

#include <atomic>
#include <chrono>
#include <cmath>
#include <complex>
#include <cuda_runtime.h>
#include <gtest/gtest.h>
#include <iostream>
#include <random>
#include <thread>
#include <vector>

#include "DAQ.h"
// The .cpp is #included directly (single TU) rather than declared via its
// header so the extern "C" consumer factory defined in TensorCorrelatorData.h
// (the pattern every cdaq consumer header uses, relied on by dlsym) is emitted
// exactly once. Compiling TensorCorrelatorData.cpp as a separate object as well
// would define that factory twice and break linking. Mirrors test_raw_data_consumer.
//
// split_ring is private in TensorCorrelatorData, but TestableTensorCorrelator below
// needs it for split-ring backpressure (pushPacketWhenReady). Promote private ->
// protected for this test translation unit only, so the test can subclass and reach
// it without widening the production header's access. Scoped to the include below.
#define private protected
#include "TensorCorrelatorData.cpp"
#undef private
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
// the std::function in a static slot and installs a trampoline - safe as long
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

    // Push pkt only once the split ring slot for global_split is EMPTY.
    // When ring_size < nof_splits the ring cycles multiple times per integration;
    // the producer must wait for the GPU thread to release a slot before reusing it.
    bool pushPacketWhenReady(const std::vector<uint8_t> &pkt, uint64_t global_split,
                             int timeout_ms = 2000)
    {
        if (split_ring)
        {
            const uint32_t slot_idx = (uint32_t)(global_split % split_ring->ring_size());
            for (int i = 0; i * 100 < timeout_ms * 1000; ++i)
            {
                if (split_ring->get_slot(slot_idx).state.load(std::memory_order_acquire) == SlotState::EMPTY)
                    break;
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            }
        }
        return pushPacket(pkt) && processPacket();
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
    // Ring is 4× smaller than the number of splits, so each integration cycles
    // through the ring 4 times - matching the production scenario where the GPU
    // thread releases and reuses slots mid-integration.
    constexpr int RING_SIZE = N_SPLITS / 4;
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
        {"nbuffers", RING_SIZE},
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

    // Payload layout: [samples_per_pkt][N_ANT][N_POL] of uint16_t (complex<int8_t>).
    // Each antenna carries a constant complex sample with a distinct (real, imag),
    // so no two antennas are scalar multiples of one another:
    //   ant 0: (  SIGNAL, 4*SIGNAL)
    //   ant 1: (2*SIGNAL, 3*SIGNAL)
    //   ant 2: (3*SIGNAL, 2*SIGNAL)
    //   ant 3: (4*SIGNAL,   SIGNAL)
    // This produces distinct, genuinely complex cross-correlation values for
    // most baselines.
    const int ant_re[N_ANT] = {SIGNAL, 2 * SIGNAL, 3 * SIGNAL, 4 * SIGNAL};
    const int ant_im[N_ANT] = {4 * SIGNAL, 3 * SIGNAL, 2 * SIGNAL, SIGNAL};

    const int samples_per_pkt = N_SAMPLES / N_SPLITS;
    const size_t payload_bytes = (size_t)samples_per_pkt * N_ANT * N_POL * sizeof(uint16_t);
    std::vector<uint8_t> payload_data(payload_bytes);
    for (size_t i = 0; i < payload_bytes; i += 2)
    {
        const int ant = (i / 2 / N_POL) % N_ANT;
        payload_data[i] = static_cast<uint8_t>(ant_re[ant]);
        payload_data[i + 1] = static_cast<uint8_t>(ant_im[ant]);
    }

    const uint64_t chan_info = (uint64_t(1) << 16) | uint64_t(N_ANT);

    // pushPacketWhenReady blocks until the target slot is EMPTY before writing.
    // For pkt_idx < RING_SIZE all slots start EMPTY; for later packets the GPU
    // thread must have released the slot before the producer can fill it again.
    for (int pkt_idx = 0; pkt_idx < N_SPLITS; ++pkt_idx)
    {
        auto pkt = SpeadPacket()
                       .item(0x0001, pkt_idx)
                       .item(0x0004, payload_bytes)
                       .item(0x1027, 0)
                       .item(0x1600, 0)
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, 0)
                       .item(0x3300, 0)
                       .payload(payload_data)
                       .build();
        ASSERT_TRUE(c.pushPacketWhenReady(pkt, (uint64_t)pkt_idx));
    }

    for (int i = 0; i < 500 && !got.load(std::memory_order_acquire); ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));

    c.cleanUp();

    ASSERT_TRUE(got.load()) << "callback never fired within 5 s";

    // TCC computes V_{rx,ry} = sum_t conj(s_rx[t]) * s_ry[t]  (rx >= ry).
    // With constant DC signals: vis[bl(rx,ry)] = N_SAMPLES * conj(s[rx]) * s[ry]
    //   real part: N_SAMPLES * (re_rx*re_ry + im_rx*im_ry)
    //   imag part: N_SAMPLES * (re_rx*im_ry - im_rx*re_ry)
    // Baseline ordering: bl = rx*(rx+1)/2 + ry, rx >= ry.
    int bl = 0;
    for (int rx = 0; rx < N_ANT; ++rx)
    {
        for (int ry = 0; ry <= rx; ++ry, ++bl)
        {
            const int32_t expected_re = (int32_t)N_SAMPLES *
                                        (ant_re[rx] * ant_re[ry] + ant_im[rx] * ant_im[ry]);
            const int32_t expected_im = (int32_t)N_SAMPLES *
                                        (ant_re[rx] * ant_im[ry] - ant_im[rx] * ant_re[ry]);
            for (int py = 0; py < N_POL; ++py)
                for (int px = 0; px < N_POL; ++px)
                {
                    auto v = vis_out[(bl * N_POL + py) * N_POL + px];
                    EXPECT_EQ(v.real(), expected_re)
                        << "bl=" << bl << " rx=" << rx << " ry=" << ry
                        << " py=" << py << " px=" << px;
                    EXPECT_EQ(v.imag(), expected_im)
                        << "bl=" << bl << " rx=" << rx << " ry=" << ry
                        << " py=" << py << " px=" << px;
                }
        }
    }
}

// Random-noise decorrelation: fill every (sample, antenna, pol) element with
// *independent* pseudo-random noise of the same variance and run one integration.
// Independent noise streams decorrelate, so the normalised cross-correlation
// coefficient between two different antennas
//     rho(rx,ry) = |V_rx,ry| / sqrt(V_rx,rx * V_ry,ry)
// sits at the interferometric noise floor rho_rms = 1/sqrt(N_SAMPLES): each of the
// real/imag parts of the cross term is a sum of N zero-mean products so its std
// grows as sqrt(N), while the auto-power grows as N. This asserts the correlator
// does not manufacture spurious correlation out of uncorrelated inputs.
//
// The tolerance is derived from that floor rather than hard-coded. |rho| per
// baseline is Rayleigh-distributed (magnitude of a 2-D Gaussian), so across the M
// cross coefficients checked the largest is ~rho_rms * sqrt(ln M); we allow a
// safety factor above that. The PRNG seed is fixed, so the payload — and thus the
// exact visibilities — are deterministic and the test is reproducible.
//
// N_SAMPLES=65536 exceeds a single 9000-byte packet (64 antennas × 2 pols is
// 256 B/sample), so the integration is streamed across N_SPLITS packets, each
// carrying SAMPLES_PER_PKT samples - the same multi-split path as
// VisibilityRoundTripMultiSplit above.
//
// Because every antenna/pol carries the same noise variance, all auto powers
// are ~equal, so the normalisation (and hence the assertion) is insensitive to
// which of the two visibility pol axes maps to which receiver.
TEST_F(TensorCorrelatorGpuTest, RandomNoiseYieldsLowCorrelation)
{
    constexpr int A = 64;              // noise amplitude: int8 samples drawn from [-A, A]
    constexpr int N_ANT = 64;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 65536;   // closest power of two to 50k
    constexpr int SAMPLES_PER_PKT = 32; // payload = 32*64*2*2 = 8192 B < max_packet_size
    constexpr int N_SPLITS = N_SAMPLES / SAMPLES_PER_PKT; // 2048 packets / integration
    constexpr int RING_SIZE = 64;      // divides N_SPLITS; keeps the split ring small
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
        {"nbuffers", RING_SIZE},
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

    // Deterministic PRNG -> independent int8 noise in [-A, A] for the real and
    // imag byte of every payload element. The fixed seed keeps the payload (and
    // thus the exact visibilities) reproducible across runs on this toolchain.
    std::mt19937_64 rng(0x123456789abcdefULL);
    std::uniform_int_distribution<int> noise(-A, A);
    auto next_noise = [&]() -> uint8_t
    {
        return static_cast<uint8_t>(static_cast<int8_t>(noise(rng)));
    };

    const uint64_t chan_info = (uint64_t(1) << 16) | uint64_t(N_ANT);

    // Payload per packet: SAMPLES_PER_PKT × N_ANT × N_POL × uint16_t. Refilled
    // with fresh randoms every packet, so the whole integration is an
    // independent noise stream per (split, sample, antenna, pol).
    const size_t payload_bytes = (size_t)SAMPLES_PER_PKT * N_ANT * N_POL * sizeof(uint16_t);
    std::vector<uint8_t> payload_data(payload_bytes);

    // pushPacketWhenReady blocks until the target ring slot is EMPTY, so the
    // producer can safely reuse slots as the GPU thread releases them.
    for (int pkt_idx = 0; pkt_idx < N_SPLITS; ++pkt_idx)
    {
        for (size_t i = 0; i < payload_bytes; i += 2)
        {
            payload_data[i] = next_noise();     // real
            payload_data[i + 1] = next_noise(); // imag
        }

        auto pkt = SpeadPacket()
                       .item(0x0001, pkt_idx)
                       .item(0x0004, payload_bytes)
                       .item(0x1027, 0)
                       .item(0x1600, 0)
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, 0)
                       .item(0x3300, 0)
                       .payload(payload_data)
                       .build();
        ASSERT_TRUE(c.pushPacketWhenReady(pkt, (uint64_t)pkt_idx));
    }

    for (int i = 0; i < 500 && !got.load(std::memory_order_acquire); ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));

    c.cleanUp();

    ASSERT_TRUE(got.load()) << "callback never fired within 5 s";

    auto vis_at = [&](int bl, int py, int px)
    { return vis_out[(bl * N_POL + py) * N_POL + px]; };
    auto bl_index = [](int rx, int ry)
    { return rx * (rx + 1) / 2 + ry; };

    // Auto-correlation power for antenna a, pol p: diagonal baseline bl(a,a),
    // entry [p][p]. Must be large and positive (noise carries real power).
    double auto_pow[N_ANT][N_POL];
    for (int a = 0; a < N_ANT; ++a)
        for (int p = 0; p < N_POL; ++p)
        {
            auto v = vis_at(bl_index(a, a), p, p);
            EXPECT_GT(v.real(), 0) << "auto power ant=" << a << " pol=" << p;
            auto_pow[a][p] = (double)v.real();
        }

    // Interferometric noise floor for independent noise: rho_rms = 1/sqrt(N).
    const double noise_floor = 1.0 / std::sqrt((double)N_SAMPLES);
    // |rho| is Rayleigh, so the largest of the M cross coefficients checked is
    // ~noise_floor*sqrt(ln M); allow a safety factor above that expected maximum.
    const size_t M = (size_t)(N_ANT * (N_ANT - 1) / 2) * N_POL * N_POL;
    const double tol = 4.0 * noise_floor * std::sqrt(std::log((double)M));

    // Cross baselines (rx != ry): every normalised coefficient must sit within the
    // derived noise-floor tolerance for every pol combination.
    double max_rho = 0.0, sum_sq = 0.0;
    size_t count = 0;
    for (int rx = 0; rx < N_ANT; ++rx)
        for (int ry = 0; ry < rx; ++ry)
        {
            const int bl = bl_index(rx, ry);
            for (int py = 0; py < N_POL; ++py)
                for (int px = 0; px < N_POL; ++px)
                {
                    auto v = vis_at(bl, py, px);
                    const double mag = std::abs(std::complex<double>(v.real(), v.imag()));
                    const double denom = std::sqrt(auto_pow[rx][py] * auto_pow[ry][px]);
                    ASSERT_GT(denom, 0.0);
                    const double rho = mag / denom;
                    max_rho = std::max(max_rho, rho);
                    sum_sq += rho * rho;
                    ++count;
                    EXPECT_LT(rho, tol)
                        << "rho=" << rho << " bl=" << bl << " rx=" << rx
                        << " ry=" << ry << " py=" << py << " px=" << px;
                }
        }
    // The measured decorrelation must actually sit at the predicted floor — not
    // merely below the loose per-baseline tolerance, and not suspiciously zero.
    const double rms = std::sqrt(sum_sq / count);
    EXPECT_NEAR(rms, noise_floor, 0.25 * noise_floor)
        << "cross-correlation RMS " << rms << " departs from the 1/sqrt(N) floor " << noise_floor;

    std::cout << "[noise] floor(1/sqrt N)=" << noise_floor << " rms=" << rms
              << " max=" << max_rho << " tol=" << tol << " M=" << M << std::endl;
}

// Back-to-back integrations, each streamed as many packets: push two full
// integrations of N_SPLITS packets apiece (heap_counter 0..2*N_SPLITS-1) carrying
// different constant DC signals (SIGNAL_A then SIGNAL_B) and assert the callback
// fires twice, each delivering its own integration's visibilities.
//
// This exercises the per-integration accumulate/reset across split boundaries and
// the ring cycling between integrations (RING_SIZE < N_SPLITS, so slots are reused
// mid- and across integrations). If accumulation leaked across integrations,
// integration B would read N_SAMPLES*(A^2+B^2) instead of N_SAMPLES*B^2; distinct
// signals catch a missing per-integration reset, and two callbacks confirm
// consumer_integ_ and the producer's integration index stay in lock-step.
TEST_F(TensorCorrelatorGpuTest, BackToBackIntegrations)
{
    constexpr int8_t SIGNAL_A = 7;
    constexpr int8_t SIGNAL_B = 11;
    constexpr int N_ANT = 4;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256 * 16;                  // per integration
    constexpr int N_SPLITS = 64;                         // packets per integration
    constexpr int SAMPLES_PER_PKT = N_SAMPLES / N_SPLITS; // 64 samples/packet
    constexpr int RING_SIZE = N_SPLITS / 4;              // ring cycles 4x per integration
    constexpr int N_BASELINES = N_ANT * (N_ANT + 1) / 2;
    const size_t vis_len = (size_t)N_BASELINES * N_POL * N_POL;

    json config = {
        {"nof_antennas", N_ANT},   {"nof_channels", 1}, {"nof_fine_channels", 1},
        {"nof_tiles", 1},          {"nof_active_tiles", 1}, {"nof_samples", N_SAMPLES},
        {"nof_pols", N_POL},       {"max_packet_size", 9000},
        {"nof_splits", N_SPLITS},  {"nbuffers", RING_SIZE},
    };

    TestableTensorCorrelator c;
    ASSERT_TRUE(c.initialiseConsumer(config));

    // Each integration delivers one visibility buffer; keep them all in arrival order.
    std::vector<std::vector<std::complex<int32_t>>> results;
    std::atomic<int> ncb{0};
    c.setCapturingCallback([&](void *data, double, void *)
                           {
        auto *v = static_cast<std::complex<int32_t> *>(data);
        results.emplace_back(v, v + vis_len);
        ncb.fetch_add(1, std::memory_order_release); });

    const uint64_t chan_info = (uint64_t(1) << 16) | uint64_t(N_ANT);
    const size_t payload_bytes = (size_t)SAMPLES_PER_PKT * N_ANT * N_POL * sizeof(uint16_t);

    // Two integrations of N_SPLITS packets each. heap_counter (== global_split here)
    // runs 0..2*N_SPLITS-1: counters [0,N_SPLITS) map to integ 0, [N_SPLITS,2N) to
    // integ 1. Same split-streaming/backpressure path as VisibilityRoundTripMultiSplit.
    for (int integ = 0; integ < 2; ++integ)
    {
        const uint8_t sig = (integ == 0) ? (uint8_t)SIGNAL_A : (uint8_t)SIGNAL_B;
        std::vector<uint8_t> payload(payload_bytes);
        for (size_t i = 0; i < payload_bytes; i += 2)
        {
            payload[i] = sig; // real
            payload[i + 1] = 0; // imag
        }

        for (int s = 0; s < N_SPLITS; ++s)
        {
            const int counter = integ * N_SPLITS + s;
            auto pkt = SpeadPacket()
                           .item(0x0001, counter)
                           .item(0x0004, payload_bytes)
                           .item(0x1027, 0)
                           .item(0x1600, 0)
                           .item(0x2004, 0x4)
                           .item(0x2002, chan_info)
                           .item(0x2001, 0)
                           .item(0x3300, 0)
                           .payload(payload)
                           .build();
            ASSERT_TRUE(c.pushPacketWhenReady(pkt, (uint64_t)counter));
        }
    }

    for (int i = 0; i < 500 && ncb.load(std::memory_order_acquire) < 2; ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));

    c.cleanUp();

    ASSERT_EQ(ncb.load(), 2) << "expected exactly two integration callbacks";

    // Constant DC signal -> every visibility entry = N_SAMPLES * SIGNAL^2 + 0i,
    // independently per integration.
    const int32_t exp_a = (int32_t)N_SAMPLES * SIGNAL_A * SIGNAL_A;
    const int32_t exp_b = (int32_t)N_SAMPLES * SIGNAL_B * SIGNAL_B;
    for (size_t k = 0; k < vis_len; ++k)
    {
        EXPECT_EQ(results[0][k].real(), exp_a) << "integ 0 entry " << k;
        EXPECT_EQ(results[0][k].imag(), 0) << "integ 0 entry " << k;
        EXPECT_EQ(results[1][k].real(), exp_b) << "integ 1 entry " << k;
        EXPECT_EQ(results[1][k].imag(), 0) << "integ 1 entry " << k;
    }
}

// Missing-packet resilience: deliver only the first half of an integration's
// time samples (one of the two time-chunk packets is "lost"), then let
// processPacket time out on the drained ring buffer. The pull-timeout path calls
// split_ring->flush(), forcing the half-filled (FILLING) slot to READY so the GPU
// thread drains it instead of polling that split forever. The undelivered samples
// were zeroed when the slot was opened, so the result is a valid reduced
// correlation rather than a hang.
TEST_F(TensorCorrelatorGpuTest, PartialIntegrationFlushesRatherThanHangs)
{
    constexpr int8_t SIGNAL = 10;
    constexpr int N_ANT = 4;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256;
    constexpr int HALF = N_SAMPLES / 2; // samples actually delivered
    constexpr int N_BASELINES = N_ANT * (N_ANT + 1) / 2;

    json config = {
        {"nof_antennas", N_ANT},   {"nof_channels", 1}, {"nof_fine_channels", 1},
        {"nof_tiles", 1},          {"nof_active_tiles", 1}, {"nof_samples", N_SAMPLES},
        {"nof_pols", N_POL},       {"max_packet_size", 9000},
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

    const uint64_t chan_info = (uint64_t(1) << 16) | uint64_t(N_ANT);

    // One packet carrying only HALF the integration's samples (heap_counter 0):
    // samples_in_packet=HALF => pkts_per_integ=2, and the second (counter 1)
    // packet is deliberately never sent, leaving the split half-filled.
    const size_t payload_bytes = (size_t)HALF * N_ANT * N_POL * sizeof(uint16_t);
    std::vector<uint8_t> payload(payload_bytes);
    for (size_t i = 0; i < payload_bytes; i += 2)
    {
        payload[i] = (uint8_t)SIGNAL; // real
        payload[i + 1] = 0; // imag
    }

    auto pkt = SpeadPacket()
                   .item(0x0001, 0)
                   .item(0x0004, payload_bytes)
                   .item(0x1027, 0)
                   .item(0x1600, 0)
                   .item(0x2004, 0x4)
                   .item(0x2002, chan_info)
                   .item(0x2001, 0)
                   .item(0x3300, 0)
                   .payload(payload)
                   .build();
    ASSERT_TRUE(c.pushPacket(pkt));
    ASSERT_TRUE(c.processPacket());

    // No further packets: drive processPacket so its pull_timeout expires and
    // flushes the ring, releasing the half-filled slot to the GPU thread.
    for (int i = 0; i < 500 && !got.load(std::memory_order_acquire); ++i)
    {
        c.processPacket(); // returns false on timeout, flushing the ring
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    c.cleanUp();

    ASSERT_TRUE(got.load()) << "flush did not release the partial integration; consumer hung";

    // Only HALF the samples carried signal; the rest were zero-filled, so every
    // entry is HALF * SIGNAL^2 + 0i (constant DC signal, identical on all antennas).
    const int32_t expected_re = (int32_t)HALF * SIGNAL * SIGNAL;
    for (size_t k = 0; k < (size_t)N_BASELINES * N_POL * N_POL; ++k)
    {
        EXPECT_EQ(vis_out[k].real(), expected_re) << "entry " << k;
        EXPECT_EQ(vis_out[k].imag(), 0) << "entry " << k;
    }
}

// Multi-tile assembly: two tiles each deliver their own antenna block for the
// same time-chunk, exercising the tile_id * nof_antennas + start_antenna_id
// receiver-offset mapping in processPacket/write_data. The correlator must merge
// both tiles into one (N_TILES * ANT_PER_TILE)-receiver integration and correlate
// across tiles.
//
// This runs at heap_counter 0 (the natural start), which the wrap-detection fix
// makes safe for >1 tile. Note it does not, on its own, gate that fix: a single
// one-packet-per-tile integration would pass even with the old per-tile
// over-count, because the inflated global_split (offset by a multiple of 2^24)
// aliases back to the same ring slot. It verifies assembly correctness; the
// counter fix's teeth are in the wrap/reference-latch reasoning.
TEST_F(TensorCorrelatorGpuTest, MultiTileVisibilityRoundTrip)
{
    constexpr int N_TILES = 2;
    constexpr int ANT_PER_TILE = 2;
    constexpr int N_RECV = N_TILES * ANT_PER_TILE; // 4 receivers total
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256;
    constexpr int N_BASELINES = N_RECV * (N_RECV + 1) / 2;

    json config = {
        {"nof_antennas", ANT_PER_TILE}, {"nof_channels", 1}, {"nof_fine_channels", 1},
        {"nof_tiles", N_TILES},         {"nof_active_tiles", N_TILES}, {"nof_samples", N_SAMPLES},
        {"nof_pols", N_POL},            {"max_packet_size", 9000},
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

    // Distinct real amplitude per global receiver g = tile*ANT_PER_TILE + ant.
    const int recv_amp[N_RECV] = {3, 5, 7, 11};

    // 1 channel, start_antenna 0, ANT_PER_TILE antennas per tile.
    const uint64_t chan_info = (uint64_t(1) << 16) | uint64_t(ANT_PER_TILE);
    const size_t payload_bytes = (size_t)N_SAMPLES * ANT_PER_TILE * N_POL * sizeof(uint16_t);

    for (int tile = 0; tile < N_TILES; ++tile)
    {
        std::vector<uint8_t> payload(payload_bytes);
        for (size_t i = 0; i < payload_bytes; i += 2)
        {
            const int ant = (int)((i / 2 / N_POL) % ANT_PER_TILE);
            payload[i] = (uint8_t)recv_amp[tile * ANT_PER_TILE + ant]; // real
            payload[i + 1] = 0; // imag
        }
        const uint64_t tpm_info = ((uint64_t)tile << 32); // tile_id at bits[39:32], pol_id 0
        auto pkt = SpeadPacket()
                       .item(0x0001, 0) // heap_counter = 0 (both tiles, same time-chunk)
                       .item(0x0004, payload_bytes)
                       .item(0x1027, 0)
                       .item(0x1600, 0)
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, tpm_info)
                       .item(0x3300, 0)
                       .payload(payload)
                       .build();
        ASSERT_TRUE(c.pushPacket(pkt));
        ASSERT_TRUE(c.processPacket());
    }

    for (int i = 0; i < 500 && !got.load(std::memory_order_acquire); ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));

    c.cleanUp();

    ASSERT_TRUE(got.load()) << "callback never fired; multi-tile assembly did not complete";

    // Constant real signals: vis[bl(gx,gy)] = N_SAMPLES * amp[gx] * amp[gy] + 0i
    // for every pol pair. Correct values on cross-tile baselines (gx and gy in
    // different tiles) confirm both tiles landed at the right receiver offsets.
    auto bl_index = [](int gx, int gy) { return gx * (gx + 1) / 2 + gy; };
    for (int gx = 0; gx < N_RECV; ++gx)
        for (int gy = 0; gy <= gx; ++gy)
        {
            const int bl = bl_index(gx, gy);
            const int32_t expected_re = (int32_t)N_SAMPLES * recv_amp[gx] * recv_amp[gy];
            for (int py = 0; py < N_POL; ++py)
                for (int px = 0; px < N_POL; ++px)
                {
                    auto v = vis_out[(bl * N_POL + py) * N_POL + px];
                    EXPECT_EQ(v.real(), expected_re) << "bl=" << bl << " gx=" << gx << " gy=" << gy;
                    EXPECT_EQ(v.imag(), 0) << "bl=" << bl << " gx=" << gx << " gy=" << gy;
                }
        }
}

// The integration reference-counter must latch on the *first* packet even when
// that packet's absolute heap counter is 0, so no later packet can reset it.
//
// For example: the stream's first packet is the pol-1 packet at
// heap_counter 0 - its pol-0 sibling was reordered or lost. The reference must
// still latch to 0 here. If it does not, the second packet (counter 1) becomes the
// reference and every packet then maps one integration too early: two packets
// collide on split 0 (the later one dropped as already-consumed) and the final
// integration's slot never fills, so the consumer stalls and that integration is
// lost. This is visible at the callback level, unlike a mis-counted wrap - a wrap
// offsets global_split by a multiple of 2^24, which the power-of-two ring size
// divides, so it aliases back to the correct slot; a one-integration shift does not.
//
// Push three single-packet integrations (heap_counter 0,1,2) with distinct DC
// signals and require all three back, in order, each with its own values.
TEST_F(TensorCorrelatorGpuTest, ReferenceCounterLatchesOnCounterZeroStart)
{
    constexpr int8_t SIGNAL[3] = {5, 6, 7}; // one distinct DC signal per integration
    constexpr int N_ANT = 4;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256;
    constexpr int N_BASELINES = N_ANT * (N_ANT + 1) / 2;
    const size_t vis_len = (size_t)N_BASELINES * N_POL * N_POL;

    json config = {
        {"nof_antennas", N_ANT},   {"nof_channels", 1}, {"nof_fine_channels", 1},
        {"nof_tiles", 1},          {"nof_active_tiles", 1}, {"nof_samples", N_SAMPLES},
        {"nof_pols", N_POL},       {"max_packet_size", 9000},
    };

    TestableTensorCorrelator c;
    ASSERT_TRUE(c.initialiseConsumer(config));

    std::vector<std::vector<std::complex<int32_t>>> results;
    std::atomic<int> ncb{0};
    c.setCapturingCallback([&](void *data, double, void *)
                           {
        auto *v = static_cast<std::complex<int32_t> *>(data);
        results.emplace_back(v, v + vis_len);
        ncb.fetch_add(1, std::memory_order_release); });

    const uint64_t chan_info = (uint64_t(1) << 16) | uint64_t(N_ANT);
    const size_t payload_bytes = (size_t)N_SAMPLES * N_ANT * N_POL * sizeof(uint16_t);

    for (int integ = 0; integ < 3; ++integ)
    {
        std::vector<uint8_t> payload(payload_bytes);
        for (size_t i = 0; i < payload_bytes; i += 2)
        {
            payload[i] = (uint8_t)SIGNAL[integ]; // real
            payload[i + 1] = 0; // imag
        }
        // First packet (counter 0) carries pol_id 1 (tpm_info low byte); the rest
        // pol_id 0. Only the counter-0 packet's pol matters to the old heuristic.
        const uint64_t tpm_info = (integ == 0) ? 1u : 0u;
        auto pkt = SpeadPacket()
                       .item(0x0001, integ) // heap_counter 0, 1, 2
                       .item(0x0004, payload_bytes)
                       .item(0x1027, 0)
                       .item(0x1600, 0)
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, tpm_info)
                       .item(0x3300, 0)
                       .payload(payload)
                       .build();
        ASSERT_TRUE(c.pushPacket(pkt));
        ASSERT_TRUE(c.processPacket());
    }

    for (int i = 0; i < 500 && ncb.load(std::memory_order_acquire) < 3; ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));

    c.cleanUp();

    ASSERT_EQ(ncb.load(), 3)
        << "expected three integrations; a lower count means a counter-0 first "
           "packet caused the reference to be overwritten and an integration dropped";

    // Each integration's constant DC signal -> every entry = N_SAMPLES * SIGNAL^2.
    for (int integ = 0; integ < 3; ++integ)
    {
        const int32_t expected_re = (int32_t)N_SAMPLES * SIGNAL[integ] * SIGNAL[integ];
        for (size_t k = 0; k < vis_len; ++k)
        {
            EXPECT_EQ(results[integ][k].real(), expected_re) << "integ " << integ << " entry " << k;
            EXPECT_EQ(results[integ][k].imag(), 0) << "integ " << integ << " entry " << k;
        }
    }
}

// A stream break (producer timeout -> flush/reset) between integrations must not
// wedge the pipeline: the next integration has to be delivered.
//
// Regression for the asymmetric-reset deadlock: after delivering integration X the
// consumer advances to consumer_integ_=1 and blocks polling the next integration's
// slot. On the timeout the producer resets its reference (so the next integration
// re-maps to global_split 0), but the consumer's consumed_up_to_/consumer_integ_
// only reset at an integration boundary it can no longer reach — so the new
// integration's global_split-0 packets are dropped and the consumer stalls forever.
// The fix has the consumer observe the reset while blocked and restart numbering.
TEST_F(TensorCorrelatorGpuTest, NewIntegrationAfterBreakIsDelivered)
{
    constexpr int8_t SIG_X = 5;
    constexpr int8_t SIG_Y = 7;
    constexpr int N_ANT = 4;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256;
    constexpr int N_BASELINES = N_ANT * (N_ANT + 1) / 2;
    const size_t vis_len = (size_t)N_BASELINES * N_POL * N_POL;

    json config = {
        {"nof_antennas", N_ANT},   {"nof_channels", 1}, {"nof_fine_channels", 1},
        {"nof_tiles", 1},          {"nof_active_tiles", 1}, {"nof_samples", N_SAMPLES},
        {"nof_pols", N_POL},       {"max_packet_size", 9000},
    };

    TestableTensorCorrelator c;
    ASSERT_TRUE(c.initialiseConsumer(config));

    std::vector<std::vector<std::complex<int32_t>>> results;
    std::atomic<int> ncb{0};
    c.setCapturingCallback([&](void *data, double, void *)
                           {
        auto *v = static_cast<std::complex<int32_t> *>(data);
        results.emplace_back(v, v + vis_len);
        ncb.fetch_add(1, std::memory_order_release); });

    const size_t payload_bytes = (size_t)N_SAMPLES * N_ANT * N_POL * sizeof(uint16_t);

    // Send one full single-packet integration on the given channel, fresh counter 0.
    auto send_integration = [&](uint16_t channel, uint8_t sig)
    {
        const uint64_t chan_info =
            ((uint64_t)channel << 24) | (uint64_t(1) << 16) | uint64_t(N_ANT);
        std::vector<uint8_t> payload(payload_bytes);
        for (size_t i = 0; i < payload_bytes; i += 2) { payload[i] = sig; payload[i + 1] = 0; }
        auto pkt = SpeadPacket()
                       .item(0x0001, 0)
                       .item(0x0004, payload_bytes)
                       .item(0x1027, 0)
                       .item(0x1600, 0)
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, 0)
                       .item(0x3300, 0)
                       .payload(payload)
                       .build();
        EXPECT_TRUE(c.pushPacket(pkt));
        EXPECT_TRUE(c.processPacket());
    };

    // Integration X on channel 0.
    send_integration(0, SIG_X);
    for (int i = 0; i < 500 && ncb.load(std::memory_order_acquire) < 1; ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    ASSERT_EQ(ncb.load(), 1) << "first integration never delivered";

    // Break: drive processPacket timeouts so the ring flushes and both sides reset.
    for (int i = 0; i < 3; ++i)
    {
        c.processPacket(); // empty ring -> pull_timeout expires -> flush()/reset
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }

    // Integration Y on channel 5, fresh counter — must be delivered, not dropped.
    send_integration(5, SIG_Y);
    for (int i = 0; i < 500 && ncb.load(std::memory_order_acquire) < 2; ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));

    c.cleanUp();

    ASSERT_EQ(ncb.load(), 2) << "second integration after the break was not delivered";
    const int32_t exp_y = (int32_t)N_SAMPLES * SIG_Y * SIG_Y;
    for (size_t k = 0; k < vis_len; ++k)
    {
        EXPECT_EQ(results[1][k].real(), exp_y) << "post-break integration entry " << k;
        EXPECT_EQ(results[1][k].imag(), 0) << "post-break integration entry " << k;
    }
}
