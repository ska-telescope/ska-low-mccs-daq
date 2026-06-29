cmake_minimum_required(VERSION 3.14)
project(TccSplitRingTests CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Coverage flags — included in the binary so gcov/gcovr can report lines.
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fprofile-arcs -ftest-coverage -O0 -g")

# The cdaq source tree holds the headers under test (TccSplitRing.h plus the
# per-mode consumer/container headers). It does NOT contain DAQ.h — that always
# comes from the real aavs-daq tree fetched below.
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
# Every C++ test builds against the genuine aavs-daq library — no DAQ stubbing.
# Fetch it from source (same mechanism as googletest above) pinned to the SHA the
# rest of the project builds against (see Dockerfile AAVS_DAQ_SHA). Only the
# source is downloaded — aavs-daq's own CMakeLists lives in src/ and pulls in
# extra dependencies we don't need, which we bypass by compiling the core ourselves.
#
# Always fetch the pinned revision from the remote: clear CMake's built-in
# FETCHCONTENT_SOURCE_DIR override so a local checkout can never be substituted,
# guaranteeing every build (CI and dev) compiles the same source.
set(FETCHCONTENT_SOURCE_DIR_AAVS_DAQ "" CACHE PATH "" FORCE)
FetchContent_Declare(
    aavs_daq
    GIT_REPOSITORY https://gitlab.com/ska-telescope/aavs-daq.git
    GIT_TAG        68e5953acd7a778ea37278f38679e5ca30636e69
)
FetchContent_GetProperties(aavs_daq)
if(NOT aavs_daq_POPULATED)
    FetchContent_Populate(aavs_daq)
endif()
set(AAVS_DAQ_SRC ${aavs_daq_SOURCE_DIR}/src)

# The genuine library code (logging, ring buffer, network receiver), compiled
# once and shared by every test.
add_library(aavsdaq_real STATIC
    ${AAVS_DAQ_SRC}/DAQ.cpp
    ${AAVS_DAQ_SRC}/NetworkReceiver.cpp
    ${AAVS_DAQ_SRC}/RingBuffer.cpp
)
target_include_directories(aavsdaq_real PUBLIC ${AAVS_DAQ_SRC})
target_link_libraries(aavsdaq_real PUBLIC pthread dl)

# Helper: one executable per test, linked against the real aavs-daq core. Mode
# headers define extern "C" consumer factories that pull in the (unused)
# consumer classes; -ffunction-sections + --gc-sections lets the linker drop
# them so only the code under test links.
function(add_aavsdaq_test name)
    add_executable(${name} ${name}.cpp)
    target_include_directories(${name} BEFORE PRIVATE ${AAVS_DAQ_SRC})
    target_compile_options(${name} PRIVATE -ffunction-sections -fdata-sections)
    target_link_options(${name} PRIVATE -Wl,--gc-sections)
    target_link_libraries(${name} PRIVATE GTest::gtest_main aavsdaq_real)
    gtest_discover_tests(${name})
endfunction()

# ── TccSplitRing test ────────────────────────────────────────────────────────────
# TccSplitRing.cpp uses the real DAQ.h/LOG (from aavsdaq_real) but pulls in
# cudawrappers, which we replace with a header-only stub so the ring logic can be
# tested without CUDA. The stub lives in stubs/ (not next to the test sources) so
# it only shadows cudawrappers for this target and never another test's includes.
add_executable(test_tcc_split_ring
    test_tcc_split_ring.cpp
    ${CDAQ_SRC}/TccSplitRing.cpp
)
target_include_directories(test_tcc_split_ring BEFORE PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/stubs  # cudawrappers stub only
    ${AAVS_DAQ_SRC}                    # real DAQ.h
)
target_compile_options(test_tcc_split_ring PRIVATE -ffunction-sections -fdata-sections)
target_link_options(test_tcc_split_ring PRIVATE -Wl,--gc-sections)
target_link_libraries(test_tcc_split_ring PRIVATE GTest::gtest_main aavsdaq_real)
gtest_discover_tests(test_tcc_split_ring)

# ── Per-mode data container tests ────────────────────────────────────────────────
add_aavsdaq_test(test_raw_data)
add_aavsdaq_test(test_channelised_data)
add_aavsdaq_test(test_beamformed_data)
add_aavsdaq_test(test_antenna_buffer)

# ── Per-mode consumer (processPacket / SPEAD-parsing) tests ──────────────────────
# These #include the mode .cpp directly (single TU), so no extra source is linked.
add_aavsdaq_test(test_raw_data_consumer)
add_aavsdaq_test(test_antenna_buffer_consumer)

# ── aavs-daq core tests (ring buffer + C API entry points) ───────────────────────
add_aavsdaq_test(test_ring_buffer)
add_aavsdaq_test(test_daq)

# ── GPU correlator tests (TensorCorrelatorData) ──────────────────────────────────
# TensorCorrelatorData needs the CUDA toolkit, cudawrappers and libtcc to compile,
# plus a physical GPU to run (it JITs and launches Tensor-Core-Correlator kernels).
# We only add the target when all of that is present, so CPU-only builds (most CI
# and dev boxes) still configure and run the other suites unaffected.
#
# Override with -DBUILD_GPU_TESTS=ON (require it; error if deps missing) or =OFF
# (never build it). The default, AUTO, builds it iff the toolchain and a GPU are
# detected.
set(BUILD_GPU_TESTS "AUTO" CACHE STRING "Build CUDA/TCC correlator tests: AUTO, ON or OFF")
set_property(CACHE BUILD_GPU_TESTS PROPERTY STRINGS AUTO ON OFF)

# Compile-time dependencies.
find_package(CUDAToolkit QUIET)
find_package(cudawrappers QUIET)
find_package(libtcc QUIET)
set(_gpu_toolchain FALSE)
if(CUDAToolkit_FOUND AND cudawrappers_FOUND AND libtcc_FOUND)
    set(_gpu_toolchain TRUE)
endif()

# Run-time dependency: a real GPU, probed via nvidia-smi at configure time.
set(_gpu_device FALSE)
find_program(NVIDIA_SMI nvidia-smi)
if(NVIDIA_SMI)
    execute_process(COMMAND ${NVIDIA_SMI} -L
                    RESULT_VARIABLE _smi_rc OUTPUT_VARIABLE _smi_out ERROR_QUIET)
    if(_smi_rc EQUAL 0 AND _smi_out MATCHES "GPU [0-9]")
        set(_gpu_device TRUE)
    endif()
endif()

# Resolve AUTO / ON / OFF into a decision.
if(BUILD_GPU_TESTS STREQUAL "OFF")
    set(_build_gpu FALSE)
elseif(BUILD_GPU_TESTS STREQUAL "ON")
    if(NOT _gpu_toolchain)
        message(FATAL_ERROR "BUILD_GPU_TESTS=ON but CUDAToolkit/cudawrappers/libtcc not all found")
    endif()
    set(_build_gpu TRUE)  # honour explicit request even on a build node without a GPU
else()  # AUTO
    if(_gpu_toolchain AND _gpu_device)
        set(_build_gpu TRUE)
    else()
        set(_build_gpu FALSE)
    endif()
endif()

if(_build_gpu)
    message(STATUS "Building GPU correlator tests (toolchain + GPU detected)")
    # Compiles the real TensorCorrelatorData against real cudawrappers/libtcc — the
    # cudawrappers stub used by test_tcc_split_ring is NOT on this target's path.
    add_executable(test_tensor_correlator
        test_tensor_correlator.cpp
        ${CDAQ_SRC}/TensorCorrelatorData.cpp
        ${CDAQ_SRC}/TccSplitRing.cpp
    )
    target_include_directories(test_tensor_correlator BEFORE PRIVATE ${AAVS_DAQ_SRC})
    target_compile_options(test_tensor_correlator PRIVATE -ffunction-sections -fdata-sections)
    target_link_options(test_tensor_correlator PRIVATE -Wl,--gc-sections)
    target_link_libraries(test_tensor_correlator PRIVATE
        GTest::gtest_main aavsdaq_real
        cudawrappers::cu cudawrappers::nvrtc tcc CUDA::cudart)
    gtest_discover_tests(test_tensor_correlator)
else()
    message(STATUS "Skipping GPU correlator tests "
                   "(toolchain=${_gpu_toolchain} gpu=${_gpu_device} BUILD_GPU_TESTS=${BUILD_GPU_TESTS})")
endif()
