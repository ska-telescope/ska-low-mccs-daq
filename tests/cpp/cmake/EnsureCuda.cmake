# Decide whether to build the GPU correlator tests, and prepare the CUDA language
# if so.
#
# TensorCorrelatorData needs the CUDA toolkit, cudawrappers and libtcc to compile,
# plus a physical GPU to run. We only build the GPU target when all of that is present
#
# Override with -DBUILD_GPU_TESTS=ON (require it; error if deps missing) or =OFF
# (never build it). The default, AUTO, builds it iff the toolchain and a GPU are
# detected.
#
# Provides:
#   _build_gpu - TRUE when the GPU tests should be built. When TRUE, the CUDA
#                language has been enabled and CMAKE_CUDA_ARCHITECTURES defaulted.
set(BUILD_GPU_TESTS "AUTO" CACHE STRING "Build CUDA/TCC correlator tests: AUTO, ON or OFF")
set_property(CACHE BUILD_GPU_TESTS PROPERTY STRINGS AUTO ON OFF)

# Return early if BUILD_GPU_TESTS=OFF.
if(BUILD_GPU_TESTS STREQUAL "OFF")
    set(_build_gpu FALSE)
    message(STATUS "Skipping GPU correlator tests (BUILD_GPU_TESTS=OFF)")
    return()
endif()

# Compile-time dependency: a working CUDA toolkit (compiler + runtime).
# cudawrappers and libtcc do NOT need to be pre-installed - they are built from
# source via FetchContent (see FetchTensorCorrelator), so the only thing that can
# gate the build is a CUDA compiler, which we cannot fetch.
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

# Resolve AUTO / ON into a decision (OFF handled and returned above).
if(BUILD_GPU_TESTS STREQUAL "ON")
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

    # Pin the device architecture to one the local nvcc actually supports (sm_80,
    # matching the Docker image's CUDA_ARCH). The correlator kernel itself is
    # JIT-compiled by NVRTC against the running device's compute capability at run
    # time, so newer GPUs (e.g. sm_89) still work even though their arch is not a
    # compile target here.
    if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
        set(CMAKE_CUDA_ARCHITECTURES 80)
    endif()
    enable_language(CUDA)
else()
    message(STATUS "Skipping GPU correlator tests "
                   "(toolchain=${_gpu_toolchain} gpu=${_gpu_device} BUILD_GPU_TESTS=${BUILD_GPU_TESTS})")
endif()
