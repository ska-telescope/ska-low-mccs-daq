//
// Station beam correlator consumer. See StationCorrelatorData.h.
//

#include <algorithm>
#include <cstring>
#include <ctime>

#include "StationCorrelatorData.h"
#include "SPEAD.h"

#define ELAPSED_MS(start, stop) \
    ((((int64_t)stop.tv_sec - start.tv_sec) * 1000 * 1000 * 1000 + (stop.tv_nsec - start.tv_nsec)) / 1e6)

namespace
{
    // Unix time of TAI 2000, including extra leap seconds (as in StationData.cpp)
    constexpr uint64_t TAI_2000 = 946684768 - 5;

    // Duration of one station beam packet (2048 samples of 1.08 us)
    constexpr double PACKET_PERIOD = STATION_CORRELATOR_SAMPLES_PER_PACKET * 1.08e-6;

    // Ring buffer cells. This is about 0.38 s of a full-band station beam.
    constexpr size_t RING_BUFFER_CELLS = 65536;
} // namespace

// -------------------------------------------------------------------------------------------------------------
// STATION CORRELATOR CONSUMER
// -------------------------------------------------------------------------------------------------------------

// Initialise consumer
bool StationCorrelatorData::initialiseConsumer(json configuration)
{
    cu::init();

    // Check that all required keys are present
    for (const char *key : {"substation_ids", "start_channel", "nof_channels", "nof_samples", "max_packet_size"})
    {
        if (!key_in_json(configuration, key))
        {
            LOG(ERROR, "Missing configuration item %s for StationCorrelatorData consumer. Requires "
                       "substation_ids, start_channel, nof_channels, nof_samples and max_packet_size",
                key);
            return false;
        }
    }

    // Give each substation a TCC receiver in the configured order (as StationData
    // does for subarrays)
    const json &ids = configuration["substation_ids"];
    if (!ids.is_array() || ids.empty() || ids.size() > STATION_CORRELATOR_MAX_SUBSTATIONS)
    {
        LOG(ERROR, "substation_ids must list between 1 and %d substation IDs", STATION_CORRELATOR_MAX_SUBSTATIONS);
        return false;
    }

    std::fill(std::begin(substation_slot), std::end(substation_slot), -1);
    std::vector<uint8_t> substation_ids;
    for (auto &entry : ids)
    {
        int substation_id = entry;
        if (substation_id < 0 || substation_id > 255)
        {
            LOG(ERROR, "Substation ID %d in substation_ids is out of range", substation_id);
            return false;
        }
        if (substation_slot[substation_id] != -1)
        {
            LOG(ERROR, "Duplicate substation ID %d in substation_ids", substation_id);
            return false;
        }
        substation_slot[substation_id] = (int16_t)substation_ids.size();
        substation_ids.push_back((uint8_t)substation_id);
    }

    // Set local values
    this->nof_substations = (uint16_t)substation_ids.size();
    this->start_channel = configuration["start_channel"];
    this->nof_channels = configuration["nof_channels"];
    this->nof_samples = configuration["nof_samples"];
    this->packet_size = configuration["max_packet_size"];

    if (nof_channels == 0)
    {
        LOG(ERROR, "nof_channels must be at least 1");
        return false;
    }

    // An integration must be a whole number of packets
    if (nof_samples == 0 || nof_samples % STATION_CORRELATOR_SAMPLES_PER_PACKET != 0)
    {
        LOG(ERROR, "nof_samples (%u) must be a positive multiple of %u",
            nof_samples, STATION_CORRELATOR_SAMPLES_PER_PACKET);
        return false;
    }

    // Create the cross-correlator before the ring buffer. Its GPU allocations are the
    // likeliest to fail (for example out of GPU memory), and when they throw no ring
    // buffer exists yet to leak.
    cross_correlator = new StationCrossCorrelator(nof_substations, nof_channels, nof_samples);
    double_buffer = cross_correlator->double_buffer;

    // Metadata that is the same for each integration
    StationCorrelatorMetadata metadata{};
    metadata.start_channel = start_channel;
    metadata.nof_channels = nof_channels;
    metadata.nof_substations = nof_substations;
    std::copy(substation_ids.begin(), substation_ids.end(), metadata.substation_ids);
    cross_correlator->setMetadataTemplate(metadata);

    // Create ring buffer
    initialiseRingBuffer(packet_size, RING_BUFFER_CELLS);

    // Start cross-correlator
    cross_correlator->startThread();

    return true;
}

// Cleanup function
void StationCorrelatorData::cleanUp()
{
    if (cross_correlator == nullptr)
        return;

    // Stop cross correlator thread
    cross_correlator->stop();

    // Destroy instances
    delete cross_correlator;
    cross_correlator = nullptr;
    double_buffer = nullptr;
}

// Set callback
void StationCorrelatorData::setCallback(DataCallbackDynamic callback)
{
    if (cross_correlator != nullptr)
        this->cross_correlator->setCallback(callback);
}

// Packet filter (as StationData::packetFilter, SKA format only)
bool StationCorrelatorData::packetFilter(unsigned char *udp_packet)
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

    // Look for the scan ID item of the SKA station beam format. Item 0 is the
    // SPEAD header.
    for (unsigned short i = 1; i <= SPEAD_GET_NITEMS(hdr); i++)
        if (SPEAD_ITEM_ID(SPEAD_ITEM(udp_packet, i)) == 0x3010)
            return true;

    // Did not find item 0x3010, not a station beam packet
    return false;
}

// Get and process packet
bool StationCorrelatorData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer->pull_timeout(&packet, 1);

    // Check if the request timed out
    if (packet_size == SIZE_MAX)
    {
        // Request timed out, finish any pending writes
        double_buffer->finish_write();
        return false;
    }

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);
    auto nofitems = (unsigned short)SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nofitems * SPEAD_ITEMLEN;

    uint64_t packet_counter = 0;
    uint64_t payload_length = 0;
    uint64_t scan_id = 0;
    uint16_t frequency_id = 0;
    uint16_t station_id = 0;
    uint8_t substation_id = 0;
    uint32_t payload_offset = 0;

    // Loop over items to extract values (as StationData::processPacket)
    for (unsigned i = 1; i <= nofitems; i++)
    {
        uint64_t item = SPEAD_ITEM(packet, i);
        switch (SPEAD_ITEM_ID(item))
        {
        case 0x0001: // Heap counter, the packet count since TAI 2000
        {
            packet_counter = SPEAD_ITEM_ADDR(item) & 0xFFFFFFFFFFLL; // 40-bits
            break;
        }
        case 0x0004: // Payload length
        {
            payload_length = SPEAD_ITEM_ADDR(item);
            break;
        }
        case 0x3000: // Logical channel, beam and frequency information
        {
            frequency_id = (uint16_t)(SPEAD_ITEM_ADDR(item) & 0xFFFF);
            break;
        }
        case 0x3001: // Substation, subarray and station information
        {
            uint64_t val = SPEAD_ITEM_ADDR(item);
            substation_id = (uint8_t)((val >> 40) & 0xFF);
            station_id = (uint16_t)((val >> 16) & 0xFFFF);
            break;
        }
        case 0x3010: // Scan ID, the full 48-bit item value
        {
            scan_id = SPEAD_ITEM_ADDR(item);
            break;
        }
        case 0x3300: // Payload offset
        {
            payload_offset = (uint32_t)SPEAD_ITEM_ADDR(item);
            break;
        }
        default:
            break;
        }
    }

    // Find the TCC receiver and channel. Drop packets that are not in the
    // configuration, and packets with a wrong payload size.
    const int16_t slot = substation_slot[substation_id];
    const uint32_t channel = (uint32_t)frequency_id - start_channel;
    const uint64_t samples = (payload_length - payload_offset) /
                             (sizeof(uint16_t) * STATION_CORRELATOR_NOF_POLS);
    const size_t packet_end = SPEAD_HEADERLEN + nofitems * SPEAD_ITEMLEN + payload_length;

    if (slot < 0 || frequency_id < start_channel || channel >= nof_channels ||
        payload_length < payload_offset || samples != STATION_CORRELATOR_SAMPLES_PER_PACKET ||
        packet_end > packet_size)
    {
        ring_buffer->pull_ready();
        return true;
    }

    // Calculate packet time. It is expressed in UTC (as in StationData)
    double packet_time = TAI_2000 + packet_counter * PACKET_PERIOD;

    double_buffer->write_data((uint16_t)slot, (uint16_t)channel, (uint32_t)samples, packet_counter,
                              reinterpret_cast<uint16_t *>(payload + payload_offset),
                              packet_time, scan_id, station_id);

    // Ready from packet
    ring_buffer->pull_ready();

    return true;
}

// -------------------------------------------------------------------------------------------------------------
// STATION CORRELATOR DOUBLE BUFFER
// -------------------------------------------------------------------------------------------------------------

StationCorrelatorDoubleBuffer::StationCorrelatorDoubleBuffer(uint16_t nof_substations, uint16_t nof_channels,
                                               uint32_t nof_samples, uint8_t nbuffers)
    : buffers_(nbuffers),
      nof_substations(nof_substations),
      nof_channels(nof_channels),
      nof_samples(nof_samples),
      chunk_samples(station_correlator_chunk_samples(nof_samples)),
      nbuffers(nbuffers),
      buffer_bytes_((size_t)nof_channels * nof_samples * nof_substations *
                    STATION_CORRELATOR_NOF_POLS * sizeof(uint16_t))
{
    cu::init();
    pinned_.reserve(nbuffers);

    // Pinned host memory, as in TccDoubleBuffer, so the copy to the GPU is fast
    for (auto &buffer : buffers_)
    {
        auto mem = std::make_unique<cu::HostMemory>(buffer_bytes_, CU_MEMHOSTALLOC_WRITECOMBINED);
        buffer.data = static_cast<uint16_t *>((void *)*mem);
        memset(buffer.data, 0, buffer_bytes_);
        pinned_.push_back(std::move(mem)); // make sure the memory isn't freed when we leave scope.
    }
}

// Write one packet to the buffers. The window logic is from StationDoubleBuffer::write_data.
void StationCorrelatorDoubleBuffer::write_data(uint16_t substation, uint16_t channel, uint32_t samples,
                                        uint64_t packet_counter, uint16_t *data_ptr, double timestamp,
                                        uint64_t scan_id, uint16_t station_id)
{
    // One window is one integration
    const uint64_t window = nof_samples / samples;

    // Windows start at multiples of the window length, so integrations align to TAI
    const uint64_t window_start = packet_counter - packet_counter % window;

    // Open a buffer if none is open (at the start of the stream, or after finish_write)
    if (!current_open)
        claim(window_start);

    uint64_t current_index = current_start;

    // Put a late packet in the previous buffer if it belongs there
    if (packet_counter < current_index)
    {
        int previous = (producer == 0) ? nbuffers - 1 : producer - 1;
        uint64_t previous_index = buffers_[previous].index;

        // Drop the packet if the GPU thread has the previous buffer, or if the packet
        // is not in the previous window. After a jump in the stream, there can be a
        // gap between the two windows.
        if (!previous_open || packet_counter < previous_index ||
            packet_counter - previous_index >= window)
            return;

        copy_data(previous, substation, channel, (packet_counter - previous_index) * samples,
                  samples, data_ptr, timestamp, scan_id, station_id);
        return;
    }

    // A packet after the current window opens the next buffer. The previous buffer
    // becomes ready. The current buffer becomes the previous buffer and accepts
    // late packets.
    if (packet_counter - current_index >= window)
    {
        int previous = (producer == 0) ? nbuffers - 1 : producer - 1;
        if (previous_open)
            buffers_[previous].ready = true;
        previous_open = true;

        // Update producer pointer
        producer = (producer + 1) % nbuffers;

        // Start the window of this packet. After a gap in the stream, this can be
        // more than one window ahead.
        claim(window_start);
        current_index = window_start;
    }

    // Copy data to buffer
    copy_data(producer, substation, channel, (packet_counter - current_index) * samples,
              samples, data_ptr, timestamp, scan_id, station_id);
}

// Take the buffer at `producer` for a new window
void StationCorrelatorDoubleBuffer::claim(uint64_t start)
{
    // Wait for the buffer to become available (as StationDoubleBuffer::write_data)
    unsigned int index = 0;
    while (index * tim.tv_nsec < 1e6)
    {
        if (buffers_[producer].index != STATION_CORRELATOR_EMPTY)
        {
            nanosleep(&tim, &tim2);
            index++;
        }
        else
            break;
    }

    StationCorrelatorBuffer &buffer = buffers_[producer];
    if (buffer.index != STATION_CORRELATOR_EMPTY)
    {
        // The GPU thread still has it. Overwrite it, as StationDoubleBuffer does.
        LOG(WARN, "Overwriting station correlator buffer [%d]", producer);
        buffer.ref_time = 0;
        buffer.nof_packets = 0;
    }

    buffer.ready = false;
    buffer.index = start;
    current_start = start;
    current_open = true;
}

// Copy one packet into a buffer in TCC layout (as TccDoubleBuffer::copy_data, with a
// channel dimension). The packet is [T][P] for one substation and one channel.
inline void StationCorrelatorDoubleBuffer::copy_data(int index, uint16_t substation, uint16_t channel,
                                              uint64_t start_sample, uint32_t samples,
                                              uint16_t *data_ptr, double timestamp,
                                              uint64_t scan_id, uint16_t station_id)
{
    constexpr uint32_t TPB = STATION_CORRELATOR_TIMES_PER_BLOCK;
    constexpr uint32_t NP = STATION_CORRELATOR_NOF_POLS;
    StationCorrelatorBuffer &buffer = buffers_[index];

    // The buffer layout is [Q][C][M][R][P][T] with T = 16 and M = chunk_samples / 16.
    // Each uint16_t is one complex 8-bit sample. A packet starts at a multiple of
    // the packet length, and the chunk length is a whole number of packets, so the
    // packet is inside one chunk.
    const uint64_t m_stride = (uint64_t)nof_substations * NP * TPB;     // stride per m
    const uint64_t c_stride = (uint64_t)(chunk_samples / TPB) * m_stride; // stride per channel
    const uint64_t q_stride = (uint64_t)nof_channels * c_stride;        // stride per chunk
    const uint64_t chunk = start_sample / chunk_samples;
    uint16_t *base = buffer.data + chunk * q_stride + channel * c_stride +
                     (uint64_t)substation * NP * TPB;

    uint64_t m = (start_sample % chunk_samples) / TPB;
    const uint32_t blocks = samples / TPB;

    // Split each block of 16 samples into one stripe for each polarisation. The
    // pragma prevents full unrolling, which stops GCC vectorising the loop.
    const uint16_t *__restrict__ src = data_ptr;
    for (uint32_t b = 0; b < blocks; ++b, ++m, src += TPB * NP)
    {
        uint16_t *__restrict__ dst = base + m * m_stride;
#pragma GCC unroll 1
        for (uint32_t t = 0; t < TPB; ++t)
        {
            dst[t] = src[t * NP];           // pol 0
            dst[TPB + t] = src[t * NP + 1]; // pol 1
        }
    }

    buffer.nof_packets++;
    buffer.scan_id = scan_id;
    buffer.station_id = station_id;

    if (buffer.ref_time == 0 || buffer.ref_time > timestamp)
        buffer.ref_time = timestamp;
}

// Mark the open buffers as ready when the stream stops (as DoubleBuffer::finish_write)
void StationCorrelatorDoubleBuffer::finish_write()
{
    int previous = (producer == 0) ? nbuffers - 1 : producer - 1;
    if (previous_open)
        buffers_[previous].ready = true;
    previous_open = false;

    if (current_open)
    {
        buffers_[producer].ready = true;
        producer = (producer + 1) % nbuffers;
        current_open = false;
    }
}

// Read buffer
StationCorrelatorBuffer *StationCorrelatorDoubleBuffer::read_buffer()
{
    // Wait for buffer to become available
    if (!buffers_[consumer].ready)
    {
        nanosleep(&tim, &tim2);
        return nullptr;
    }

    return &buffers_[consumer];
}

// Ready from buffer, mark as processed
void StationCorrelatorDoubleBuffer::release_buffer()
{
    StationCorrelatorBuffer &buffer = buffers_[consumer];

    // Zero the samples, so packets that are missing from the next window correlate as zero
    memset(buffer.data, 0, buffer_bytes_);
    buffer.ref_time = 0;
    buffer.nof_packets = 0;
    buffer.scan_id = 0;
    buffer.station_id = 0;
    buffer.ready = false;

    // Give the buffer back to the producer last
    buffer.index = STATION_CORRELATOR_EMPTY;

    // Move consumer pointer
    consumer = (consumer + 1) % nbuffers;
}

// -------------------------------------------------------------------------------------------------------------
// STATION CROSS CORRELATOR (GPU THREAD)
// -------------------------------------------------------------------------------------------------------------

// Class constructor (as TensorCrossCorrelator, with nrChannels > 1). TCC is compiled
// for one chunk, and runs once for each chunk of an integration.
StationCrossCorrelator::StationCrossCorrelator(uint16_t nof_substations, uint16_t nof_channels,
                                           uint32_t nof_samples, uint8_t nbuffers)
    : nof_substations(nof_substations),
      nof_channels(nof_channels),
      chunk_samples(station_correlator_chunk_samples(nof_samples)),
      nof_chunks(nof_samples / chunk_samples),
      device_(0),           // choose GPU 0
      context_(0, device_), // primary context on device 0
      stream_(),
      samplesExt_(multi_array::extents[nof_channels][chunk_samples / STATION_CORRELATOR_TIMES_PER_BLOCK]
                                      [nof_substations][STATION_CORRELATOR_NOF_POLS][STATION_CORRELATOR_TIMES_PER_BLOCK]),
      visExt_(multi_array::extents[nof_channels][(nof_substations * (nof_substations + 1)) / 2]
                                  [STATION_CORRELATOR_NOF_POLS][STATION_CORRELATOR_NOF_POLS]),
      hostVis_(sizeof(VisT) * visExt_.size, 0),
      devSamples_(sizeof(SampleT) * samplesExt_.size * nof_chunks),
      devVis_(sizeof(VisT) * visExt_.size),
      visSum_(visExt_.size)
{
    context_.setCurrent();

    correlator_ = std::make_unique<tcc::Correlator>(
        device_, tcc::Format::i8, // TPMs produce int8 complex
        /*nrReceivers*/ nof_substations,
        /*nrChannels*/ nof_channels,
        /*nrSamplesPerChannel*/ chunk_samples,
        /*nrPolarizations*/ STATION_CORRELATOR_NOF_POLS);

    // Allocate the double buffer last. The destructor does not run when the
    // constructor throws, so a double buffer allocated before a throw would leak.
    double_buffer = new StationCorrelatorDoubleBuffer(nof_substations, nof_channels, nof_samples, nbuffers);
}

// Class destructor
StationCrossCorrelator::~StationCrossCorrelator()
{
    delete double_buffer;
}

// Main event loop (as TensorCrossCorrelator::threadEntry)
void StationCrossCorrelator::threadEntry()
{
    context_.setCurrent();
    cu::Event eH2D0, eH2D1;
    cu::Event eK0, eK1;
    cu::Event eD2H0, eD2H1;

    while (!this->stop_thread)
    {
        StationCorrelatorBuffer *buffer;
        do
        {
            buffer = double_buffer->read_buffer();
            if (this->stop_thread)
                return;
        } while (buffer == nullptr);

        clock_gettime(CLOCK_MONOTONIC, &tic);

        // Copy the buffer values now. The producer uses the buffer again after
        // release_buffer.
        const double timestamp = buffer->ref_time;
        const uint32_t nof_packets = buffer->nof_packets;
        const uint64_t scan_id = buffer->scan_id;
        const uint16_t station_id = buffer->station_id;
        const size_t sample_bytes = double_buffer->buffer_bytes();
        const size_t chunk_bytes = sample_bytes / nof_chunks;
        const size_t vis_bytes = sizeof(VisT) * visExt_.size;

        stream_.record(eH2D0);
        stream_.memcpyHtoDAsync(devSamples_, buffer->data, sample_bytes);
        stream_.record(eH2D1);

        // Correlate each chunk, and add its int32 visibilities in int64. One chunk
        // cannot overflow int32 (see STATION_CORRELATOR_MAX_SAMPLES_PER_LAUNCH), but
        // the whole integration can.
        std::fill(visSum_.begin(), visSum_.end(), VisSumT(0, 0));
        const VisT *vis = static_cast<const VisT *>(static_cast<void *>(hostVis_));
        float kern_ms = 0;
        float d2h_ms = 0;
        for (uint32_t chunk = 0; chunk < nof_chunks; ++chunk)
        {
            // A view of this chunk's samples in the device buffer
            cu::DeviceMemory chunk_samples_dev(devSamples_, chunk * chunk_bytes, chunk_bytes);

            stream_.record(eK0);
            correlator_->launchAsync(stream_, devVis_, chunk_samples_dev, false);
            stream_.record(eK1);

            stream_.record(eD2H0);
            stream_.memcpyDtoHAsync(hostVis_, devVis_, vis_bytes);
            stream_.record(eD2H1);

            stream_.synchronize();
            kern_ms += eK1.elapsedTime(eK0);
            d2h_ms += eD2H1.elapsedTime(eD2H0);

            for (size_t i = 0; i < visSum_.size(); ++i)
                visSum_[i] = VisSumT(visSum_[i].real() + vis[i].real(),
                                     visSum_[i].imag() + vis[i].imag());
        }

        // Read the copy time (ms) from the device timeline
        float h2d_ms = eH2D1.elapsedTime(eH2D0);

        // Release buffer back to producer
        double_buffer->release_buffer();

        // Callback
        clock_gettime(CLOCK_MONOTONIC, &toc);
        if (callback != nullptr)
        {
            StationCorrelatorMetadata metadata = metadata_template_;
            metadata.time_taken = ELAPSED_MS(tic, toc);
            metadata.h2d_time = h2d_ms;
            metadata.kern_time = kern_ms;
            metadata.d2h_time = d2h_ms;
            metadata.scan_id = scan_id;
            // Mean samples received for each substation and channel
            metadata.nof_samples = (uint32_t)((uint64_t)nof_packets * STATION_CORRELATOR_SAMPLES_PER_PACKET /
                                              ((uint64_t)nof_substations * nof_channels));
            metadata.nof_packets = nof_packets;
            metadata.station_id = station_id;
            callback(static_cast<void *>(visSum_.data()), timestamp, static_cast<void *>(&metadata));
        }

        LOG(INFO,
            "Station correlator | H2D=%.3f ms | kern=%.3f ms | D2H=%.3f ms "
            "(packets=%u, chunks=%u, bytes=%.2f MiB)",
            h2d_ms, kern_ms, d2h_ms,
            nof_packets, nof_chunks, sample_bytes / (1024.0 * 1024.0));
    }
}

// Class factory
DataConsumer *stationcorrelator() { return new StationCorrelatorData; }
