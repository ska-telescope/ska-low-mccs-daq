# The DAQ core the tests link to. AavsDaqSource, shared with the product build,
# fetches the source and holds the pinned commit.
include(AavsDaqSource)

# Adds the fallback for when SCHED_FIFO is unavailable (the module has the
# detail). Only the test binaries need it, as they run unprivileged on CI.
include(PatchRealTimeThread)

# STATIC and without libnuma, unlike the shared libdaq.so the product build
# installs, because nothing dlopens this one.
add_library(aavsdaq STATIC ${AAVS_DAQ_SOURCES})
target_include_directories(aavsdaq PUBLIC ${AAVS_DAQ_SRC})
target_link_libraries(aavsdaq PUBLIC pthread dl)
