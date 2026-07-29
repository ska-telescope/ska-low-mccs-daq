# The Tensor-Core-Correlator and its cudawrappers dependency, built from source
# at a pinned commit. Defines the `tcc`, `cudawrappers::cu` and
# `cudawrappers::nvrtc` targets. Include it after the CUDA language is enabled.
# The C++ tests include this same module (tests/cpp/CMakeLists.txt), so both
# builds use the same commit.
include(FetchContent)

set(BUILD_TESTING OFF CACHE BOOL "Disable TCC's bundled test suite" FORCE)

# TCC declares its cudawrappers dependency as `GIT_TAG main`, so pinning TCC
# alone pins nothing. On 2026-07-29 a cudawrappers commit started using CUDA 12
# APIs that the CUDA 11.8 toolkit in these images lacks, and every build failed.
# FetchContent takes the FIRST declaration, so this one overrides that floating
# tag. 1.0.0 is the last release before CUDA 12. Bump it with the base image.
FetchContent_Declare(
    cudawrappers
    GIT_REPOSITORY https://github.com/nlesc-recruit/cudawrappers.git
    GIT_TAG        1.0.0
)
FetchContent_Declare(
    tensor_core_correlator
    GIT_REPOSITORY https://git.astron.nl/RD/tensor-core-correlator.git
    GIT_TAG        00a9b7b2f826bc3eac26a5368f4a604e33061e6e
)
FetchContent_MakeAvailable(tensor_core_correlator)

# TCC derives the public include path of `tcc` from ${CMAKE_SOURCE_DIR}, which
# points at this project when TCC is a FetchContent subproject. Neither the TCC
# sources nor these then resolve "libtcc/..." and TCC-Config.h, so point the
# target at the real TCC roots.
target_include_directories(tcc PUBLIC
    $<BUILD_INTERFACE:${tensor_core_correlator_SOURCE_DIR}>
    $<BUILD_INTERFACE:${tensor_core_correlator_BINARY_DIR}>)
