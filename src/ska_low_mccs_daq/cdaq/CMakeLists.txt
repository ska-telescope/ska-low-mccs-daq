cmake_minimum_required(VERSION 3.10)

# Add include and lib directories
link_directories(/usr/local /usr/lib/x86_64-linux-gnu/lib ${DAQ_DIRECTORY}/lib)
include_directories(/usr/lib/x86_64-linux-gnu/include ${CMAKE_INSTALL_PREFIX}/include)
include_directories(${DAQ_DIRECTORY}/include)

project(AAVS_DAQ C CXX)

# Add option to compile correlator
option(WITH_CORRELATOR "Compile cross-correlator which uses xGPU" ON)
option(WITH_SMALL_STATION "Compile a separate library for 48 element stations" OFF)
message(STATUS "Correlator compilation: ${WITH_CORRELATOR}")
message(STATUS "48-element station compilation: ${WITH_SMALL_STATION}")

link_directories(${CMAKE_INSTALL_PREFIX}/lib)

# CMAKE compilation flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++14 -D_REENTRANT -fPIC -funroll-loops -O3 -msse4 -mavx2 -g")

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

# Add correlator if required
if (WITH_CORRELATOR)
    add_definitions(-DWITH_CORRELATOR)
    list(APPEND AAVS_FILES DoubleBuffer.cpp
                           DoubleBuffer.h
                           CorrelatorData.cpp
                           CorrelatorData.h
                           multi_array.h
                           TensorCorrelatorData.cpp
                           TensorCorrelatorData.h
                           TccDoubleBuffer.cpp
                           TccDoubleBuffer.h
                           StandaloneCorrelator.cpp)
endif()

# CMAKE compilation flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++14 -D_REENTRANT -fPIC -funroll-loops -O3 -msse4 -mavx2 -g")

# Source file for raw station beam acquisition
set(STATION_BEAM_FILES StationDataRaw.cpp
        StationData.h
        acquire_station_beam.cpp
        acquire_station_beam.h)

# Compile library
add_library(aavsdaq SHARED ${AAVS_FILES})

# Compile AAVSDAQ library
if (WITH_CORRELATOR)
    # Link required libraries

    find_package(CUDAToolkit REQUIRED)
    find_package(cudawrappers REQUIRED)
    find_package(libtcc REQUIRED)

    target_link_libraries(aavsdaq tcc cudawrappers::cu cudawrappers::nvrtc)
    target_link_libraries(aavsdaq daq xgpu ${CMAKE_THREAD_LIBS_INIT})

    if (WITH_SMALL_STATION)
        # Compile a different library using xgpu for 48 antennas
        add_library(aavsdaq48 SHARED ${AAVS_FILES} )
        target_link_libraries(aavsdaq48 daq xgpu48 ${MAKE_THREAD_LIBS_INIT})
    endif()
else()
    # Link required libraries
    target_link_libraries(aavsdaq daq ${CMAKE_THREAD_LIBS_INIT})
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

if (WITH_SMALL_STATION)
    install(TARGETS "aavsdaq48" DESTINATION ${CMAKE_INSTALL_PREFIX}/lib)
endif()

add_executable(tensor_ctor_test test_tcc_correlator.cpp)
target_link_libraries(tensor_ctor_test aavsdaq)
install(TARGETS tensor_ctor_test RUNTIME DESTINATION ${CMAKE_INSTALL_PREFIX}/bin)
