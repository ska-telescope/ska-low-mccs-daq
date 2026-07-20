# GPU test targets. The parent only adds this subdirectory when EnsureCuda set
# _build_gpu and after FetchTensorCorrelator defined the tcc / cudawrappers
# targets, so everything linked below is guaranteed to exist here.
#
# Inherited from the parent scope: CDAQ_SRC, TEST_CPP_ROOT (spead_test_util.h),
# AAVS_DAQ_SRC and the aavsdaq / GTest::gtest_main / tcc / cudawrappers targets.

# ── TccDoubleBuffer unit test ─────────────────────────────────────────────────────
# The buffer sources call cu::init()/cu::HostMemory, so they need the real
# cudawrappers headers and CUDA runtime; this is a GPU target for that reason.
# AAVS_DAQ_SRC supplies DAQ.h and Utils.h.
add_executable(test_tcc_double_buffer
    test_tcc_double_buffer.cpp
    ${CDAQ_SRC}/TccDoubleBuffer.cpp
    ${CDAQ_SRC}/DoubleBuffer.cpp
)
target_include_directories(test_tcc_double_buffer PRIVATE ${AAVS_DAQ_SRC})
target_link_libraries(test_tcc_double_buffer PRIVATE
    GTest::gtest_main aavsdaq cudawrappers::cu cudawrappers::nvrtc CUDA::cudart)
gtest_discover_tests(test_tcc_double_buffer)

# ── TensorCorrelator test ─────────────────────────────────────────────────────────
# Compiles TensorCorrelatorData against the fetched cudawrappers/libtcc.
# AAVS_DAQ_SRC supplies DAQ.h and Utils.h; the cudawrappers headers come from the
# linked cudawrappers::cu/::nvrtc targets.
add_executable(test_tensor_correlator
    test_tensor_correlator.cpp
    ${CDAQ_SRC}/TensorCorrelatorData.cpp
    ${CDAQ_SRC}/TccDoubleBuffer.cpp
    ${CDAQ_SRC}/DoubleBuffer.cpp
)
target_include_directories(test_tensor_correlator PRIVATE ${AAVS_DAQ_SRC})
target_compile_options(test_tensor_correlator PRIVATE -ffunction-sections -fdata-sections)
target_link_options(test_tensor_correlator PRIVATE -Wl,--gc-sections)
target_link_libraries(test_tensor_correlator PRIVATE
    GTest::gtest_main aavsdaq
    cudawrappers::cu cudawrappers::nvrtc tcc CUDA::cudart)
gtest_discover_tests(test_tensor_correlator)
