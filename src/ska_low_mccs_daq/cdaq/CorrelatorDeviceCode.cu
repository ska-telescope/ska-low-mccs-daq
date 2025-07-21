//
// Created by Alessio Magro on 04/05/2018.
//

#include "DeviceCode.h"

// ====================== cuFFT callbacks ==============================

// For below callbacks:
//   offset is the number of elements from start of data
//   dataOut is global output array pointer

// Load callback
__device__ cufftComplex _expandInputPrecision(void *dataIn, size_t offset,
                                              void *callerInfo, void *sharedPtr)
{
    complex8_t value = ((complex8_t *) dataIn)[offset];
    return { (float) ((value.x) / 128.0),
             (float) ((value.y) / 128.0) };
}

// Store callback
__device__ void _quantizeOutput(void *dataOut, size_t offset, cufftComplex element,
                                void *callerInfo, void *sharedPtr)
{
    // Read in observation parameters
    CudaObsParams *p = (CudaObsParams *) callerInfo;

    // Calculate index in output buffer where to store value
    int fft_number = offset / p -> nof_channels;
    int channel = offset % p -> nof_channels;
    int pol = fft_number % p -> nof_pols;
    int antenna = fft_number / p -> nof_pols;
    int index = p->nof_pols * (channel * p->nof_antennas + antenna) + pol;

    // Quantise value
    float factor = p->nof_channels / (sqrtf(p->nof_channels) * 2);
    complex8_t val;
    val.x = (int8_t) (element.x * factor);
    val.y = (int8_t) (element.y * factor);

    // Store quantised value
    *(((complex8_t *) dataOut) + index) = val;
}

// Pointer to load and store callback functions
__device__ cufftCallbackLoadC d_loadCallbackPtr = _expandInputPrecision;
__device__ cufftCallbackStoreC d_storeCallbackPtr = _quantizeOutput;

// Generate FFT plans
void generateFFTPlan(cufftHandle *plan, cudaStream_t *stream, CudaObsParams *params)
{
    // Create FFT plan
    CuFFTCheckResult(cufftCreate(plan));

    // Create CUDA stream
    CudaSafeCall(cudaStreamCreate(stream));

    // Get observation information
    int nof_channels = params -> nof_channels;
    int nof_antennas = params ->nof_antennas;
    int nof_pols = params -> nof_pols;

    // Create plan
    int inembed = 1, onembed = 1; // These are ignored for rank 1 FFTs
    size_t ws = 0;

    CuFFTCheckResult(cufftMakePlanMany(*plan,
                                       1,              // rank
                                       &nof_channels,  // size of each dimension
                                       &inembed,       // inembed (storage dimensions of of input data in memory)
                                       (int) nof_antennas,   // istride (distance between two successive input elements in input array)
                                       1,              // idist (distance between the first element of two consecutive signals in a batch in input array)
                                       &onembed,       // onembef (storage dimensions of output data in memory)
                                       1,              // ostride (distance between two successive output elements in output array)
                                       nof_channels,   // odist (distance between the first element of two consecutive signals in a batch in output array
                                       CUFFT_C2C,      // transform type
                                       nof_antennas * nof_pols, // batch size of transform
                                       &ws));          // pointer to the sizes of the work areas

    // Set CUDA stream for plan
    CuFFTCheckResult(cufftSetStream(*plan, *stream));

    // Allocate observation params area on GPU and copy info
    CudaObsParams *d_cuda_obs_params;
    CudaSafeCall(cudaMalloc((void **)&d_cuda_obs_params, sizeof(CudaObsParams)));
    CudaSafeCall(cudaMemcpy(d_cuda_obs_params, params,
                            sizeof(CudaObsParams),
                            cudaMemcpyHostToDevice));

    // Copy load callback symbol to GPU
    cufftCallbackLoadR h_loadCallbackPtr;
    CudaSafeCall(cudaMemcpyFromSymbol(&h_loadCallbackPtr,
                                      d_loadCallbackPtr,
                                      sizeof(h_loadCallbackPtr)));

    // Copy store callback symbol to GPU
    cufftCallbackStoreC h_storeCallbackPtr;
    CudaSafeCall(cudaMemcpyFromSymbol(&h_storeCallbackPtr,
                                      d_storeCallbackPtr,
                                      sizeof(h_storeCallbackPtr)));

    // Assign load callback
    CuFFTCheckResult(cufftXtSetCallback(*plan, (void **) &h_loadCallbackPtr,
                                        CUFFT_CB_LD_COMPLEX, nullptr));

    // Assign store callback
    CuFFTCheckResult(cufftXtSetCallback(*plan, (void **) &h_storeCallbackPtr,
                                        CUFFT_CB_ST_COMPLEX,
                                        (void **) &d_cuda_obs_params));
}