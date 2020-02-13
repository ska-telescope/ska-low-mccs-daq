cmake_minimum_required(VERSION 2.8)

# Add include and lib directories
link_directories(/usr/local /usr/lib/x86_64-linux-gnu/lib ${DAQ_DIRECTORY}/lib)
include_directories(/usr/lib/x86_64-linux-gnu/include )
include_directories(${DAQ_DIRECTORY}/include)

project(AAVS_DAQ C CXX)

# Add option to compile correlator
option(WITH_CORRELATOR "Compile cross-correlator which uses xGPU" OFF)
option(WITH_SMALL_STATION "Compile a separate library for 48 element stations" OFF)
message(STATUS "Correlator compilation: ${WITH_CORRELATOR}")
message(STATUS "48-element station compilation: ${WITH_SMALL_STATION}")

link_directories(/opt/aavs/lib)

# CMAKE compilation flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++14 -D_REENTRANT -fPIC -funroll-loops -O3 -msse4 -mavx -g")

# Souce files
set(AAVS_FILES RawData.cpp
        RawData.h
        ChannelisedData.cpp
        ChannelisedData.h
        BeamformedData.cpp
        BeamformedData.h
        StationData.cpp
        StationData.h)

# Add correlator if required
if (WITH_CORRELATOR)
    add_definitions(-DWITH_CORRELATOR)
    list(APPEND AAVS_FILES DoubleBuffer.cpp
                           DoubleBuffer.h
                           CorrelatorData.cpp
                           CorrelatorData.h
                            StandaloneCorrelator.cpp)
endif()

# CMAKE compilation flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++14 -D_REENTRANT -fPIC -funroll-loops -O3 -msse4 -mavx -g")

# Compile library
add_library(aavsdaq SHARED ${AAVS_FILES} )

# Compile library
if (WITH_CORRELATOR)
    # Link required libraries
    target_link_libraries(aavsdaq daq xgpu_aavs ${CMAKE_THREAD_LIBS_INIT})

    if (WITH_SMALL_STATION)
        # Compile a different library using xgpu for 48 antennas
        add_library(aavsdaq48 SHARED ${AAVS_FILES} )
        target_link_libraries(aavsdaq48 daq xgpu48 ${MAKE_THREAD_LIBS_INIT})
    endif()
else()
    # Link required libraries
    target_link_libraries(aavsdaq daq ${CMAKE_THREAD_LIBS_INIT})
endif()

# Create executable
add_executable(test_aavs test_aavs.cpp)
target_link_libraries(test_aavs aavsdaq)

# Install library
install(TARGETS "aavsdaq" DESTINATION ${CMAKE_INSTALL_PREFIX}/lib)

if (WITH_SMALL_STATION)
    install(TARGETS "aavsdaq48" DESTINATION ${CMAKE_INSTALL_PREFIX}/lib)
endif()
