//
// Created by Alessio Magro on 14/05/2018.
//

#include "CorrelatorData.h"
#include "SPEAD.h"
#include "xgpu.h"

// Initialise correlator data consumer
bool CorrelatorData::initialiseConsumer(json configuration)
{
    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_antennas")) &&
         (key_in_json(configuration, "nof_channels")) &&
         (key_in_json(configuration, "nof_fine_channels")) &&
         (key_in_json(configuration, "nof_tiles")) &&
         (key_in_json(configuration, "nof_samples")) &&
         (key_in_json(configuration, "nof_pols")) &&
         (key_in_json(configuration, "max_packet_size"))) {
        LOG(FATAL, "Missing configuration item for CorrelatorData consumer. Requires "
                "nof_antennas, nof_samples, nof_tiles, nof_pols, nof_channels, "
                "nof_fine_channels and max_packet_size");
        return false;
    }

    // Set local values
    this -> nof_channels = configuration["nof_channels"];
    this -> nof_tiles    = configuration["nof_tiles"];
    this -> nof_samples  = configuration["nof_samples"];
    this -> nof_antennas = configuration["nof_antennas"];
    this -> nof_pols     = configuration["nof_pols"];
    this -> packet_size  = configuration["max_packet_size"];
    uint32_t nof_fine_channels = configuration["nof_fine_channels"];

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t) 32768 * this -> nof_tiles);

    // Create double buffer
    double_buffer= new DoubleBuffer(nof_antennas * nof_tiles, nof_samples, nof_pols);

    // Create cross-correlator and start
    cross_correlator = new CrossCorrelator(double_buffer, nof_fine_channels,
                                           nof_tiles * nof_antennas, nof_samples, nof_pols);

    // Start cross-correlator
    cross_correlator -> startThread();

    // All done
    return true;
}

// Cleanup function
void CorrelatorData::cleanUp()
{
    // Stop cross correlator thread
    cross_correlator->stop();

    // Destroy instances
    delete cross_correlator;
    delete double_buffer;
}

// Set callback
void CorrelatorData::setCallback(DataCallbackDynamic callback)
{
    this -> cross_correlator -> setCallback(callback);
}

// Packet filter
bool CorrelatorData::packetFilter(unsigned char *udp_packet)
{
    // Unpack SPEAD Header (or try to)
    uint64_t hdr = SPEAD_HEADER(udp_packet);

    // Check that this is in fact a SPEAD packet and that the correct
    // version is being used
    if ((SPEAD_GET_MAGIC(hdr) != SPEAD_MAGIC) ||
        (SPEAD_GET_VERSION(hdr) != SPEAD_VERSION) ||
        (SPEAD_GET_ITEMSIZE(hdr) != SPEAD_ITEM_PTR_WIDTH) ||
        (SPEAD_GET_ADDRSIZE(hdr) != SPEAD_HEAP_ADDR_WIDTH))
        return false;

    // Check whether the SPEAD packet contains burst channel data
    uint64_t mode = SPEAD_ITEM_ADDR(SPEAD_ITEM(udp_packet, 5));
    return (mode == 0x4 || mode == 0x5 || mode == 0x7);
}

// Get and process packet
bool CorrelatorData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer -> pull_timeout(&packet, 1);

    // Check if the request timed out
    if (packet_size == SIZE_MAX) {
        // Request timed out, finish any pending writes
        double_buffer->finish_write();

        // Reset rollover counters
        rollover_counter = 0;
        reference_counter = 0;
        return false;
    }

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);

    uint32_t packet_index   = 0;
    uint32_t packet_counter = 0;
    uint64_t payload_length = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint16_t start_channel_id = 0;
    uint16_t start_antenna_id = 0;
    uint16_t nof_included_channels = 0;
    uint16_t nof_included_antennas = 0;
    uint16_t tile_id = 0;
    uint16_t station_id = 0;
    uint8_t  pol_id     = 0;
    uint32_t payload_offset = 0;

    // Get the number of items and get a pointer to the packet payload
    auto nofitems = (unsigned short) SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nofitems * SPEAD_ITEMLEN;

    // Loop over items to extract values
    for(unsigned i = 1; i <= nofitems; i++)
    {
        uint64_t item = SPEAD_ITEM(packet, i);
        switch (SPEAD_ITEM_ID(item))
        {
            case 0x0001:  // Heap counter
            {
                packet_counter = (uint32_t) (SPEAD_ITEM_ADDR(item) & 0xFFFFFF);       // 24-bits
                packet_index   = (uint32_t) ((SPEAD_ITEM_ADDR(item) >> 24) & 0xFFFF); // 16-bits
                break;
            }
            case 0x0004: // Payload length
            {
                payload_length = SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x1027: // Sync time
            {
                sync_time = SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x1600: // Timestamp
            {
                timestamp = SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x2002: // Antenna and Channel information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                start_channel_id      = (uint16_t) ((val >> 24) & 0xFFFF);
                nof_included_channels = (uint16_t) ((val >> 16) & 0xFF);
                start_antenna_id      = (uint16_t) ((val >> 8) & 0xFF);
                nof_included_antennas = (uint16_t) (val & 0xFF);
                break;
            }
            case 0x2001: // Tile information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                station_id = (uint16_t) ((val >> 16) & 0xFFFF);
                tile_id    = (uint16_t) ((val >> 32) & 0xFF);
                pol_id     = (uint8_t)   (val & 0xFF);
                break;
            }
            case 0x3300: // Payload offset
            {
                payload_offset = (uint32_t) SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x2004:
                break;
            default:
                LOG(INFO, "Unknown item %#010x (%d of %d)", SPEAD_ITEM_ID(item), i, nofitems);
        }
    }

    // TEMPORARY: Timestamp_scale maybe will disappear, so it's hardcoded for now
    double packet_time = sync_time + timestamp * 1.08e-6;// timestamp_scale;

    // Calculate number of samples in packet
    uint32_t samples_in_packet;

    samples_in_packet = (uint32_t) ((payload_length - payload_offset) /
                                    (nof_included_antennas * nof_pols * nof_included_channels * sizeof(uint16_t)));
    // Check whether packet counter has rolled over
    if (packet_counter == 0 && pol_id == 0)
        rollover_counter += 1;

    // Multiply packet_counter by rollover counts
    packet_counter += rollover_counter << 24;

    // Update packet index
    if (reference_counter == 0)
        reference_counter = packet_counter;

    // Assigned correct packet index
    packet_index = static_cast<uint32_t>((packet_counter - reference_counter) % (this->nof_samples / samples_in_packet));

   if (this->nof_channels == 1)
        // Write packet data to double buffer
        double_buffer->write_data_single_channel(tile_id * nof_antennas + start_antenna_id,
                                                 nof_included_antennas, start_channel_id,
                                                 packet_index,
                                                 samples_in_packet,
                                                 (uint16_t * )(payload + payload_offset),
                                                 packet_time);
    
    else 
        // We have processed the packet items, send data to packet counter
        double_buffer->write_data(tile_id * nof_antennas + start_antenna_id,
                                  nof_included_antennas, start_channel_id,
                                  packet_index,
                                  samples_in_packet,
                                  (uint16_t * )(payload + payload_offset),
                                  packet_time);

    // Ready from packet
    ring_buffer -> pull_ready();

    // All done, return
    return true;
}

// ------------------------- CROSS CORRELATOR ----------------------------------

// Class constructor
CrossCorrelator::CrossCorrelator(DoubleBuffer *double_buffer, uint32_t nof_fine_channels, uint16_t nof_antennas,
                                 uint32_t nof_samples, uint8_t nof_pols):
        nof_antennas(nof_antennas), nof_samples(nof_samples), nof_pols(nof_pols), nof_channels(nof_fine_channels)
{
    // Get pointer to double buffer
    this -> double_buffer = double_buffer;

    // Get sizing information for xGPU library
    XGPUInfo xgpu_info;
    xgpuInfo(&xgpu_info);

#ifndef FIXED_POINT
    LOG(FATAL, "xGPU needs to be configured to FIXED_POINT.\n");
#endif

    // Check whether xGPU was compiled properly for this configuration
    if (xgpu_info.npol != nof_pols)
        LOG(FATAL, "Error: xGPU pols (%d) != pols (%d)", xgpu_info.npol, nof_pols);

    if (xgpu_info.nstation != nof_antennas)
        LOG(FATAL, "Error: xGPU nstation (%d) != nof_antennas (%d)", xgpu_info.nstation, nof_antennas);

    if (xgpu_info.nfrequency != nof_fine_channels)
        LOG(FATAL, "Error: xGPU nfrequency (%d) != nof_channels (%d)", xgpu_info.nfrequency, nof_fine_channels);

    if (xgpu_info.ntime != nof_samples)
        LOG(FATAL, "Error: xGPU ntime(%d) != nof_samples (%d)", xgpu_info.ntime, nof_samples);

    if (xgpu_info.matLength != (int) (((nof_antennas * 0.5) + 1) * nof_fine_channels * nof_antennas * nof_pols * nof_pols))
        LOG(FATAL, "Error: xGPU matLength (%lld) != %d", xgpu_info.matLength,
               (int) (((nof_antennas * 0.5) + 1) * nof_antennas * nof_fine_channels * nof_pols * nof_pols));

    // Allocate the GPU X-engine memory
    context.array_len = xgpu_info.vecLength;
    context.matrix_len = xgpu_info.matLength;
    context.array_h = nullptr;  // Let xGPU create this buffer (overridden for no channeliser mode)
    context.matrix_h = nullptr; // Let xGPU create this buffer

#ifdef WITH_CHANNELISER
    // Initialise xGPU context
    if (xgpuInit(&context, 0))
        LOG(FATAL, "xgpuInit returned error code");

    // Allocate CUDA memory to act as input and output for cuFFT. We only need two
    // times the total batch size, one for each stream
    unsigned int cufft_size = 2 * nof_channels * nof_antennas * nof_pols * sizeof(uint16_t);
    CudaSafeCall(cudaMalloc((void **) &d_input_buffer, cufft_size));
    CudaSafeCall(cudaMalloc((void **) &d_temp_buffer, cufft_size));

    // Populate observation parameters strcuture to be passed in to store callback
    cuda_obs_params.nof_channels = nof_channels;
    cuda_obs_params.nof_antennas = nof_antennas;
    cuda_obs_params.nof_pols = nof_pols;

    // Generate FF plans
    generateFFTPlan(&fftplan_1, &stream_1, &cuda_obs_params);
    generateFFTPlan(&fftplan_2, &stream_2, &cuda_obs_params);

    // Register double buffer buffers
    long host_input_size = nof_antennas * nof_pols * nof_samples * nof_channels * sizeof(uint16_t);
    for(unsigned i = 0; i < double_buffer -> get_number_of_buffers(); i++)
        cudaHostRegister(double_buffer->get_buffer_pointer(i) -> data, host_input_size, cudaHostRegisterDefault);
#else
    if (nof_channels != 1) {
        LOG(FATAL, "Channeliser mode not built for correlator, nof_channels must be 1");
    }
#endif
}

// Class destructor
CrossCorrelator::~CrossCorrelator()
{
#ifdef WITH_CHANNELISER
    CudaSafeCall(cudaFree(d_input_buffer));
    CudaSafeCall(cudaFree(d_temp_buffer));
    CudaSafeCall(cudaStreamDestroy(stream_1));
    CudaSafeCall(cudaStreamDestroy(stream_2));
    CudaSafeCall(cudaFree(d_temp_buffer));
    CuFFTCheckResult(cufftDestroy(fftplan_1));
    CuFFTCheckResult(cufftDestroy(fftplan_2));
#endif

    // Free gpu memory
    xgpuFree(&context);
}

// Main event loop
void CrossCorrelator::threadEntry()
{

#ifndef WITH_CHANNELISER
    // Initialise with empty buffer for now
    context.array_h = (ComplexInput *) (double_buffer -> get_buffer_pointer(0)) -> data;
    if (xgpuInit(&context, 0))
        LOG(FATAL, "xgpuInit returned error code");
#endif

    // Infinite loop: Process buffers
    while(!this->stop_thread)
    {
        // Get new buffer
        Buffer *buffer;
        do {
            buffer = double_buffer->read_buffer();
            if (this->stop_thread)
                return;
        } while(buffer == nullptr);

        // Start timing
        clock_gettime(CLOCK_MONOTONIC, &tic);

        // Get parameters
        double timestamp = buffer->ref_time;
        int channel = buffer->channel;
        unsigned int read_samples = buffer->read_samples;
        unsigned int nof_packets = buffer->nof_packets;

#ifdef WITH_CHANNELISER
        // Perform channelisation
        for(unsigned i = 0; i < nof_samples; i++)
        {
            cudaStream_t *stream = &stream_1;
            cufftHandle *plan = &fftplan_1;
            if (i % 2 == 1) {
                plan = &fftplan_2;
                stream = &stream_2;
            }

            // Update input and output pointers
            unsigned host_index = i * nof_antennas * nof_pols * nof_channels;
            unsigned cufft_index = (i % 2) * nof_antennas * nof_pols * nof_channels;

            auto *input = (cufftComplex *) (d_input_buffer + cufft_index);
            auto *output = (cufftComplex *) (d_temp_buffer + cufft_index);

            // Copy data from input into GPU
            CudaSafeCall(cudaMemcpyAsync(input,
                                         buffer -> data + host_index,
                                         nof_antennas * nof_pols * nof_channels * sizeof(uint16_t),
                                         cudaMemcpyHostToDevice,
                                         *stream));

            // Perform FFT
            CuFFTCheckResult(cufftExecC2C(*plan, input, output, CUFFT_FORWARD));

            // Copy output to CPU
            CudaSafeCall(cudaMemcpyAsync(context.array_h + host_index,
                                         output,
                                         nof_antennas * nof_pols * nof_channels * sizeof(uint16_t),
                                         cudaMemcpyDeviceToHost,
                                         *stream));
        }
#endif
        // Set buffer data as input to xGPU
        context.array_h = (ComplexInput *) (buffer->data);

        // Call xGPU
        xgpuCudaXengine(&context, SYNCOP_DUMP);

        // Reorder output matrix
        xgpuReorderMatrix(context.matrix_h);

        // All done with data, release buffer
        double_buffer -> release_buffer();
        
        // Call callback if set
        clock_gettime(CLOCK_MONOTONIC, &toc);
        if (callback != nullptr)
        {
            CorrelatorMetadata metadata = {
                .channel_id = static_cast<unsigned int>(channel),
                .time_taken = ELAPSED_MS(tic, toc),
                .nof_samples = read_samples,
                .nof_packets = nof_packets,
            };
            callback(context.matrix_h, timestamp, static_cast<void *>(&metadata));
        };

        // Clear device integrations
        xgpuClearDeviceIntegrationBuffer(&context);

        // Finished with current buffer
        LOG(INFO, "xGPU with callback took: %11.6f ms (%d samples, %d packets)",
            ELAPSED_MS(tic,toc), read_samples, nof_packets);
    }
}

