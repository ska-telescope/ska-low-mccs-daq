# Fetches the AAVS DAQ source at the commit this project pins, defined here and
# nowhere else. Only the source is populated, because the product build
# (FetchAavsDaq) makes a shared libdaq.so from it and the C++ tests
# (tests/cpp/cmake/FetchAavsDaq.cmake) patch it into a static library.
#
#   AAVS_DAQ_SRC       the populated src/ directory, also the include path
#   AAVS_DAQ_SOURCES   the translation units of the DAQ core
include(FetchContent)

set(FETCHCONTENT_SOURCE_DIR_AAVS_DAQ "" CACHE PATH "" FORCE)
FetchContent_Declare(
    aavs_daq
    GIT_REPOSITORY https://gitlab.com/ska-telescope/aavs-daq.git
    GIT_TAG        68e5953acd7a778ea37278f38679e5ca30636e69
)
# This populates the source and defines no targets. The repository root of
# aavs-daq holds no CMakeLists.txt, because its build files are in src/, so
# MakeAvailable skips its add_subdirectory step. That is what this module wants,
# for the reasons given below.
FetchContent_MakeAvailable(aavs_daq)

set(AAVS_DAQ_SRC ${aavs_daq_SOURCE_DIR}/src)

# The src/CMakeLists.txt of aavs-daq stays unused on purpose. It builds one fixed
# library, and this project needs two from the same sources. It makes `daq`
# SHARED, which the product build needs, because pydaq opens libdaq.so with
# ctypes.CDLL. The C++ tests need a static library. The tests also rewrite
# RealTimeThread.h before they compile it (see PatchRealTimeThread), so they need
# the raw source.
# Including that file would add its `receiver` executable and its
# install(TARGETS daq) to whichever project pulled it in. Its project(AAVS_DAQ)
# name and its c++14 CMAKE_CXX_FLAGS would collide with cdaq, and it sets no
# target_include_directories, so a consumer gains no include path from it. It
# declares cmake_minimum_required(VERSION 2.8) as well. CMake 3.x accepts that
# with a deprecation warning, and CMake 4.0 refuses it.
#
# These are the same translation units as its `daq` library.
set(AAVS_DAQ_SOURCES
    ${AAVS_DAQ_SRC}/DAQ.cpp
    ${AAVS_DAQ_SRC}/NetworkReceiver.cpp
    ${AAVS_DAQ_SRC}/RingBuffer.cpp
)
