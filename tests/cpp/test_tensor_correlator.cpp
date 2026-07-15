// GPU correlator tests (TensorCorrelatorData.cpp).
//
// This target is only built when the CUDA toolkit, cudawrappers, libtcc AND a
// physical GPU are present (see tests/cpp/CMakeLists.txt, BUILD_GPU_TESTS). It
// links the real cudawrappers/libtcc - not the cudawrappers stub the
// test_tcc_double_buffer unit test uses.
//
// packetFilter is pure SPEAD parsing and needs no device. The correlation
// round-trip needs a GPU at run time; it GTEST_SKIPs if none is visible (the
// build node and run node may differ), so the binary is safe to run anywhere.
//
// ── How delivery works in the double-buffer pipeline ─────────────────────────
// A buffer is released to the consumer only when either
//   (a) the *next* integration starts - write_data_single_channel detects the
//       boundary from the packet TIMESTAMP (packet_index==0 and
//       timestamp >= ref_time + (nof_samples-1)*1.08e-6), marks the older buffer
//       ready and advances the producer; or
//   (b) processPacket() hits a pull timeout on a drained ring and calls
//       double_buffer->finish_write(), which marks the in-flight buffer ready.
// So every round-trip test here:
//   * separates integrations with distinct, advancing SPEAD timestamps, and
//   * drives processPacket() through pull timeouts at the end to flush the tail
//     integration (finish_write), exactly as the production timeout path does.
// A single integration is simply many packets whose heap counters map, via
// packet_index = (counter - reference) % (nof_samples / samples_in_packet), to
// successive sample offsets in one buffer.

#include <atomic>
#include <chrono>
#include <cmath>
#include <complex>
#include <cuda_runtime.h>
#include <functional>
#include <gtest/gtest.h>
#include <iostream>
#include <random>
#include <thread>
#include <vector>

#include "TensorCorrelatorData.h"
#include "spead_test_util.h"

namespace
{
    bool gpu_visible()
    {
        int count = 0;
        return cudaGetDeviceCount(&count) == cudaSuccess && count > 0;
    }

    // SPEAD timestamp (item 0x1600) for integration `integ`. packet_time =
    // sync_time + timestamp*1.08e-6, and the buffer swaps integrations when the
    // time advances by >= (nof_samples-1)*1.08e-6. Spacing integrations by
    // 4*nof_samples time-units clears that threshold with a comfortable margin;
    // the (integ+1) base keeps the first integration's time strictly positive so
    // it never trips the "belongs to previous buffer" (ref_time > timestamp) path
    // against a freshly-initialised buffer (ref_time == 0).
    uint64_t ts_for(int integ, int nof_samples)
    {
        return (uint64_t)(integ + 1) * (uint64_t)nof_samples * 4;
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
// the std::function in a static slot and installs a trampoline.
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

    // Push one packet and hand it straight to processPacket()
    bool feed(const std::vector<uint8_t> &pkt)
    {
        return pushPacket(pkt) && processPacket();
    }

    // Drive processPacket() against a drained ring so its pull timeout fires
    // finish_write() and flushes the pending buffer(s) to the GPU thread. Stops
    // as soon as `done` is satisfied or the deadline passes.
    template <class Pred>
    void driveUntil(Pred done, int timeout_ms = 5000)
    {
        for (int i = 0; i * 10 < timeout_ms && !done(); ++i)
        {
            processPacket(); // empty ring -> pull_timeout -> finish_write()
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
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
// constant DC signal (SIGNAL + 0j) on every antenna/pol/time sample, drive the
// pull-timeout flush so the GPU correlator runs one integration, and check the
// delivered visibilities.
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
                   .item(0x0001, 0)                       // heap_counter: packet_index=0, counter=0
                   .item(0x0004, payload_bytes)           // pkt_len
                   .item(0x1027, 0)                       // sync_time
                   .item(0x1600, ts_for(0, N_SAMPLES))    // timestamp
                   .item(0x2004, 0x4)                     // capture_mode: burst channel
                   .item(0x2002, chan_info)               // channel/antenna info
                   .item(0x2001, 0)                       // tpm_info: tile=0, station=0
                   .item(0x3300, 0)                       // sample_offset
                   .payload(payload_data)
                   .build();

    ASSERT_TRUE(c.feed(pkt));

    // No further packets: drive pull timeouts so finish_write() flushes the
    // single integration to the GPU thread.
    c.driveUntil([&] { return got.load(std::memory_order_acquire); });

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

// Multi-packet round-trip: one integration streamed as many packets, each
// carrying SAMPLES_PER_PKT time samples. heap counters 0..N_PKTS-1 map (via
// packet_index) to successive sample offsets in the SAME double buffer, which is
// flushed once at the end. This exercises the packet_index assembly path and
// accumulation over the whole integration.
//
// Expected result is identical to a single-packet integration because the total
// number of correlated samples is still N_SAMPLES.
TEST_F(TensorCorrelatorGpuTest, VisibilityRoundTripMultiPacket)
{
    constexpr int8_t SIGNAL = 10;
    constexpr int N_ANT = 4;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256 * 16;
    constexpr int N_PKTS = 64;
    constexpr int SAMPLES_PER_PKT = N_SAMPLES / N_PKTS; // 64 samples/packet
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

    std::vector<std::complex<int32_t>> vis_out;
    std::atomic<bool> got{false};
    c.setCapturingCallback([&](void *data, double, void *)
                           {
        auto *v = static_cast<std::complex<int32_t> *>(data);
        vis_out.assign(v, v + N_BASELINES * N_POL * N_POL);
        got.store(true, std::memory_order_release); });

    // Payload layout: [SAMPLES_PER_PKT][N_ANT][N_POL] of uint16_t (complex<int8_t>).
    // Each antenna carries a constant complex sample with a distinct (real, imag),
    // so no two antennas are scalar multiples of one another:
    //   ant 0: (  SIGNAL, 4*SIGNAL)
    //   ant 1: (2*SIGNAL, 3*SIGNAL)
    //   ant 2: (3*SIGNAL, 2*SIGNAL)
    //   ant 3: (4*SIGNAL,   SIGNAL)
    // This produces distinct, complex cross-correlation values for most baselines.
    const int ant_re[N_ANT] = {SIGNAL, 2 * SIGNAL, 3 * SIGNAL, 4 * SIGNAL};
    const int ant_im[N_ANT] = {4 * SIGNAL, 3 * SIGNAL, 2 * SIGNAL, SIGNAL};

    const size_t payload_bytes = (size_t)SAMPLES_PER_PKT * N_ANT * N_POL * sizeof(uint16_t);
    std::vector<uint8_t> payload_data(payload_bytes);
    for (size_t i = 0; i < payload_bytes; i += 2)
    {
        const int ant = (i / 2 / N_POL) % N_ANT;
        payload_data[i] = static_cast<uint8_t>(ant_re[ant]);
        payload_data[i + 1] = static_cast<uint8_t>(ant_im[ant]);
    }

    const uint64_t chan_info = (uint64_t(1) << 16) | uint64_t(N_ANT);
    const uint64_t ts = ts_for(0, N_SAMPLES); // same timestamp: all one integration

    for (int pkt_idx = 0; pkt_idx < N_PKTS; ++pkt_idx)
    {
        auto pkt = SpeadPacket()
                       .item(0x0001, pkt_idx)
                       .item(0x0004, payload_bytes)
                       .item(0x1027, 0)
                       .item(0x1600, ts)
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, 0)
                       .item(0x3300, 0)
                       .payload(payload_data)
                       .build();
        ASSERT_TRUE(c.feed(pkt));
    }

    c.driveUntil([&] { return got.load(std::memory_order_acquire); });

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
// safety factor above that. The PRNG seed is fixed, so the payload - and thus the
// exact visibilities - are deterministic and the test is reproducible.
//
// N_SAMPLES=65536 far exceeds a single 9000-byte packet, so the integration is
// streamed across N_PKTS packets, each carrying SAMPLES_PER_PKT samples - the
// same multi-packet assembly path as VisibilityRoundTripMultiPacket above.
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
    constexpr int N_PKTS = N_SAMPLES / SAMPLES_PER_PKT; // 2048 packets / integration
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
    const uint64_t ts = ts_for(0, N_SAMPLES); // one integration

    // Payload per packet: SAMPLES_PER_PKT × N_ANT × N_POL × uint16_t. Refilled
    // with fresh randoms every packet, so the whole integration is an
    // independent noise stream per (packet, sample, antenna, pol).
    const size_t payload_bytes = (size_t)SAMPLES_PER_PKT * N_ANT * N_POL * sizeof(uint16_t);
    std::vector<uint8_t> payload_data(payload_bytes);

    for (int pkt_idx = 0; pkt_idx < N_PKTS; ++pkt_idx)
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
                       .item(0x1600, ts)
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, 0)
                       .item(0x3300, 0)
                       .payload(payload_data)
                       .build();
        ASSERT_TRUE(c.feed(pkt));
    }

    c.driveUntil([&] { return got.load(std::memory_order_acquire); });

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
    // The measured decorrelation must actually sit at the predicted floor - not
    // merely below the loose per-baseline tolerance, and not suspiciously zero.
    const double rms = std::sqrt(sum_sq / count);
    EXPECT_NEAR(rms, noise_floor, 0.25 * noise_floor)
        << "cross-correlation RMS " << rms << " departs from the 1/sqrt(N) floor " << noise_floor;

    std::cout << "[noise] floor(1/sqrt N)=" << noise_floor << " rms=" << rms
              << " max=" << max_rho << " tol=" << tol << " M=" << M << std::endl;
}

// Back-to-back integrations, each streamed as many packets: push two full
// integrations of N_PKTS packets apiece carrying different constant DC signals
// (SIGNAL_A then SIGNAL_B), with distinct advancing timestamps so the double
// buffer separates them, and assert the callback fires twice, each delivering
// its own integration's visibilities.
//
// This exercises the per-integration accumulate/reset across the buffer boundary.
// If accumulation leaked across integrations, integration B would read
// N_SAMPLES*(A^2+B^2) instead of N_SAMPLES*B^2; distinct signals catch a missing
// per-integration reset, and two callbacks confirm each integration lands in its
// own buffer and is delivered in order.
TEST_F(TensorCorrelatorGpuTest, BackToBackIntegrations)
{
    constexpr int8_t SIGNAL_A = 7;
    constexpr int8_t SIGNAL_B = 11;
    constexpr int N_ANT = 4;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256 * 16;                   // per integration
    constexpr int N_PKTS = 64;                            // packets per integration
    constexpr int SAMPLES_PER_PKT = N_SAMPLES / N_PKTS;   // 64 samples/packet
    constexpr int N_BASELINES = N_ANT * (N_ANT + 1) / 2;
    const size_t vis_len = (size_t)N_BASELINES * N_POL * N_POL;

    json config = {
        {"nof_antennas", N_ANT},   {"nof_channels", 1},     {"nof_fine_channels", 1},
        {"nof_tiles", 1},          {"nof_active_tiles", 1}, {"nof_samples", N_SAMPLES},
        {"nof_pols", N_POL},       {"max_packet_size", 9000},
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

    // Two integrations of N_PKTS packets each. heap counters run 0..2*N_PKTS-1:
    // counters [0,N_PKTS) map (mod N_PKTS) to integ 0's sample offsets, and
    // [N_PKTS,2N) map to integ 1's. The advancing per-integration timestamp is
    // what tells the double buffer that integ 1 is a new integration.
    for (int integ = 0; integ < 2; ++integ)
    {
        const uint8_t sig = (integ == 0) ? (uint8_t)SIGNAL_A : (uint8_t)SIGNAL_B;
        std::vector<uint8_t> payload(payload_bytes);
        for (size_t i = 0; i < payload_bytes; i += 2)
        {
            payload[i] = sig; // real
            payload[i + 1] = 0; // imag
        }
        const uint64_t ts = ts_for(integ, N_SAMPLES);

        for (int s = 0; s < N_PKTS; ++s)
        {
            const int counter = integ * N_PKTS + s;
            auto pkt = SpeadPacket()
                           .item(0x0001, counter)
                           .item(0x0004, payload_bytes)
                           .item(0x1027, 0)
                           .item(0x1600, ts)
                           .item(0x2004, 0x4)
                           .item(0x2002, chan_info)
                           .item(0x2001, 0)
                           .item(0x3300, 0)
                           .payload(payload)
                           .build();
            ASSERT_TRUE(c.feed(pkt));
        }
    }

    c.driveUntil([&] { return ncb.load(std::memory_order_acquire) >= 2; });

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
// double_buffer->finish_write(), marking the half-filled buffer ready so the GPU
// thread drains it instead of waiting forever for a packet that never comes.
//
// The undelivered samples occupy freshly-allocated pinned host pages, which are
// first-touch zero on this fresh consumer, so the result is a valid reduced
// correlation (auto power over HALF the samples) rather than a hang. The core
// assertion is that the callback fires at all; the value check assumes that
// first-touch-zero fill.
TEST_F(TensorCorrelatorGpuTest, PartialIntegrationFlushesRatherThanHangs)
{
    constexpr int8_t SIGNAL = 10;
    constexpr int N_ANT = 4;
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256;
    constexpr int HALF = N_SAMPLES / 2; // samples actually delivered
    constexpr int N_BASELINES = N_ANT * (N_ANT + 1) / 2;

    json config = {
        {"nof_antennas", N_ANT},   {"nof_channels", 1},     {"nof_fine_channels", 1},
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
    // samples_in_packet=HALF => nof_samples/samples_in_packet=2, and the second
    // (counter 1) packet is deliberately never sent, leaving the buffer half-filled.
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
                   .item(0x1600, ts_for(0, N_SAMPLES))
                   .item(0x2004, 0x4)
                   .item(0x2002, chan_info)
                   .item(0x2001, 0)
                   .item(0x3300, 0)
                   .payload(payload)
                   .build();
    ASSERT_TRUE(c.feed(pkt));

    // No further packets: drive processPacket so its pull_timeout expires and
    // flushes the buffer, releasing the half-filled integration to the GPU thread.
    c.driveUntil([&] { return got.load(std::memory_order_acquire); });

    c.cleanUp();

    ASSERT_TRUE(got.load()) << "flush did not release the partial integration; consumer hung";

    // Only HALF the samples carried signal; the rest were first-touch-zero, so
    // every entry is HALF * SIGNAL^2 + 0i (constant DC signal, identical on all
    // antennas).
    const int32_t expected_re = (int32_t)HALF * SIGNAL * SIGNAL;
    for (size_t k = 0; k < (size_t)N_BASELINES * N_POL * N_POL; ++k)
    {
        EXPECT_EQ(vis_out[k].real(), expected_re) << "entry " << k;
        EXPECT_EQ(vis_out[k].imag(), 0) << "entry " << k;
    }
}

// Multi-tile assembly: two tiles each deliver their own antenna block for the
// same time-chunk (same heap counter, same timestamp), exercising the
// tile_id * nof_antennas + start_antenna_id receiver-offset mapping in
// processPacket/write_data. The correlator must merge both tiles into one
// (N_TILES * ANT_PER_TILE)-receiver integration and correlate across tiles.
TEST_F(TensorCorrelatorGpuTest, MultiTileVisibilityRoundTrip)
{
    constexpr int N_TILES = 2;
    constexpr int ANT_PER_TILE = 2;
    constexpr int N_RECV = N_TILES * ANT_PER_TILE; // 4 receivers total
    constexpr int N_POL = 2;
    constexpr int N_SAMPLES = 256;
    constexpr int N_BASELINES = N_RECV * (N_RECV + 1) / 2;

    json config = {
        {"nof_antennas", ANT_PER_TILE}, {"nof_channels", 1},           {"nof_fine_channels", 1},
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
    const uint64_t ts = ts_for(0, N_SAMPLES); // both tiles share one integration

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
                       .item(0x1600, ts)
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, tpm_info)
                       .item(0x3300, 0)
                       .payload(payload)
                       .build();
        ASSERT_TRUE(c.feed(pkt));
    }

    c.driveUntil([&] { return got.load(std::memory_order_acquire); });

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

// A stream break (producer timeout -> finish_write + counter reset) between
// integrations must not wedge the pipeline: the next integration, arriving on a
// different channel with a fresh heap counter, has to be delivered.
//
// After delivering integration X the consumer's counters are reset by the pull
// timeout. Integration Y then arrives with heap_counter 0 again; the wrap and
// reference bookkeeping must re-latch cleanly so Y maps to a valid buffer and is
// flushed to the GPU thread rather than dropped.
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
        {"nof_antennas", N_ANT},   {"nof_channels", 1},     {"nof_fine_channels", 1},
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
                       .item(0x1600, ts_for(0, N_SAMPLES))
                       .item(0x2004, 0x4)
                       .item(0x2002, chan_info)
                       .item(0x2001, 0)
                       .item(0x3300, 0)
                       .payload(payload)
                       .build();
        EXPECT_TRUE(c.feed(pkt));
    };

    // Integration X on channel 0. Flush it with pull timeouts (this is also the
    // "break": finish_write() delivers X and resets the reference/rollover counters).
    send_integration(0, SIG_X);
    c.driveUntil([&] { return ncb.load(std::memory_order_acquire) >= 1; });
    ASSERT_EQ(ncb.load(), 1) << "first integration never delivered";

    // A few more empty-ring timeouts to be sure both sides have fully reset.
    for (int i = 0; i < 3; ++i)
    {
        c.processPacket();
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }

    // Integration Y on channel 5, fresh counter - must be delivered, not dropped.
    send_integration(5, SIG_Y);
    c.driveUntil([&] { return ncb.load(std::memory_order_acquire) >= 2; });

    c.cleanUp();

    ASSERT_EQ(ncb.load(), 2) << "second integration after the break was not delivered";
    const int32_t exp_y = (int32_t)N_SAMPLES * SIG_Y * SIG_Y;
    for (size_t k = 0; k < vis_len; ++k)
    {
        EXPECT_EQ(results[1][k].real(), exp_y) << "post-break integration entry " << k;
        EXPECT_EQ(results[1][k].imag(), 0) << "post-break integration entry " << k;
    }
}
