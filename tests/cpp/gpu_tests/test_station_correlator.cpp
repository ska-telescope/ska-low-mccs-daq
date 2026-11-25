// Station beam correlator tests (StationCorrelatorData.cpp). The tests skip if no GPU is visible.
//
// The GPU thread correlates a buffer when it is ready. A buffer becomes ready when a
// packet arrives two windows later, or when processPacket() times out and calls
// finish_write(). The tests feed whole integrations, then call processPacket() on an
// empty ring to flush them.

#include <chrono>
#include <complex>
#include <cstddef>
#include <cstdint>
#include <cuda_runtime.h>
#include <functional>
#include <gtest/gtest.h>
#include <mutex>
#include <thread>
#include <vector>

#include "StationCorrelatorData.h"
#include "spead_test_util.h"

// DaqReceiver.StationCorrelatorMetadata in pydaq/daq_receiver_interface.py has the same
// layout. Change both together.
static_assert(sizeof(StationCorrelatorMetadata) == 104, "update DaqReceiver.StationCorrelatorMetadata");
static_assert(offsetof(StationCorrelatorMetadata, substation_ids) == 56,
              "update DaqReceiver.StationCorrelatorMetadata");

namespace
{
    constexpr uint32_t SPP = STATION_CORRELATOR_SAMPLES_PER_PACKET; // samples per packet
    constexpr uint32_t NP = STATION_CORRELATOR_NOF_POLS;
    constexpr uint32_t TPB = STATION_CORRELATOR_TIMES_PER_BLOCK;
    constexpr uint64_t TAI_2000 = 946684768 - 5;
    constexpr double PACKET_PERIOD = SPP * 1.08e-6;

    constexpr uint16_t STATION_ID = 345;
    constexpr uint64_t SCAN_ID = 0x123456789ABCull; // uses all 48 bits

    bool gpu_visible()
    {
        int count = 0;
        return cudaGetDeviceCount(&count) == cudaSuccess && count > 0;
    }

    // Complex 8-bit value as in the buffers. The low byte is real, the high byte imaginary.
    uint16_t pack(int re, int im)
    {
        return (uint16_t)((uint8_t)(int8_t)re | ((uint16_t)(uint8_t)(int8_t)im << 8));
    }

    // Index of (channel, sample, receiver, pol) in the TCC layout [C][T/16][R][P][16]
    size_t tcc_index(size_t c, size_t s, size_t r, size_t p, size_t nof_r, size_t nof_samples)
    {
        return ((((c * (nof_samples / TPB) + s / TPB) * nof_r + r) * NP + p) * TPB) + s % TPB;
    }

    // Payload of one packet ([T][P] of complex 8-bit) from a function of sample and pol
    using SampleFn = std::function<std::complex<int>(size_t sample, size_t pol)>;

    std::vector<uint8_t> make_payload(const SampleFn &fn, size_t first_sample = 0)
    {
        std::vector<uint8_t> bytes(SPP * NP * 2);
        for (size_t t = 0; t < SPP; ++t)
            for (size_t p = 0; p < NP; ++p)
            {
                auto v = fn(first_sample + t, p);
                bytes[(t * NP + p) * 2] = (uint8_t)(int8_t)v.real();
                bytes[(t * NP + p) * 2 + 1] = (uint8_t)(int8_t)v.imag();
            }
        return bytes;
    }

    // A CSP station beam packet, with the items in the firmware order
    std::vector<uint8_t> make_station_packet(uint64_t counter, uint8_t substation_id,
                                             uint16_t frequency_id, const std::vector<uint8_t> &payload)
    {
        const uint64_t logical_channel = 7, beam_id = 3, subarray_id = 1;
        return SpeadPacket()
            .item(0x0001, counter)
            .item(0x0004, payload.size())
            .item(0x3010, SCAN_ID)
            .item(0x3000, (logical_channel << 32) | (beam_id << 16) | frequency_id)
            .item(0x3001, ((uint64_t)substation_id << 40) | (subarray_id << 32) |
                              ((uint64_t)STATION_ID << 16))
            .item(0x3300, 0)
            .payload(payload)
            .build();
    }

    // Noise in [-100, 100] for each (seed, sample, pol). A hash is faster than a
    // random generator for each sample.
    std::complex<int> noise(uint32_t seed, size_t sample, size_t pol)
    {
        uint32_t h = seed * 2654435761u ^ (uint32_t)(sample * NP + pol) * 2246822519u;
        h ^= h >> 15;
        h *= 2654435761u;
        h ^= h >> 13;
        return {(int)(h % 201) - 100, (int)((h >> 16) % 201) - 100};
    }
} // namespace

// ── StationCorrelatorDoubleBuffer ───────────────────────────────────────────────────────

class StationCorrelatorDoubleBufferTest : public ::testing::Test
{
protected:
    static constexpr uint16_t R = 2;
    static constexpr uint16_t C = 3;
    static constexpr uint32_t NS = 2 * SPP; // two packets per integration

    // Pinned host memory needs a current CUDA context. In the consumer the
    // correlator creates it before the buffer.
    void SetUp() override
    {
        if (!gpu_visible())
            GTEST_SKIP() << "no CUDA device visible at run time";
        cu::init();
        device_ = std::make_unique<cu::Device>(0);
        context_ = std::make_unique<cu::Context>(0, *device_);
        buffer_ = std::make_unique<StationCorrelatorDoubleBuffer>(R, C, NS, 4);
    }

    // Declared in this order so the buffer is freed before the context
    std::unique_ptr<cu::Device> device_;
    std::unique_ptr<cu::Context> context_;
    std::unique_ptr<StationCorrelatorDoubleBuffer> buffer_;

    // Payload as uint16 [T][P], value encodes sample and pol
    static std::vector<uint16_t> payload()
    {
        std::vector<uint16_t> data(SPP * NP);
        for (size_t s = 0; s < SPP; ++s)
            for (size_t p = 0; p < NP; ++p)
                data[s * NP + p] = pack((int)(s % 120) + 1, (int)p + 1);
        return data;
    }

    void write(uint16_t r, uint16_t c, uint64_t counter)
    {
        auto data = payload();
        buffer_->write_data(r, c, SPP, counter, data.data(), TAI_2000 + counter * PACKET_PERIOD,
                           SCAN_ID, STATION_ID);
    }

    // Flush and return the next ready buffer
    StationCorrelatorBuffer *flush_and_read()
    {
        buffer_->finish_write();
        return buffer_->read_buffer();
    }
};

TEST_F(StationCorrelatorDoubleBufferTest, WritesPacketInTccLayout)
{
    // Counter 11 is the second packet of the window starting at 10
    write(/*r=*/1, /*c=*/2, /*counter=*/11);

    StationCorrelatorBuffer *b = flush_and_read();
    ASSERT_NE(b, nullptr);
    EXPECT_EQ(b->index.load(), 10u);
    EXPECT_EQ(b->nof_packets, 1u);
    EXPECT_EQ(b->scan_id, SCAN_ID);
    EXPECT_EQ(b->station_id, STATION_ID);
    EXPECT_DOUBLE_EQ(b->ref_time, TAI_2000 + 11 * PACKET_PERIOD);

    // The packet fills samples [SPP, 2*SPP) of receiver 1, channel 2
    for (size_t s : {size_t(0), size_t(15), size_t(16), size_t(SPP - 1)})
        for (size_t p = 0; p < NP; ++p)
            EXPECT_EQ(b->data[tcc_index(2, SPP + s, 1, p, R, NS)], pack((int)(s % 120) + 1, (int)p + 1))
                << "s=" << s << " p=" << p;

    // Nothing else was written
    EXPECT_EQ(b->data[tcc_index(2, 0, 1, 0, R, NS)], 0u);
    EXPECT_EQ(b->data[tcc_index(2, SPP, 0, 0, R, NS)], 0u);
    EXPECT_EQ(b->data[tcc_index(1, SPP, 1, 0, R, NS)], 0u);
}

TEST_F(StationCorrelatorDoubleBufferTest, LatePacketGoesToPreviousBuffer)
{
    write(0, 0, 10); // window 10
    write(0, 0, 12); // window 12, window 10 stays open
    write(0, 0, 11); // late, belongs to window 10

    buffer_->finish_write();
    StationCorrelatorBuffer *first = buffer_->read_buffer();
    ASSERT_NE(first, nullptr);
    EXPECT_EQ(first->index.load(), 10u);
    EXPECT_EQ(first->nof_packets, 2u);
    EXPECT_EQ(first->data[tcc_index(0, SPP, 0, 0, R, NS)], pack(1, 1));
    buffer_->release_buffer();

    StationCorrelatorBuffer *second = buffer_->read_buffer();
    ASSERT_NE(second, nullptr);
    EXPECT_EQ(second->index.load(), 12u);
    EXPECT_EQ(second->nof_packets, 1u);
}

TEST_F(StationCorrelatorDoubleBufferTest, PacketOlderThanPreviousWindowIsDropped)
{
    write(0, 0, 12);
    write(0, 0, 14); // window 12 becomes the previous one
    write(0, 0, 10); // older than window 12

    // Neither window received it
    buffer_->finish_write();
    StationCorrelatorBuffer *first = buffer_->read_buffer();
    ASSERT_NE(first, nullptr);
    EXPECT_EQ(first->index.load(), 12u);
    EXPECT_EQ(first->nof_packets, 1u);
    buffer_->release_buffer();
    StationCorrelatorBuffer *second = buffer_->read_buffer();
    ASSERT_NE(second, nullptr);
    EXPECT_EQ(second->nof_packets, 1u);
}

TEST_F(StationCorrelatorDoubleBufferTest, PacketBeforeFirstWindowIsDropped)
{
    // At the start there is no previous window to place a late packet in
    write(0, 0, 12);
    write(0, 0, 10);

    StationCorrelatorBuffer *b = flush_and_read();
    ASSERT_NE(b, nullptr);
    EXPECT_EQ(b->nof_packets, 1u);
}

TEST_F(StationCorrelatorDoubleBufferTest, JumpAheadStartsNewWindowWithoutOverrun)
{
    write(0, 0, 10);
    write(0, 0, 1000); // far ahead, starts window 1000
    write(0, 0, 1001);
    write(0, 0, 500);  // between the windows, dropped

    buffer_->finish_write();
    StationCorrelatorBuffer *first = buffer_->read_buffer();
    ASSERT_NE(first, nullptr);
    EXPECT_EQ(first->index.load(), 10u);
    EXPECT_EQ(first->nof_packets, 1u);
    buffer_->release_buffer();

    StationCorrelatorBuffer *second = buffer_->read_buffer();
    ASSERT_NE(second, nullptr);
    EXPECT_EQ(second->index.load(), 1000u);
    EXPECT_EQ(second->nof_packets, 2u);
}

TEST_F(StationCorrelatorDoubleBufferTest, ReleaseClearsBufferForReuse)
{
    // Fill window 10 through every buffer once, so the buffer is reused
    write(1, 2, 10);
    StationCorrelatorBuffer *b = flush_and_read();
    ASSERT_NE(b, nullptr);
    buffer_->release_buffer();

    for (uint64_t w = 1; w < 4; ++w)
    {
        write(0, 0, 10 + 2 * w);
        ASSERT_NE(flush_and_read(), nullptr);
        buffer_->release_buffer();
    }

    // The first buffer again, for a different receiver and channel
    write(0, 1, 100);
    b = flush_and_read();
    ASSERT_NE(b, nullptr);
    EXPECT_EQ(b->index.load(), 100u);
    EXPECT_EQ(b->nof_packets, 1u);
    // The earlier packet's samples were cleared, so a missing packet correlates as zero
    EXPECT_EQ(b->data[tcc_index(2, 0, 1, 0, R, NS)], 0u);
    EXPECT_EQ(b->data[tcc_index(1, 0, 0, 0, R, NS)], pack(1, 1));
}

// ── StationCorrelatorData consumer ──────────────────────────────────────────────────────

// Expose the protected packet path and ring-buffer push for testing (as
// TestableTensorCorrelator in test_tensor_correlator.cpp)
class TestableStationCorrelator : public StationCorrelatorData
{
public:
    using DataConsumer::cleanUp;
    using StationCorrelatorData::packetFilter;
    using StationCorrelatorData::processPacket;

    // Stop the GPU thread even when a test fails before its own cleanUp()
    ~TestableStationCorrelator() override { cleanUp(); }

    bool pushPacket(const std::vector<uint8_t> &pkt)
    {
        return ring_buffer->push(const_cast<uint8_t *>(pkt.data()), pkt.size());
    }

    bool hasRingBuffer() const { return ring_buffer != nullptr; }

    // Push one packet and hand it straight to processPacket()
    bool feed(const std::vector<uint8_t> &pkt)
    {
        return pushPacket(pkt) && processPacket();
    }

    // Drive processPacket() against a drained ring so its pull timeout fires
    // finish_write() and flushes the pending buffers to the GPU thread
    template <class Pred>
    void driveUntil(Pred done, size_t timeout_ms = 10000)
    {
        auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
        while (!done() && std::chrono::steady_clock::now() < deadline)
        {
            processPacket();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }

    void setCapturingCallback(std::function<void(void *, double, void *)> fn)
    {
        s_fn_ = std::move(fn);
        setCallback(&TestableStationCorrelator::trampoline);
    }

private:
    static void trampoline(void *data, double ts, void *meta)
    {
        if (s_fn_)
            s_fn_(data, ts, meta);
    }
    static inline std::function<void(void *, double, void *)> s_fn_;
};

// One delivered integration
struct Integration
{
    std::vector<std::complex<int32_t>> vis; // [C][B][P][P]
    double timestamp;
    StationCorrelatorMetadata metadata;
};

// Collects every integration the consumer delivers
class Collector
{
public:
    Collector(TestableStationCorrelator &c, size_t nof_vis)
    {
        c.setCapturingCallback([this, nof_vis](void *data, double ts, void *meta)
                               {
            auto *v = static_cast<std::complex<int32_t> *>(data);
            std::lock_guard<std::mutex> lock(mutex_);
            items_.push_back({std::vector<std::complex<int32_t>>(v, v + nof_vis), ts,
                              *static_cast<StationCorrelatorMetadata *>(meta)}); });
    }

    size_t size()
    {
        std::lock_guard<std::mutex> lock(mutex_);
        return items_.size();
    }

    Integration at(size_t i)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        return items_.at(i);
    }

private:
    std::mutex mutex_;
    std::vector<Integration> items_;
};

namespace
{
    json station_config(std::vector<int> substation_ids, int start_channel, int nof_channels,
                        uint32_t nof_samples)
    {
        return json{
            {"substation_ids", substation_ids},
            {"start_channel", start_channel},
            {"nof_channels", nof_channels},
            {"nof_samples", nof_samples},
            {"max_packet_size", 9000},
        };
    }

    // Index of vis[c][baseline(x, y)][py][px], with x >= y
    size_t vis_index(size_t c, size_t x, size_t y, size_t py, size_t px, size_t nof_r)
    {
        const size_t nof_baselines = nof_r * (nof_r + 1) / 2;
        return ((c * nof_baselines + x * (x + 1) / 2 + y) * NP + py) * NP + px;
    }
} // namespace

TEST(StationCorrelatorFilterTest, AcceptsStationBeamPackets)
{
    TestableStationCorrelator c;
    auto pkt = make_station_packet(10, 1, 100, make_payload([](size_t, size_t)
                                                            { return std::complex<int>(1, 0); }));
    EXPECT_TRUE(c.packetFilter(pkt.data()));
}

TEST(StationCorrelatorFilterTest, RejectsLmcPackets)
{
    TestableStationCorrelator c;
    // LMC channelised data header, with no 0x3010 item
    auto pkt = SpeadPacket()
                   .item(0x0001, 0)
                   .item(0x0004, 0)
                   .item(0x1027, 0)
                   .item(0x1600, 0)
                   .item(0x2004, 0x5)
                   .item(0x2002, 0)
                   .item(0x2001, 0)
                   .item(0x3300, 0)
                   .build();
    EXPECT_FALSE(c.packetFilter(pkt.data()));
}

TEST(StationCorrelatorFilterTest, RejectsNonSpead)
{
    TestableStationCorrelator c;
    std::vector<uint8_t> garbage(64, 0xFF);
    EXPECT_FALSE(c.packetFilter(garbage.data()));
}

class StationCorrelatorGpuTest : public ::testing::Test
{
protected:
    void SetUp() override
    {
        if (!gpu_visible())
            GTEST_SKIP() << "no CUDA device visible at run time";
    }
};

TEST_F(StationCorrelatorGpuTest, InitialiseRejectsBadConfig)
{
    auto good = station_config({1, 2}, 100, 2, 2 * SPP);

    json missing = good;
    missing.erase("start_channel");
    json empty = good;
    empty["substation_ids"] = json::array();
    json duplicate = good;
    duplicate["substation_ids"] = {1, 1};
    json partial_packet = good;
    partial_packet["nof_samples"] = SPP + 16;
    json no_channels = good;
    no_channels["nof_channels"] = 0;

    for (const json &config : {missing, empty, duplicate, partial_packet, no_channels})
    {
        TestableStationCorrelator c;
        EXPECT_FALSE(c.initialiseConsumer(config)) << config.dump();
        EXPECT_FALSE(c.hasRingBuffer());
        c.cleanUp(); // safe after a failed initialise
    }

    TestableStationCorrelator c;
    EXPECT_TRUE(c.initialiseConsumer(good));
    c.cleanUp();
}

// Two substations see exactly the same signal, so every baseline equals the
// autocorrelation. The signal differs per channel, which checks the channel order.
TEST_F(StationCorrelatorGpuTest, IdenticalSubstationsCorrelatePerfectly)
{
    constexpr size_t R = 2, C = 3, NPKT = 2, NS = NPKT * SPP;
    constexpr size_t NVIS = C * (R * (R + 1) / 2) * NP * NP;
    constexpr uint64_t BASE = 1000 * NPKT; // window start
    const std::vector<int> substations = {4, 9};
    constexpr int START = 200;

    TestableStationCorrelator c;
    ASSERT_TRUE(c.initialiseConsumer(station_config(substations, START, C, NS)));
    Collector got(c, NVIS);

    for (size_t ch = 0; ch < C; ++ch)
        for (size_t k = 0; k < NPKT; ++k)
        {
            auto payload = make_payload([ch](size_t s, size_t p)
                                        { return noise((uint32_t)ch, s, p); },
                                        k * SPP);
            for (int sub : substations)
                ASSERT_TRUE(c.feed(make_station_packet(BASE + k, sub, START + ch, payload)));
        }

    c.driveUntil([&] { return got.size() >= 1; });
    ASSERT_EQ(got.size(), 1u);
    Integration in = got.at(0);

    for (size_t ch = 0; ch < C; ++ch)
        for (size_t p = 0; p < NP; ++p)
        {
            int64_t expected = 0;
            for (size_t s = 0; s < NS; ++s)
                expected += std::norm(noise((uint32_t)ch, s, p));

            auto auto0 = in.vis[vis_index(ch, 0, 0, p, p, R)];
            EXPECT_EQ(auto0.real(), expected) << "ch=" << ch << " p=" << p;
            EXPECT_EQ(auto0.imag(), 0);
            EXPECT_EQ(in.vis[vis_index(ch, 1, 1, p, p, R)], auto0);
            EXPECT_EQ(in.vis[vis_index(ch, 1, 0, p, p, R)], auto0); // cross = auto
        }

    EXPECT_DOUBLE_EQ(in.timestamp, TAI_2000 + BASE * PACKET_PERIOD);
    EXPECT_EQ(in.metadata.nof_packets, R * C * NPKT);
    EXPECT_EQ(in.metadata.nof_samples, NS);
    EXPECT_EQ(in.metadata.station_id, STATION_ID);
    EXPECT_EQ(in.metadata.scan_id, SCAN_ID);
    EXPECT_EQ(in.metadata.start_channel, START);
    EXPECT_EQ(in.metadata.nof_channels, C);
    EXPECT_EQ(in.metadata.nof_substations, R);
    EXPECT_EQ(in.metadata.substation_ids[0], 4);
    EXPECT_EQ(in.metadata.substation_ids[1], 9);

    c.cleanUp();
}

// Substation 1 sees substation 0's signal rotated by 90 degrees (multiplied by j).
// The cross-correlation is then purely imaginary with the magnitude of the auto.
// TCC computes baseline (x, y) as sum(v_y * conj(v_x)), so
// vis(1, 0) = sum(v0 * conj(j v0)) = -j * auto.
TEST_F(StationCorrelatorGpuTest, PhaseOffsetBetweenSubstationsIsRecovered)
{
    constexpr size_t R = 2, C = 1, NPKT = 2, NS = NPKT * SPP;
    constexpr size_t NVIS = C * (R * (R + 1) / 2) * NP * NP;
    constexpr uint64_t BASE = 500 * NPKT;

    TestableStationCorrelator c;
    ASSERT_TRUE(c.initialiseConsumer(station_config({1, 2}, 100, C, NS)));
    Collector got(c, NVIS);

    for (size_t k = 0; k < NPKT; ++k)
    {
        auto v0 = make_payload([](size_t s, size_t p)
                               { return noise(7, s, p); },
                               k * SPP);
        auto v1 = make_payload([](size_t s, size_t p)
                               { auto v = noise(7, s, p); return std::complex<int>(-v.imag(), v.real()); },
                               k * SPP);
        ASSERT_TRUE(c.feed(make_station_packet(BASE + k, 1, 100, v0)));
        ASSERT_TRUE(c.feed(make_station_packet(BASE + k, 2, 100, v1)));
    }

    c.driveUntil([&] { return got.size() >= 1; });
    ASSERT_EQ(got.size(), 1u);
    Integration in = got.at(0);

    for (size_t p = 0; p < NP; ++p)
    {
        auto auto0 = in.vis[vis_index(0, 0, 0, p, p, R)];
        auto cross = in.vis[vis_index(0, 1, 0, p, p, R)];
        EXPECT_GT(auto0.real(), 0);
        EXPECT_EQ(cross.real(), 0) << "p=" << p;
        EXPECT_EQ(cross.imag(), -auto0.real()) << "p=" << p;
    }

    c.cleanUp();
}

// Packets from substations or channels that are not configured are ignored
TEST_F(StationCorrelatorGpuTest, UnconfiguredPacketsAreIgnored)
{
    constexpr size_t R = 2, C = 2, NS = SPP;
    constexpr size_t NVIS = C * (R * (R + 1) / 2) * NP * NP;
    constexpr uint64_t BASE = 4000;

    TestableStationCorrelator c;
    ASSERT_TRUE(c.initialiseConsumer(station_config({1, 2}, 100, C, NS)));
    Collector got(c, NVIS);

    auto payload = make_payload([](size_t, size_t)
                                { return std::complex<int>(3, 4); });

    ASSERT_TRUE(c.feed(make_station_packet(BASE, 7, 100, payload)));  // unconfigured substation
    ASSERT_TRUE(c.feed(make_station_packet(BASE, 1, 99, payload)));   // below the channel window
    ASSERT_TRUE(c.feed(make_station_packet(BASE, 1, 102, payload)));  // above the channel window

    for (int sub : {1, 2})
        for (int ch : {100, 101})
            ASSERT_TRUE(c.feed(make_station_packet(BASE, sub, ch, payload)));

    c.driveUntil([&] { return got.size() >= 1; });
    ASSERT_EQ(got.size(), 1u);
    Integration in = got.at(0);

    EXPECT_EQ(in.metadata.nof_packets, 4u);
    // Only the configured packets are correlated. |3+4j|^2 = 25 for each sample.
    EXPECT_EQ(in.vis[vis_index(1, 1, 1, 0, 0, R)].real(), (int32_t)(25 * NS));

    c.cleanUp();
}

// A missing packet correlates as zero
TEST_F(StationCorrelatorGpuTest, MissingPacketsCorrelateAsZero)
{
    constexpr size_t R = 2, C = 1, NPKT = 2, NS = NPKT * SPP;
    constexpr size_t NVIS = C * (R * (R + 1) / 2) * NP * NP;
    constexpr uint64_t BASE = 6000;

    TestableStationCorrelator c;
    ASSERT_TRUE(c.initialiseConsumer(station_config({1, 2}, 100, C, NS)));
    Collector got(c, NVIS);

    auto ones = make_payload([](size_t, size_t)
                             { return std::complex<int>(1, 0); });

    // Substation 1 sends both packets, substation 2 only the first
    ASSERT_TRUE(c.feed(make_station_packet(BASE, 1, 100, ones)));
    ASSERT_TRUE(c.feed(make_station_packet(BASE + 1, 1, 100, ones)));
    ASSERT_TRUE(c.feed(make_station_packet(BASE, 2, 100, ones)));

    c.driveUntil([&] { return got.size() >= 1; });
    ASSERT_EQ(got.size(), 1u);
    Integration in = got.at(0);

    EXPECT_EQ(in.metadata.nof_packets, 3u);
    for (size_t p = 0; p < NP; ++p)
    {
        EXPECT_EQ(in.vis[vis_index(0, 0, 0, p, p, R)].real(), (int32_t)NS) << "p=" << p;
        EXPECT_EQ(in.vis[vis_index(0, 1, 1, p, p, R)].real(), (int32_t)SPP) << "p=" << p;
        EXPECT_EQ(in.vis[vis_index(0, 1, 0, p, p, R)].real(), (int32_t)SPP) << "p=" << p;
    }

    c.cleanUp();
}

// Consecutive integrations are delivered in order, aligned to the packet counter
TEST_F(StationCorrelatorGpuTest, BackToBackIntegrations)
{
    constexpr size_t R = 1, C = 1, NPKT = 2, NS = NPKT * SPP, NINTEG = 3;
    constexpr size_t NVIS = C * (R * (R + 1) / 2) * NP * NP;
    constexpr uint64_t BASE = 3000 * NPKT;

    TestableStationCorrelator c;
    ASSERT_TRUE(c.initialiseConsumer(station_config({1}, 100, C, NS)));
    Collector got(c, NVIS);

    for (size_t i = 0; i < NINTEG; ++i)
    {
        // Integration i has amplitude i + 1, so each one is recognisable
        auto payload = make_payload([i](size_t, size_t)
                                    { return std::complex<int>((int)i + 1, 0); });
        for (size_t k = 0; k < NPKT; ++k)
            ASSERT_TRUE(c.feed(make_station_packet(BASE + i * NPKT + k, 1, 100, payload)));
    }

    c.driveUntil([&] { return got.size() >= NINTEG; });
    ASSERT_EQ(got.size(), NINTEG);

    for (size_t i = 0; i < NINTEG; ++i)
    {
        Integration in = got.at(i);
        EXPECT_DOUBLE_EQ(in.timestamp, TAI_2000 + (BASE + i * NPKT) * PACKET_PERIOD) << "i=" << i;
        EXPECT_EQ(in.vis[vis_index(0, 0, 0, 0, 0, R)].real(), (int32_t)((i + 1) * (i + 1) * NS))
            << "i=" << i;
        EXPECT_EQ(in.metadata.nof_packets, NPKT);
    }

    c.cleanUp();
}
