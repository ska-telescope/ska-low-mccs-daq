cmake_minimum_required(VERSION 3.14)
project(TccSplitRingTests CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Coverage flags — included in the binary so gcov/gcovr can report lines.
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fprofile-arcs -ftest-coverage -O0 -g")

# ── Stub include directories ──────────────────────────────────────────────────
# The test/ directory must come first so that our stub cudawrappers/cu.hpp and
# DAQ.h shadow the real external headers when compiling TccSplitRing.cpp.
set(CDAQ_SRC ${CMAKE_CURRENT_SOURCE_DIR}/../../src/ska_low_mccs_daq/cdaq)

include_directories(${CMAKE_CURRENT_SOURCE_DIR})  # stubs: DAQ.h, cudawrappers/
include_directories(${CDAQ_SRC})                  # real source: TccSplitRing.h

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

# ── Test executable ───────────────────────────────────────────────────────────
add_executable(test_tcc_split_ring
    test_tcc_split_ring.cpp
    ${CDAQ_SRC}/TccSplitRing.cpp
)

target_link_libraries(test_tcc_split_ring PRIVATE GTest::gtest_main)

# Register with CTest so `ctest -V` discovers and runs all TEST_F cases.
include(GoogleTest)
gtest_discover_tests(test_tcc_split_ring)
