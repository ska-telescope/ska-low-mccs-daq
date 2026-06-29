// Unit tests for the aavs-daq C API entry points (DAQ.cpp).
//
// Two testable surfaces don't need a live network receiver:
//   1. LOG() / attachLogger() — message formatting and forwarding.
//   2. The receiver/consumer guard clauses that return early when the global
//      receiver is uninitialised or a consumer is unknown.
//
// The DAQ globals (`receiver`, `consumers`) are process-wide. These tests never
// start a receiver, so `receiver` stays null and `consumers` stays empty; each
// test that touches the logger detaches it again in TearDown.

#include <gtest/gtest.h>
#include <cerrno>
#include <string>

#include "DAQ.h"

// ── Logger capture ───────────────────────────────────────────────────────────

namespace {
struct LogCapture {
    int         calls = 0;
    int         level = -1;
    std::string message;
};
LogCapture g_log;

void capturing_logger(int level, const char *message)
{
    g_log.calls++;
    g_log.level = level;
    g_log.message = message;
}
}  // namespace

// ─────────────────────────────────────────────────────────────────────────────
// LOG / attachLogger
// ─────────────────────────────────────────────────────────────────────────────

class DaqLogTest : public ::testing::Test {
protected:
    void SetUp() override { g_log = LogCapture{}; errno = 0; attachLogger(capturing_logger); }
    // Detach so a later LOG (e.g. a FATAL with no logger -> exit) can't escape.
    void TearDown() override { attachLogger(nullptr); errno = 0; }
};

TEST_F(DaqLogTest, ForwardsMessageAndLevelToLogger)
{
    LOG(INFO, "hello");
    EXPECT_EQ(g_log.calls, 1);
    EXPECT_EQ(g_log.level, INFO);
    EXPECT_EQ(g_log.message, "hello");
}

TEST_F(DaqLogTest, FormatsPrintfArguments)
{
    LOG(WARN, "value=%d name=%s", 42, "abc");
    EXPECT_EQ(g_log.calls, 1);
    EXPECT_EQ(g_log.level, WARN);
    EXPECT_EQ(g_log.message, "value=42 name=abc");
}

TEST_F(DaqLogTest, FatalIsForwardedNotExitedWhenLoggerAttached)
{
    // With a logger attached, FATAL forwards rather than calling exit(-1).
    errno = 0;  // avoid the strerror suffix appended for FATAL
    LOG(FATAL, "boom");
    EXPECT_EQ(g_log.calls, 1);
    EXPECT_EQ(g_log.level, FATAL);
    EXPECT_EQ(g_log.message, "boom");
}

TEST_F(DaqLogTest, FatalAppendsErrnoStringWhenErrnoSet)
{
    // For FATAL-level logs the errno description is appended when errno != 0.
    errno = EACCES;
    LOG(FATAL, "denied");
    ASSERT_EQ(g_log.calls, 1);
    EXPECT_EQ(g_log.message, std::string("denied: ") + strerror(EACCES));
}

TEST_F(DaqLogTest, NonFatalDoesNotAppendErrno)
{
    errno = EACCES;
    LOG(ERROR, "plain");
    ASSERT_EQ(g_log.calls, 1);
    EXPECT_EQ(g_log.message, "plain");  // errno suffix only added for FATAL
}

// ─────────────────────────────────────────────────────────────────────────────
// Receiver / consumer guard clauses (no network receiver running)
// ─────────────────────────────────────────────────────────────────────────────

// A logger is attached for this suite too: the failure paths under test emit
// FATAL/ERROR logs, and a FATAL with no logger would exit the process.
class DaqApiTest : public ::testing::Test {
protected:
    void SetUp() override { attachLogger(capturing_logger); }
    void TearDown() override { attachLogger(nullptr); }
};

TEST_F(DaqApiTest, StopReceiverSucceedsWhenNoReceiver)
{
    // Idempotent: stopping a receiver that was never started is a no-op success.
    EXPECT_EQ(stopReceiver(), SUCCESS);
}

TEST_F(DaqApiTest, AddReceiverPortFailsWithoutReceiver)
{
    EXPECT_EQ(addReceiverPort(4660), RECEIVER_UNINITIALISED);
}

TEST_F(DaqApiTest, InitialiseConsumerFailsWithoutReceiver)
{
    EXPECT_EQ(initialiseConsumer("rawdata", "{}"), RECEIVER_UNINITIALISED);
}

TEST_F(DaqApiTest, StartConsumerFailsWithoutReceiver)
{
    EXPECT_EQ(startConsumer("rawdata", nullptr, nullptr), RECEIVER_UNINITIALISED);
}

TEST_F(DaqApiTest, StartConsumerDynamicFailsWithoutReceiver)
{
    EXPECT_EQ(startConsumerDynamic("rawdata", nullptr, nullptr), RECEIVER_UNINITIALISED);
}

TEST_F(DaqApiTest, StopConsumerFailsForUnknownConsumer)
{
    EXPECT_EQ(stopConsumer("does_not_exist"), CONSUMER_NOT_INITIALISED);
}

TEST_F(DaqApiTest, LoadConsumerFailsForMissingLibrary)
{
    // dlopen of a non-existent module fails; loadConsumer logs FATAL and returns
    // FAILURE (the FATAL is forwarded to our logger rather than exiting).
    EXPECT_EQ(loadConsumer("/no/such/library.so", "rawdata"), FAILURE);
    EXPECT_GT(g_log.calls, 0);
}
