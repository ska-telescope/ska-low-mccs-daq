//
// Created by Alessio Magro on 14/05/2018.
//

#ifndef AAVS_DAQ_CORRELATOR_H
#define AAVS_DAQ_CORRELATOR_H


#include <cstdlib>
#include <unistd.h>
#include <fcntl.h>
#include <cstring>
#include <cmath>
#include <string>

#include "DAQ.h"
#include "DoubleBuffer.h"

#ifdef WITH_CHANNELISER
    #include "DeviceCode.h"
    #include <driver_types.h>
#endif

#include "xgpu.h"

#define ELAPSED_MS(start,stop) \
  ((((int64_t)stop.tv_sec-start.tv_sec)*1000*1000*1000+(stop.tv_nsec-start.tv_nsec))/1e6)

struct CorrelatorMetadata
{
    uint channel_id;
    double time_taken;
    uint nof_samples;
    uint nof_packets;
};

// -----------------------------------------------------------------------------

// Class which implements the GPU cross-correlator
class CrossCorrelator: public RealTimeThread
{

public:
    // Class constructor
    CrossCorrelator(DoubleBuffer *double_buffer, uint32_t nof_fine_channels,
                    uint16_t nof_antennas, uint32_t nof_samples, uint8_t nof_pols);

    ~CrossCorrelator() override;

    // Set callback (provided by CorrelatorData)
    void setCallback(DataCallbackDynamic callback)
    {
        this -> callback = callback;
    }

protected:

    // Main thread event loop
    void threadEntry() override;

private:

    // xGPU context
    XGPUContext context;

    // Pointer to double buffer
    DoubleBuffer *double_buffer;

    // Callback
    DataCallbackDynamic callback = nullptr;

    // Output buffer
    Complex *output_buffer = nullptr;

    // Observation parameters
    uint32_t nof_channels;
    uint16_t nof_antennas;
    uint32_t nof_samples;
    uint8_t nof_pols;

#ifdef WITH_CHANNELISER
    // CUDA streams
    cudaStream_t stream_1, stream_2;

    // cuFFT plans
    cufftHandle fftplan_1, fftplan_2;

    // Temporary GPU array for FFTing
    uint16_t *d_input_buffer, *d_temp_buffer;

    // Cuda observation parameters for callbacks
    CudaObsParams cuda_obs_params;
#endif

    // Timing
    struct timespec tic, toc;
};


// -----------------------------------------------------------------------------

// Class which will hold the channelised data for correlation
class CorrelatorData: public DataConsumer
{
public:

    // Override setDataCallback
    void setCallback(DataCallbackDynamic callback) override;

    // Initialise consumer
    bool initialiseConsumer(json configuration) override;

protected:
    // Packet filtering function to be passed to network thread
    inline bool packetFilter(unsigned char* udp_packet) override;

    // Grab SPEAD packet from buffer and process
    bool processPacket() override;

    // Override cleanup method
    void cleanUp() override;

private:

    // Pointer to Double Buffer
    DoubleBuffer *double_buffer;

    // Pointer to CrossCorrelator;
    CrossCorrelator *cross_correlator;

    // Reference packet counter
    size_t reference_counter = 0;
    uint32_t rollover_counter = 0;

    // Data setup
    uint16_t nof_antennas = 0;        // Number of antennas per tile
    uint8_t  nof_pols = 0;            // Number of polarisations
    uint16_t nof_tiles = 0;           // Number of tiles
    uint16_t nof_channels = 0;        // Number of channels
    uint32_t nof_samples = 0;         // Number of time samples
};

// Expose class factory for birales
extern "C" DataConsumer *correlator() { return new CorrelatorData; }

#endif //AAVS_DAQ_CORRELATOR_H
