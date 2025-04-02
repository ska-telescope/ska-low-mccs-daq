//
// Created by lessju on 20/03/2019.
//

#ifndef AAVS_DAQ_STANDALONECORRELATOR_H
#define AAVS_DAQ_STANDALONECORRELATOR_H

#include <cstdio>
#include <cstdint>
#include "xgpu.h"

// xGPU context
XGPUContext context;

extern "C" {

int initialise_correlator(uint32_t nof_antennas, uint32_t nof_samples) {
    // Get sizing information for xGPU library
    XGPUInfo xgpu_info;
    xgpuInfo(&xgpu_info);

#ifndef FIXED_POINT
    printf("xGPU needs to be configured to FIXED_POINT.\n");
#endif

    // Check whether xGPU was compiled properly for this configuration
    if (xgpu_info.npol != 2)
        printf("Error: xGPU pols (%d) != pols (%d)", xgpu_info.npol, 2);

    if (xgpu_info.nstation != nof_antennas)
        printf("Error: xGPU nstation (%d) != nof_antennas (%d)", xgpu_info.nstation, nof_antennas);

    if (xgpu_info.ntime != nof_samples)
        printf("Error: xGPU ntime(%d) != nof_samples (%d)", xgpu_info.ntime, nof_samples);

    if (xgpu_info.matLength != (int) (((nof_antennas * 0.5) + 1) * nof_antennas * 2 * 2))
        printf("Error: xGPU matLength (%lld) != %d", xgpu_info.matLength,
               (int) (((nof_antennas * 0.5) + 1) * nof_antennas * 2 * 2));

    // Allocate the GPU X-engine memory
    context.array_len = xgpu_info.vecLength;
    context.matrix_len = xgpu_info.matLength;
    context.array_h = nullptr;  // Let xGPU create this buffer (overridden for no channeliser mode)
    context.matrix_h = nullptr; // Let xGPU create this buffer
    
    // Initialise xGPU context
    if (xgpuInit(&context, 0))
        printf("xgpuInit returned error code\n");

}

float* correlate(int8_t *input_data) {

    // Update input buffer
    context.array_h = (ComplexInput *) input_data;

    // Call xGPU
    xgpuCudaXengine(&context, SYNCOP_DUMP);

    // Reorder output matrix
    xgpuReorderMatrix(context.matrix_h);

    // Clear device integrations
    xgpuClearDeviceIntegrationBuffer(&context);

    return (float *) context.matrix_h;
}

}
#endif //AAVS_DAQ_STANDALONECORRELATOR_H
