cmake_minimum_required(VERSION 3.14)
project(TccDoubleBufferTests CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Coverage flags - included in the binary so gcov/gcovr can report lines.
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fprofile-arcs -ftest-coverage -O0 -g")

set(CDAQ_SRC ${CMAKE_CURRENT_SOURCE_DIR}/../../src/ska_low_mccs_daq/cdaq)
include_directories(${CDAQ_SRC})

enable_testing()

# ── Google Test via FetchContent ──────────────────────────────────────────────
include(FetchContent)
FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG        v1.14.0
)
# Prevent GTest from overriding compiler/linker settings.
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)
include(GoogleTest)

# ── Real aavs-daq core ──────────────────────────────────────────────────────────
# The integrated-channel test drives the full DataConsumer pipeline (ring buffer +
# processPacket), so it needs the real aavs-daq sources, not the DAQ.h stub the
# buffer unit test uses. Fetch it pinned to the SHA the rest of the project builds
# against (see Dockerfile AAVS_DAQ_SHA). Only the source is downloaded - aavs-daq's
# own CMakeLists pulls in extra dependencies we don't need, which we bypass by
# compiling the core ourselves into aavsdaq_real.
set(FETCHCONTENT_SOURCE_DIR_AAVS_DAQ "" CACHE PATH "" FORCE)
FetchContent_Declare(
    aavs_daq
    GIT_REPOSITORY https://gitlab.com/ska-telescope/aavs-daq.git
    GIT_TAG        68e5953acd7a778ea37278f38679e5ca30636e69
)
FetchContent_GetProperties(aavs_daq)
if(NOT aavs_daq_POPULATED)
    FetchContent_Populate(aavs_daq)
    # Patch RealTimeThread for the SCHED_FIFO-unavailable fallback (see the module
    # for the why and the exact before/after).
    include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/PatchRealTimeThread.cmake)
endif()
set(AAVS_DAQ_SRC ${aavs_daq_SOURCE_DIR}/src)

# ── Real aavs-daq core (CPU only) ────────────────────────────────────────────────
# The full DataConsumer pipeline (ring buffer + processPacket) compiled from the
# real aavs-daq sources.
add_library(aavsdaq_real STATIC
    ${AAVS_DAQ_SRC}/DAQ.cpp
    ${AAVS_DAQ_SRC}/NetworkReceiver.cpp
    ${AAVS_DAQ_SRC}/RingBuffer.cpp
)
target_include_directories(aavsdaq_real PUBLIC ${AAVS_DAQ_SRC})
target_link_libraries(aavsdaq_real PUBLIC pthread dl)

# ── TccDoubleBuffer unit test (CPU only) ─────────────────────────────────────────
# Compiles the buffer sources against the cudawrappers + DAQ.h stubs so it needs
# neither CUDA nor a GPU. The stub headers (stubs/cudawrappers/, stubs/DAQ.h) are
# put on this target's path BEFORE the aavs-daq sources so they shadow the real
# ones; aavs-daq is still needed for Utils.h (allocate_aligned et al.).
add_executable(test_tcc_double_buffer
    test_tcc_double_buffer.cpp
    ${CDAQ_SRC}/TccDoubleBuffer.cpp
    ${CDAQ_SRC}/DoubleBuffer.cpp
)
target_include_directories(test_tcc_double_buffer BEFORE PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/stubs   # DAQ.h, cudawrappers/{cu,nvrtc}.hpp
    ${AAVS_DAQ_SRC}                     # Utils.h and friends
)
target_link_libraries(test_tcc_double_buffer PRIVATE GTest::gtest_main)
gtest_discover_tests(test_tcc_double_buffer)

# ── Integrated-channel (bandpass) consumer test (CPU only) ───────────────────────
# Drives IntegratedChannelisedData's real processPacket()/callback path against
# the real aavs-daq core.
add_executable(test_integrated_channel
    test_integrated_channel.cpp
    ${CDAQ_SRC}/ChannelisedData.cpp
)
target_include_directories(test_integrated_channel BEFORE PRIVATE ${AAVS_DAQ_SRC})
target_link_libraries(test_integrated_channel PRIVATE GTest::gtest_main aavsdaq_real)
gtest_discover_tests(test_integrated_channel)
