cmake_minimum_required(VERSION 3.18)

# Add include and lib directories
link_directories(/usr/local /usr/lib/x86_64-linux-gnu/lib)
include_directories(/usr/lib/x86_64-linux-gnu/include ${CMAKE_INSTALL_PREFIX}/include)

project(AAVS_DAQ C CXX)

# The helper modules are in cmake/. This makes include(<name>) find them.
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/cmake)

# Defines the `daq` target, which supplies libdaq.so and the DAQ headers these
# sources include. Every library below links to it.
include(FetchAavsDaq)

# The correlator is built as its own library, because it is the only part of
# this project that needs a GPU toolchain (Tensor-Core-Correlator/cudawrappers).
option(WITH_TCC "Compile Tensor-Core-Correlator (TCC) GPU correlator" OFF)
message(STATUS "TCC correlator compilation: ${WITH_TCC}")

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

# Add the TCC correlator library if required.
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
target_link_libraries(aavsdaq daq ${CMAKE_THREAD_LIBS_INIT})

# Build and link the TCC correlator library.
if (WITH_TCC)
    find_package(CUDAToolkit REQUIRED)
    if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
        set(CMAKE_CUDA_ARCHITECTURES 80)
    endif()
    enable_language(CUDA)

    # Builds the `tcc`, `cudawrappers::cu` and `cudawrappers::nvrtc` targets
    # from source at a pinned commit.
    include(FetchTensorCorrelator)

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

# This project now builds libdaq.so (see FetchAavsDaq) and installs it beside
# these libraries instead of taking it from a system-wide install. Python dlopens
# libaavsdaq.so by absolute path, so give them an $ORIGIN rpath rather than rely
# on LD_LIBRARY_PATH, as for aavsdaq_tcc above.
set_target_properties(aavsdaq aavsstationbeam PROPERTIES
    BUILD_WITH_INSTALL_RPATH FALSE
    INSTALL_RPATH "$ORIGIN")

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
  # libtcc.so has no system-wide install now (see FetchTensorCorrelator), so it
  # goes beside aavsdaq_tcc.so for the $ORIGIN rpath to find. LIBRARY DESTINATION
  # and not a plain DESTINATION, which would also install the PUBLIC_HEADER files
  # of tcc. Those resolve against this directory, and cdaq has no such headers.
  install(TARGETS tcc LIBRARY DESTINATION ${CMAKE_INSTALL_PREFIX}/lib)
endif()
