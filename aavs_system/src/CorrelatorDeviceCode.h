//
// Created by Alessio Magro on 04/05/2018.
//

#ifndef _DEVICECODE_H
#define _DEVICECODE_H

#include <cstdint>
#include <cstdio>
#include <cuda.h>
#include <cufft.h>
#include <cufftXt.h>

// ======================== CUDA HELPER FUNCTIONS ==========================

// Error checking function

#define CUDA_ERROR_CHECK
#define CudaSafeCall( err ) _cudaSafeCall( err, __FILE__, __LINE__ )
#define CudaCheckError()    _cudaCheckError( __FILE__, __LINE__ )
#define CuFFTCheckResult(result) _cufftCheckResult(result, __FILE__, __LINE__)

inline void _cudaSafeCall( cudaError err, const char *file, const int line )
{
#ifdef CUDA_ERROR_CHECK
    if ( cudaSuccess != err )
    {
        fprintf( stderr, "cudaSafeCall() failed at %s:%i : %s\n",
                 file, line, cudaGetErrorString( err ) );
        exit( -1 );
    }
#endif
}

inline void _cudaCheckError( const char *file, const int line )
{
#ifdef CUDA_ERROR_CHECK
    cudaError err = cudaGetLastError();
    if ( cudaSuccess != err )
    {
        fprintf( stderr, "cudaCheckError() failed at %s:%i : %s\n",
                 file, line, cudaGetErrorString( err ) );
        exit( -1 );
    }
#endif
}


inline void _cufftCheckResult( cufftResult result, const char *file, const int line )
{
#ifdef CUDA_ERROR_CHECK
    if ( result != CUFFT_SUCCESS )
    {
        fprintf( stderr, "CuFFTCheckResult() failed at %s:%i : Result Code %d\n",
                 file, line, result);
        exit( -1 );
    }
#endif
}

// -----------------------------------------------------------------------------



// Define structure for passing in observation parameters
typedef struct obs_params
{
    int nof_pols, nof_antennas, nof_channels;
} CudaObsParams;

// 8-bit data type for handling input
typedef struct _complex8_t
{
    int8_t x;
    int8_t y;
} complex8_t;


extern "C" void generateFFTPlan(cufftHandle *plan, cudaStream_t *stream, CudaObsParams *params);

#endif