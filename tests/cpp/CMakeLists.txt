cmake_minimum_required(VERSION 3.14)
project(TccDoubleBufferTests CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Coverage flags - included in the binary so gcov/gcovr can report lines.
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fprofile-arcs -ftest-coverage -O0 -g")

# Sources under test (cdaq) and shared test helpers (spead_test_util.h at this
# root), on the include path for every test subdirectory.
set(CDAQ_SRC ${CMAKE_CURRENT_SOURCE_DIR}/../../src/ska_low_mccs_daq/cdaq)
set(TEST_CPP_ROOT ${CMAKE_CURRENT_SOURCE_DIR})
include_directories(${CDAQ_SRC} ${TEST_CPP_ROOT})

# Our helper modules live in cmake/; make them resolvable by include(<name>).
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/cmake)

enable_testing()

# ── Dependencies ─────────────────────────────────────────────────────────────────
# Each module documents the variables/targets it provides.
include(FetchGTest)
include(FetchAavsDaq)
include(EnsureCuda)

# ── Test targets ─────────────────────────────────────────────────────────────────
# CPU tests always build; GPU tests only when EnsureCuda cleared them.
add_subdirectory(cpu_tests)

if(_build_gpu)
    include(FetchTensorCorrelator)
    add_subdirectory(gpu_tests)
endif()
