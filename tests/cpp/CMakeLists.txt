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
# The integrated-channel and GPU correlator tests drive the full DataConsumer
# pipeline (ring buffer + processPacket), so they need the real aavs-daq sources,
# not the DAQ.h stub the buffer unit test uses. Fetch it pinned to the SHA the rest
# of the project builds against (see Dockerfile AAVS_DAQ_SHA). Only the source is
# downloaded - aavs-daq's own CMakeLists pulls in extra dependencies we don't need,
# which we bypass by compiling the core ourselves into aavsdaq_real.
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
# real aavs-daq sources. Shared by the integrated-channel and GPU correlator tests.
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

# ── GPU correlator tests (TensorCorrelatorData) ──────────────────────────────────
# TensorCorrelatorData needs the CUDA toolkit, cudawrappers and libtcc to compile,
# plus a physical GPU to run (it JITs and launches Tensor-Core-Correlator kernels).
# We only add the target when all of that is present, so CPU-only builds (most CI
# and dev boxes) still configure and run the buffer suite unaffected.
#
# Override with -DBUILD_GPU_TESTS=ON (require it; error if deps missing) or =OFF
# (never build it). The default, AUTO, builds it iff the toolchain and a GPU are
# detected.
set(BUILD_GPU_TESTS "AUTO" CACHE STRING "Build CUDA/TCC correlator tests: AUTO, ON or OFF")
set_property(CACHE BUILD_GPU_TESTS PROPERTY STRINGS AUTO ON OFF)

# Compile-time dependency: a working CUDA toolkit (compiler + runtime).
# cudawrappers and libtcc do NOT need to be pre-installed - they are built from
# source via FetchContent below (the same mechanism used for googletest and
# aavs-daq), so the only thing that can gate the build is a CUDA compiler, which
# we cannot fetch.
find_package(CUDAToolkit QUIET)
include(CheckLanguage)
check_language(CUDA)
set(_gpu_toolchain FALSE)
if(CUDAToolkit_FOUND AND CMAKE_CUDA_COMPILER)
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
        message(FATAL_ERROR "BUILD_GPU_TESTS=ON but no CUDA toolkit/compiler found")
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

    # The Tensor-Core-Correlator sources are CUDA; enable the language to compile
    # them. Pin the device architecture to one the local nvcc actually supports
    # (sm_80, matching the Docker image's CUDA_ARCH). The correlator kernel itself
    # is JIT-compiled by NVRTC against the running device's compute capability at
    # run time, so newer GPUs (e.g. sm_89) still work even though their arch is not
    # a compile target here.
    if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
        set(CMAKE_CUDA_ARCHITECTURES 80)
    endif()
    enable_language(CUDA)

    # Build the Tensor-Core-Correlator (and the cudawrappers dependency it pulls
    # in) from source, pinned to the same commit the Docker image builds against
    # (see Dockerfile: tensor-core-correlator git checkout). FetchContent defines
    # the `tcc`, `cudawrappers::cu` and `cudawrappers::nvrtc` targets linked below,
    # so no system-wide install of either is required. TCC's own test suite is
    # disabled - we only want the library targets.
    set(BUILD_TESTING OFF CACHE BOOL "Disable TCC's bundled test suite" FORCE)
    FetchContent_Declare(
        tensor_core_correlator
        GIT_REPOSITORY https://git.astron.nl/RD/tensor-core-correlator.git
        GIT_TAG        00a9b7b2f826bc3eac26a5368f4a604e33061e6e
    )
    FetchContent_MakeAvailable(tensor_core_correlator)

    # TCC's CMake assumes it is the top-level project: it derives the `tcc`
    # target's public include path from ${CMAKE_SOURCE_DIR}, which resolves to
    # THIS project (not the TCC tree) when TCC is built as a FetchContent
    # subproject. As a result neither TCC's own sources nor ours can resolve their
    # "libtcc/..." and TCC-Config.h includes. Point the target at the real TCC
    # source and binary roots so those headers are found here and by anything that
    # links `tcc`.
    target_include_directories(tcc PUBLIC
        $<BUILD_INTERFACE:${tensor_core_correlator_SOURCE_DIR}>
        $<BUILD_INTERFACE:${tensor_core_correlator_BINARY_DIR}>)

    # Compiles the real TensorCorrelatorData against the fetched cudawrappers/libtcc.
    # AAVS_DAQ_SRC is put on the path BEFORE the (global) cdaq include so the real
    # DAQ.h wins; the cudawrappers stub used by test_tcc_double_buffer is NOT on
    # this target's path - the real cudawrappers headers come from the linked
    # cudawrappers::cu/::nvrtc targets.
    add_executable(test_tensor_correlator
        test_tensor_correlator.cpp
        ${CDAQ_SRC}/TensorCorrelatorData.cpp
        ${CDAQ_SRC}/TccDoubleBuffer.cpp
        ${CDAQ_SRC}/DoubleBuffer.cpp
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
