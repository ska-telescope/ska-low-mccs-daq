cmake_minimum_required(VERSION 2.8)

project(AAVS_DAQ C CXX)

find_package(Threads REQUIRED)

if (WITH_BCC)
    include_directories("/usr/include/bcc")
endif()

# CMAKE compilation flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++14 -D_REENTRANT -fPIC -funroll-loops -O3 -msse4 -mavx -g")

# Source files
set(SOURCE_FILES
    NetworkReceiver.cpp
    RingBuffer.cpp
    RealTimeThread.h
    DAQ.cpp
    Utils.h
    JSON.hpp)

# Enable BCC if required
if (WITH_BCC)
    add_definitions(-DWITH_BCC)
endif()

# Create shared library
add_library(daq SHARED ${SOURCE_FILES} )
set_target_properties(daq PROPERTIES PUBLIC_HEADER 
                      "RealTimeThread.h;Utils.h;DAQ.h;JSON.hpp;NetworkReceiver.h;SPEAD.h;RingBuffer.h")
if (WITH_BCC)
    target_link_libraries(daq dl numa bcc ${CMAKE_THREAD_LIBS_INIT})
else()
    target_link_libraries(daq dl numa ${CMAKE_THREAD_LIBS_INIT})
endif()

add_executable(receiver receiver.cpp)
target_link_libraries(receiver daq)

# Install library
install(TARGETS "daq" 
        LIBRARY DESTINATION ${CMAKE_INSTALL_PREFIX}/lib
        PUBLIC_HEADER DESTINATION ${CMAKE_INSTALL_PREFIX}/include)
