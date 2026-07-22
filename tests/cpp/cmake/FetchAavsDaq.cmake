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
    # Patch RealTimeThread for the SCHED_FIFO-unavailable fallback (see the module
    # for the why and the exact before/after).
    include(PatchRealTimeThread)
endif()
set(AAVS_DAQ_SRC ${aavs_daq_SOURCE_DIR}/src)

add_library(aavsdaq STATIC
    ${AAVS_DAQ_SRC}/DAQ.cpp
    ${AAVS_DAQ_SRC}/NetworkReceiver.cpp
    ${AAVS_DAQ_SRC}/RingBuffer.cpp
)
target_include_directories(aavsdaq PUBLIC ${AAVS_DAQ_SRC})
target_link_libraries(aavsdaq PUBLIC pthread dl)
