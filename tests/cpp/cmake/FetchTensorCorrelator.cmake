# Tensor-Core-Correlator (and the cudawrappers dependency it pulls in), built from
# source. Only meaningful when the GPU tests are being built, so include this after
# EnsureCuda has enabled the CUDA language.
include(FetchContent)

# Pin to the same commit the Docker image builds against (see Dockerfile:
# tensor-core-correlator git checkout). 
# TCC's own test suite is disabled - we only want the library targets.
set(BUILD_TESTING OFF CACHE BOOL "Disable TCC's bundled test suite" FORCE)
FetchContent_Declare(
    tensor_core_correlator
    GIT_REPOSITORY https://git.astron.nl/RD/tensor-core-correlator.git
    GIT_TAG        00a9b7b2f826bc3eac26a5368f4a604e33061e6e
)
FetchContent_MakeAvailable(tensor_core_correlator)

# TCC's CMake assumes it is the top-level project: it derives the `tcc` target's
# public include path from ${CMAKE_SOURCE_DIR}, which resolves to THIS project (not
# the TCC tree) when TCC is built as a FetchContent subproject. As a result neither
# TCC's own sources nor ours can resolve their "libtcc/..." and TCC-Config.h
# includes. Point the target at the real TCC source and binary roots so those
# headers are found here and by anything that links `tcc`.
target_include_directories(tcc PUBLIC
    $<BUILD_INTERFACE:${tensor_core_correlator_SOURCE_DIR}>
    $<BUILD_INTERFACE:${tensor_core_correlator_BINARY_DIR}>)
