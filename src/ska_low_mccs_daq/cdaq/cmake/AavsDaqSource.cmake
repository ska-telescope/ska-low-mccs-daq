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
FetchContent_GetProperties(aavs_daq)
if(NOT aavs_daq_POPULATED)
    FetchContent_Populate(aavs_daq)
endif()

set(AAVS_DAQ_SRC ${aavs_daq_SOURCE_DIR}/src)

# The CMakeLists.txt of aavs-daq is unused, because it declares
# cmake_minimum_required(VERSION 2.8), which modern CMake refuses. These are the
# same translation units as its `daq` library.
set(AAVS_DAQ_SOURCES
    ${AAVS_DAQ_SRC}/DAQ.cpp
    ${AAVS_DAQ_SRC}/NetworkReceiver.cpp
    ${AAVS_DAQ_SRC}/RingBuffer.cpp
)
