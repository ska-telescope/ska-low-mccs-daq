# Patch aavs-daq's RealTimeThread to fall back to SCHED_OTHER when SCHED_FIFO is
# unavailable (no CAP_SYS_NICE), so the GPU correlator thread starts in
# unprivileged CI environments.
#
# Expects aavs_daq_SOURCE_DIR to be set (by FetchContent) before inclusion.
#
# The search/replace bodies below are CMake *bracket arguments* ([==[ ... ]==]):
# raw, unescaped, multi-line strings, so the C++ reads as real code. The leading
# newline right after the opening bracket is dropped by CMake, and indentation
# must match RealTimeThread.h exactly (12 spaces) for the match to land.

set(_rt_h "${aavs_daq_SOURCE_DIR}/src/RealTimeThread.h")
file(READ "${_rt_h}" _rt_content)

set(_rt_search [==[
            // Create thread
            ret = pthread_create(&_thread, &attr, threadEntryFunc, this);

            // Reset scheduling]==])

set(_rt_replace [==[
            // Create thread
            ret = pthread_create(&_thread, &attr, threadEntryFunc, this);

            // Fall back to default scheduling if SCHED_FIFO is unavailable (e.g. no CAP_SYS_NICE)
            if (ret != 0) {
                pthread_attr_destroy(&attr);
                pthread_attr_init(&attr);
                ret = pthread_create(&_thread, &attr, threadEntryFunc, this);
                if (ret != 0)
                    perror("Failed to create thread with fallback scheduling");
            }

            // Reset scheduling]==])

string(REPLACE "${_rt_search}" "${_rt_replace}" _rt_content "${_rt_content}")

# string(REPLACE) silently no-ops if the search text is absent (e.g. upstream
# reworded/reformatted at the pinned SHA). Fail loudly rather than shipping a
# binary that dies with an opaque pthread_create EPERM in unprivileged CI.
string(FIND "${_rt_content}" "Fall back to default scheduling" _rt_patched)
if(_rt_patched EQUAL -1)
    message(FATAL_ERROR "RealTimeThread.h SCHED_FIFO-fallback patch did not apply "
                        "(search text not found in ${_rt_h}); the pinned aavs-daq "
                        "source may have changed — update PatchRealTimeThread.cmake.")
endif()

file(WRITE "${_rt_h}" "${_rt_content}")
