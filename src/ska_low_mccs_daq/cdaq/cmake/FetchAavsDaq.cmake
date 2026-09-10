# The AAVS DAQ C++ core (libdaq) that cdaq is built on, from the source
# AavsDaqSource fetches.
include(AavsDaqSource)

find_package(Threads REQUIRED)

# SHARED, unlike the static library the C++ tests build from the same sources,
# because pydaq opens libdaq.so with ctypes.CDLL (see pydaq/interface.py). Flags
# follow aavs-daq, without WITH_BCC.
add_library(daq SHARED ${AAVS_DAQ_SOURCES})
target_compile_options(daq PRIVATE -D_REENTRANT -funroll-loops -O3 -msse4 -mavx -g)
target_compile_features(daq PUBLIC cxx_std_14)
set_target_properties(daq PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    PUBLIC_HEADER "${AAVS_DAQ_SRC}/RealTimeThread.h;${AAVS_DAQ_SRC}/Utils.h;${AAVS_DAQ_SRC}/DAQ.h;${AAVS_DAQ_SRC}/JSON.hpp;${AAVS_DAQ_SRC}/NetworkReceiver.h;${AAVS_DAQ_SRC}/SPEAD.h;${AAVS_DAQ_SRC}/RingBuffer.h")

# PUBLIC, because the cdaq sources include "DAQ.h", "RingBuffer.h" and the rest
# directly.
target_include_directories(daq PUBLIC ${AAVS_DAQ_SRC})
target_link_libraries(daq PUBLIC dl Threads::Threads)

# Into the same lib directory as the cdaq libraries that link it, because their
# $ORIGIN rpath resolves libdaq.so there. pydaq also opens it by absolute path at
# ${DAQ_INSTALL}/lib/libdaq.so (see pydaq/interface.py).
install(TARGETS daq
        LIBRARY DESTINATION ${CMAKE_INSTALL_PREFIX}/lib
        PUBLIC_HEADER DESTINATION ${CMAKE_INSTALL_PREFIX}/include)
