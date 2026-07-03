cmake_minimum_required(VERSION 3.17)

# Add include and lib directories
link_directories(/usr/local /usr/lib/x86_64-linux-gnu/lib ${DAQ_DIRECTORY}/lib)
include_directories(/usr/lib/x86_64-linux-gnu/include ${CMAKE_INSTALL_PREFIX}/include)
include_directories(${DAQ_DIRECTORY}/include)

project(AAVS_DAQ C CXX)

# Add options to compile the two independent correlators. Each pulls in its
# own GPU dependency (xGPU vs Tensor-Core-Correlator/cudawrappers) and neither
# requires the other, so they can be built alone or together.
option(WITH_CORRELATOR "Compile cross-correlator which uses xGPU" OFF)
option(WITH_TCC "Compile Tensor-Core-Correlator (TCC) GPU correlator" OFF)
option(WITH_SMALL_STATION "Compile a separate library for 48 element stations" OFF)
message(STATUS "xGPU correlator compilation: ${WITH_CORRELATOR}")
message(STATUS "TCC correlator compilation: ${WITH_TCC}")
message(STATUS "48-element station compilation: ${WITH_SMALL_STATION}")

link_directories(${CMAKE_INSTALL_PREFIX}/lib)

# CMAKE compilation flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++17 -D_REENTRANT -fPIC -funroll-loops -O3 -msse4 -mavx2 -g")

# Source files
set(AAVS_FILES RawData.cpp
        RawData.h
        ChannelisedData.cpp
        ChannelisedData.h
        BeamformedData.cpp
        BeamformedData.h
        StationData.cpp
        StationData.h
        StationDataRaw.h
        StationDataRaw.cpp
        AntennaBuffer.cpp
        AntennaBuffer.h)

# Add xGPU cross-correlator sources if required (needs xgpu.h / libxgpu)
if (WITH_CORRELATOR)
    add_definitions(-DWITH_CORRELATOR)
    list(APPEND AAVS_FILES DoubleBuffer.cpp
                           DoubleBuffer.h
                           CorrelatorData.cpp
                           CorrelatorData.h
                           StandaloneCorrelator.cpp)
endif()

# Add the TCC correlator library if required. Independent of WITH_CORRELATOR:
# only needs the CUDA toolkit, not xgpu.h/libxgpu.
if (WITH_TCC)
    add_definitions(-DWITH_TCC)
    add_library(aavsdaq_tcc SHARED
        DoubleBuffer.cpp
        DoubleBuffer.h
        multi_array.h
        TensorCorrelatorData.cpp
        TensorCorrelatorData.h
        TccDoubleBuffer.cpp
        TccDoubleBuffer.h
    )
endif()

# CMAKE compilation flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++17 -D_REENTRANT -fPIC -funroll-loops -O3 -msse4 -mavx2 -g")

# Source file for raw station beam acquisition
set(STATION_BEAM_FILES StationDataRaw.cpp
        StationData.h
        acquire_station_beam.cpp
        acquire_station_beam.h)

# Compile library
add_library(aavsdaq SHARED ${AAVS_FILES})

# Compile AAVSDAQ library
if (WITH_CORRELATOR)
    target_link_libraries(aavsdaq daq xgpu ${CMAKE_THREAD_LIBS_INIT})

    if (WITH_SMALL_STATION)
        # Compile a different library using xgpu for 48 antennas
        add_library(aavsdaq48 SHARED ${AAVS_FILES} )
        target_link_libraries(aavsdaq48 daq xgpu48 ${MAKE_THREAD_LIBS_INIT})
    endif()
else()
    target_link_libraries(aavsdaq daq ${CMAKE_THREAD_LIBS_INIT})
endif()

# Build and link the TCC correlator library. Independent of WITH_CORRELATOR:
# only needs a CUDA toolkit, never touches xgpu.h/libxgpu.
if (WITH_TCC)
    find_package(CUDAToolkit REQUIRED)
    if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
        set(CMAKE_CUDA_ARCHITECTURES 80)
    endif()
    enable_language(CUDA)

    # Build the Tensor-Core-Correlator (and the cudawrappers dependency it pulls
    # in) from source, pinned to the same commit the Docker image builds against.
    # Defines the `tcc`, `cudawrappers::cu` and `cudawrappers::nvrtc` targets.
    include(FetchContent)
    set(BUILD_TESTING OFF CACHE BOOL "Disable TCC's bundled test suite" FORCE)
    FetchContent_Declare(
        tensor_core_correlator
        GIT_REPOSITORY https://git.astron.nl/RD/tensor-core-correlator.git
        GIT_TAG        00a9b7b2f826bc3eac26a5368f4a604e33061e6e
    )
    FetchContent_MakeAvailable(tensor_core_correlator)

    # TCC's CMake assumes it is the top-level project: it derives the `tcc`
    # target's public include path from ${CMAKE_SOURCE_DIR}, which resolves to
    # THIS project (not the TCC tree) when built as a FetchContent subproject.
    # Point it at the real TCC source/binary roots so its own sources and ours
    # can resolve "libtcc/..." and TCC-Config.h.
    target_include_directories(tcc PUBLIC
        $<BUILD_INTERFACE:${tensor_core_correlator_SOURCE_DIR}>
        $<BUILD_INTERFACE:${tensor_core_correlator_BINARY_DIR}>)

    target_link_libraries(aavsdaq_tcc daq tcc cudawrappers::cu cudawrappers::nvrtc)

    # tcc is built from source here (not a system install under /usr/local/lib
    # like before), so it must be installed and made findable at runtime.
    # aavsdaq_tcc.so is dlopen'd from Python by absolute path (no LD_LIBRARY_PATH
    # guarantee), so give it an $ORIGIN rpath and install libtcc.so right next to
    # it, rather than relying on ldconfig/LD_LIBRARY_PATH covering the install dir.
    set_target_properties(aavsdaq_tcc PROPERTIES
        BUILD_WITH_INSTALL_RPATH FALSE
        INSTALL_RPATH "$ORIGIN")
endif()

# Compile raw station beam library
add_library(aavsstationbeam SHARED ${STATION_BEAM_FILES})
set_target_properties(aavsstationbeam PROPERTIES PUBLIC_HEADER "acquire_station_beam.h")
target_link_libraries(aavsstationbeam aavsdaq ${MAKE_THREAD_LIBS_INIT})

# Install raw station beam library
install(TARGETS "aavsstationbeam"
        DESTINATION ${CMAKE_INSTALL_PREFIX}/lib
        PUBLIC_HEADER DESTINATION ${CMAKE_INSTALL_PREFIX}/include)

# Create executable
add_executable(test_aavs test_aavs.cpp)
target_link_libraries(test_aavs aavsdaq)

# Create executable
add_executable(acquire_station_beam acquire_station_beam.cpp)
target_link_libraries(acquire_station_beam aavsdaq)

# Install library
install(TARGETS "aavsdaq" DESTINATION ${CMAKE_INSTALL_PREFIX}/lib)
if (WITH_TCC)
  install(TARGETS aavsdaq_tcc DESTINATION ${CMAKE_INSTALL_PREFIX}/lib)
  # libtcc.so has no system-wide install of its own anymore (see FetchContent
  # above) — install it next to aavsdaq_tcc.so so its $ORIGIN rpath finds it.
  # LIBRARY DESTINATION (not a bare DESTINATION) so CMake doesn't also try to
  # install tcc's PUBLIC_HEADER files here — those resolve relative to *this*
  # directory's scope, not TCC's, and cdaq has no such headers.
  install(TARGETS tcc LIBRARY DESTINATION ${CMAKE_INSTALL_PREFIX}/lib)
endif()

if (WITH_SMALL_STATION)
    install(TARGETS "aavsdaq48" DESTINATION ${CMAKE_INSTALL_PREFIX}/lib)
endif()
