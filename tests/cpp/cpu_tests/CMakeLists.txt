# CPU-only test targets. Built unconditionally - they need neither CUDA nor a GPU.
#
# Inherited from the parent scope: CDAQ_SRC, TEST_CPP_ROOT (spead_test_util.h),
# AAVS_DAQ_SRC and the aavsdaq / GTest::gtest_main targets.

# ── Integrated-channel (bandpass) consumer test ──────────────────────────────────
# Drives IntegratedChannelisedData's processPacket()/callback path against aavs-daq.
add_executable(test_integrated_channel
    test_integrated_channel.cpp
    ${CDAQ_SRC}/ChannelisedData.cpp
)
target_include_directories(test_integrated_channel BEFORE PRIVATE ${AAVS_DAQ_SRC})
target_link_libraries(test_integrated_channel PRIVATE GTest::gtest_main aavsdaq)
gtest_discover_tests(test_integrated_channel)
