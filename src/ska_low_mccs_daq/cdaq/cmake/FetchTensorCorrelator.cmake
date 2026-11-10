# The Tensor-Core-Correlator and its cudawrappers dependency, built from source
# at a pinned commit. Defines the `tcc`, `cudawrappers::cu` and
# `cudawrappers::nvrtc` targets. Include it after the CUDA language is enabled.
# The C++ tests include this same module (tests/cpp/CMakeLists.txt), so both
# builds use the same commit.
include(FetchContent)

set(TCC_BUILD_TESTING OFF CACHE BOOL "Disable TCC's bundled test suite" FORCE)

# TCC no longer sets a default for this, and the install rules in
# cdaq/CMakeLists.txt need libtcc.so rather than a static archive.
set(BUILD_SHARED_LIBS ON CACHE BOOL "Build TCC and cudawrappers as shared libraries" FORCE)

# TCC declares its cudawrappers and huge-page-allocator dependencies as
# `GIT_TAG main`, so pinning TCC alone pins nothing. On 2026-07-29 a cudawrappers
# commit started using CUDA 12 APIs that the CUDA 11.8 toolkit in these images
# lacks, and every build failed. FetchContent takes the FIRST declaration, so
# these override those floating tags. cudawrappers 1.0.0 is the last release
# before CUDA 12. Bump it with the base image.
FetchContent_Declare(
    cudawrappers
    GIT_REPOSITORY https://github.com/nlesc-recruit/cudawrappers.git
    GIT_TAG        1.0.0
)
FetchContent_Declare(
    huge-page-allocator
    GIT_REPOSITORY https://git.astron.nl/RD/huge-page-allocator.git
    GIT_TAG        6c1f59d96d288bc88014eaa9fee18662bd44b1e6
)
FetchContent_Declare(
    tensor_core_correlator
    GIT_REPOSITORY https://git.astron.nl/RD/tensor-core-correlator.git
    GIT_TAG        13e143301be1059caef7a351c8edb3ff800772c5
)
FetchContent_MakeAvailable(tensor_core_correlator)
