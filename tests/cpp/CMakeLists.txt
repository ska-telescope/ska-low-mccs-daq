cmake_minimum_required(VERSION 3.14)
project(TccDoubleBufferTests CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Coverage flags — included in the binary so gcov/gcovr can report lines.
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fprofile-arcs -ftest-coverage -O0 -g")

# ── Stub include directories ──────────────────────────────────────────────────
# The test/ directory must come first so that our stub cudawrappers/cu.hpp and
# DAQ.h shadow the real external headers when compiling the TCC buffer sources.
set(CDAQ_SRC ${CMAKE_CURRENT_SOURCE_DIR}/../../src/ska_low_mccs_daq/cdaq)

include_directories(${CMAKE_CURRENT_SOURCE_DIR})  # stubs: DAQ.h, cudawrappers/
include_directories(${CDAQ_SRC})                  # real sources: TccDoubleBuffer.h, DoubleBuffer.h

enable_testing()

# ── External dependencies via FetchContent ──────────────────────────────────
include(FetchContent)

FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG        v1.14.0
)
# Prevent GTest from overriding compiler/linker settings.
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

FetchContent_Declare(
    aavs_daq
    GIT_REPOSITORY https://gitlab.com/ska-telescope/aavs-daq.git
    GIT_TAG        68e5953acd7a778ea37278f38679e5ca30636e69
)
FetchContent_MakeAvailable(aavs_daq)

# ── Test executable ───────────────────────────────────────────────────────────
add_executable(test_tcc_double_buffer
    test_tcc_double_buffer.cpp
    ${CDAQ_SRC}/TccDoubleBuffer.cpp
    ${CDAQ_SRC}/DoubleBuffer.cpp
)

target_include_directories(test_tcc_double_buffer PRIVATE ${aavs_daq_SOURCE_DIR}/src)
target_link_libraries(test_tcc_double_buffer PRIVATE GTest::gtest_main)

# Register with CTest so `ctest -V` discovers and runs all TEST_F cases.
include(GoogleTest)
gtest_discover_tests(test_tcc_double_buffer)
