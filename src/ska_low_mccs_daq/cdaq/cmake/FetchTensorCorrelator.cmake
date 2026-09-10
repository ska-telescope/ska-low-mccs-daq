# The Tensor-Core-Correlator, built from source at a pinned commit. Defines the
# `tcc`, `cudawrappers::cu` and `cudawrappers::nvrtc` targets, the last two from
# the cudawrappers dependency TCC declares itself, which follows its `main`
# branch. Include this module after the CUDA language is enabled. The C++ tests
# include it too (tests/cpp/CMakeLists.txt), so both builds use the same commit.
include(FetchContent)

set(BUILD_TESTING OFF CACHE BOOL "Disable TCC's bundled test suite" FORCE)

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
