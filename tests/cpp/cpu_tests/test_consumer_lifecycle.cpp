// Consumer lifecycle tests for the aavs-daq C API (DAQ.cpp).
//
// loadConsumer stores each consumer in a global map. A consumer that fails to
// initialise must leave that map, or every later loadConsumer of the same name
// returns CONSUMER_ALREADY_INITIALISED until the process restarts.
//
// loadConsumer finds a consumer by dlopen and dlsym. With a null module, dlopen
// returns this executable, so the factories below must be exported (the target
// sets ENABLE_EXPORTS). Each test uses its own consumer name, because the map
// lives for the whole process and a consumer that initialised stays in it.

#include <gtest/gtest.h>
#include <ostream>
#include <stdexcept>
#include <string>

#include "DAQ.h"

// The receiver that DAQ.cpp keeps. initialiseConsumer only checks that it is not
// null, and a real receiver needs a raw socket, so the tests set a dummy pointer.
extern NetworkReceiver *receiver;

namespace
{
    // A consumer whose initialise result comes from its configuration. "ok" sets
    // the return value, and "throw" makes it throw instead.
    class FakeConsumer : public DataConsumer
    {
    public:
        static int live;

        FakeConsumer() { live++; }
        ~FakeConsumer() override { live--; }

        bool initialiseConsumer(json configuration) override
        {
            if (configuration.value("throw", false))
                throw std::runtime_error("out of GPU memory");
            return configuration.value("ok", false);
        }

    protected:
        bool processPacket() override { return false; }
    };

    int FakeConsumer::live = 0;
} // namespace

// The test case types are outside the anonymous namespace, because gtest stores
// the parameter in a class at global scope (see -Wsubobject-linkage).
struct FailedInitialiseCase
{
    const char *consumer;
    const char *configuration;
};

// Print the case by name. Without this, gtest prints the raw bytes, which hold
// pointer values that change from run to run.
void PrintTo(const FailedInitialiseCase &test_case, std::ostream *os)
{
    *os << test_case.consumer;
}

class ConsumerLifecycleTest : public ::testing::Test
{
protected:
    void SetUp() override { receiver = reinterpret_cast<NetworkReceiver *>(0x1); }
    void TearDown() override { receiver = nullptr; }
};

class FailedInitialiseTest : public ConsumerLifecycleTest,
                             public ::testing::WithParamInterface<FailedInitialiseCase>
{
};

extern "C" DataConsumer *fake_returns_false() { return new FakeConsumer; }
extern "C" DataConsumer *fake_throws() { return new FakeConsumer; }
extern "C" DataConsumer *fake_bad_json() { return new FakeConsumer; }
extern "C" DataConsumer *fake_initialises() { return new FakeConsumer; }

// A failed initialise deletes the consumer, and the same name loads again.
TEST_P(FailedInitialiseTest, ConsumerCanBeLoadedAgain)
{
    const auto &param = GetParam();
    const int live_before = FakeConsumer::live;

    ASSERT_EQ(loadConsumer(nullptr, param.consumer), SUCCESS);
    ASSERT_EQ(initialiseConsumer(param.consumer, param.configuration), FAILURE);
    EXPECT_EQ(FakeConsumer::live, live_before);

    EXPECT_EQ(loadConsumer(nullptr, param.consumer), SUCCESS);
    EXPECT_EQ(FakeConsumer::live, live_before + 1);
}

INSTANTIATE_TEST_SUITE_P(
    ConsumerLifecycle, FailedInitialiseTest,
    ::testing::Values(FailedInitialiseCase{"fake_returns_false", R"({"ok": false})"},
                      FailedInitialiseCase{"fake_throws", R"({"throw": true})"},
                      FailedInitialiseCase{"fake_bad_json", "{"}),
    [](const ::testing::TestParamInfo<FailedInitialiseCase> &info) {
        return std::string(info.param.consumer);
    });

// A consumer that initialised stays loaded, so a second load of it is refused.
TEST_F(ConsumerLifecycleTest, InitialisedConsumerStaysLoaded)
{
    ASSERT_EQ(loadConsumer(nullptr, "fake_initialises"), SUCCESS);
    ASSERT_EQ(initialiseConsumer("fake_initialises", R"({"ok": true})"), SUCCESS);

    EXPECT_EQ(loadConsumer(nullptr, "fake_initialises"), CONSUMER_ALREADY_INITIALISED);
}
