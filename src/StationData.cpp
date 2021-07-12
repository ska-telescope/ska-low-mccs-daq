//
// Created by Alessio Magro on 14/05/2018.
//

#include <fcntl.h>
#include <sys/mman.h>
#include <cfloat>
#include "StationData.h"
#include "SPEAD.h"

// -------------------------------------------------------------------------------------------------------------
// STATION DATA CONSUMER
// -------------------------------------------------------------------------------------------------------------

// Initialise station data consumer
bool StationData::initialiseConsumer(json configuration)
{

    // Check that all required keys are present
    if (!(key_in_json(configuration, "nof_channels")) &&
        (key_in_json(configuration, "nof_samples")) &&
        (key_in_json(configuration, "max_packet_size"))) {
        LOG(FATAL, "Missing configuration item for StationData consumer. Requires "
                "nof_channels, nof_samples and max_packet_size");
        return false;
    }

    // Set local values
    this -> nof_channels = configuration["nof_channels"];
    this -> nof_samples  = configuration["nof_samples"];
    this -> nof_pols     = 2;
    this -> packet_size  = configuration["max_packet_size"];

    // Create ring buffer
    initialiseRingBuffer(packet_size, (size_t) nof_samples / 2);

    // Create double buffer
    double_buffer= new StationDoubleBuffer(nof_channels, nof_samples, nof_pols);

    // Create and persister
    persister = new StationPersister(double_buffer);
    persister->startThread();

    // All done
    return true;
}

// Cleanup function
void StationData::cleanUp()
{
    // Stop cross correlator thread
    persister->stop();

    // Destroy instances
    delete persister;
    delete double_buffer;
}

// Set callback
void StationData::setCallback(DataCallback callback)
{
    this -> persister -> setCallback(callback);
}

// Packet filter
bool StationData::packetFilter(unsigned char *udp_packet)
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

    // Check whether this is a Station Beam packet
    for (unsigned short i = 0; i < SPEAD_GET_NITEMS(hdr); i++)
        if (SPEAD_ITEM_ID(SPEAD_ITEM(udp_packet, i)) == 0x1011)
            return true;

    // Did not find item 0x1011, not a station beam packet
    return false;
}

// Get and process packet
bool StationData::processPacket()
{
    // Get next packet to process
    size_t packet_size = ring_buffer -> pull_timeout(&packet, 1);

    // Check if the request timed out
    if (packet_size == SIZE_MAX)
        return false;

    // This packet is a SPEAD packet, since otherwise it would not have
    // passed through the filter
    uint64_t hdr = SPEAD_HEADER(packet);

    uint64_t packet_counter   = 0;
    uint16_t logical_channel_id = 0;
    uint64_t sync_time = 0;
    uint64_t timestamp = 0;
    uint64_t payload_length = 0;
    uint64_t frequency = 0;
    uint16_t beam_id = 0;
    uint16_t frequency_id = 0;
    uint8_t substation_id = 0;
    uint8_t subarray_id = 0;
    uint16_t station_id = 0;
    uint16_t nof_contributing_antennas = 0;
    uint32_t payload_offset = 0;

    // Get the number of items and get a pointer to the packet payload
    auto nofitems = (unsigned short) SPEAD_GET_NITEMS(hdr);
    uint8_t *payload = packet + SPEAD_HEADERLEN + nofitems * SPEAD_ITEMLEN;

    for(unsigned i = 1; i <= nofitems; i++)
    {
        uint64_t item = SPEAD_ITEM(packet, i);
        switch (SPEAD_ITEM_ID(item))
        {
            case 0x0001:  // Heap counter
            {
                logical_channel_id = (uint16_t) ((SPEAD_ITEM_ADDR(item) >> 32) & 0xFFFF); // 16-bits
                packet_counter = (uint32_t) (SPEAD_ITEM_ADDR(item) & 0xFFFFFFFF); // 32-bits
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
            case 0x1011: // Frequency
            {
                frequency = SPEAD_ITEM_ADDR(item);
                break;
            }
            case 0x3000: // Antenna and Channel information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                beam_id = (uint16_t) ((val >> 16) & 0xFFFF);
                frequency_id = (uint16_t) (val & 0xFFFF);
                break;
            }
            case 0x3001: // Tile information
            {
                uint64_t val = SPEAD_ITEM_ADDR(item);
                substation_id = (uint8_t) ((val >> 40) & 0xFF);
                subarray_id = (uint8_t) ((val >> 32) & 0xFF);
                station_id = (uint16_t) ((val >> 16) & 0xFFFF);
                nof_contributing_antennas = (uint16_t) (val & 0xFFFF);
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
                LOG(WARN, "Unknown item %#010x (%d of %d) \n", SPEAD_ITEM_ID(item), i, nofitems);
        }
    }

    // Check whether timestamp counter has rolled over
    if (timestamp == 0 && logical_channel_id == 0) {
        timestamp_rollover += 1;
        timestamp += timestamp_rollover << 48;
    }
    else if (timestamp == 0)
        timestamp += timestamp_rollover << 48;
    else
        // Multiply packet_counter by rollover counts
        timestamp += timestamp_rollover << 48;

    // Calculate packet time
    double packet_time = sync_time + timestamp * 1.0e-9; // timestamp_scale;

    // Divide packet counter by 8 (reason unknown)
    // packet_counter = packet_counter >> 3;

    // Calculate number of samples in packet
    auto samples_in_packet = static_cast<uint32_t>((payload_length - payload_offset) / (sizeof(uint16_t) * nof_pols));

    // Check whether packet counter has rolled over
    if (packet_counter == 0 && logical_channel_id == 0) {
        rollover_counter += 1;
        packet_counter += rollover_counter << 32;
    }
    else if (packet_counter == 0)
        packet_counter += (rollover_counter + 1) << 32;
    else
        // Multiply packet_counter by rollover counts
        packet_counter += rollover_counter << 32;

    // We have processed the packet items, send data to packet counter
    double_buffer -> write_data(logical_channel_id,
                                samples_in_packet,
                                packet_counter,
                                reinterpret_cast<uint16_t *>(payload + payload_offset),
                                packet_time);

    // Ready from packet
    ring_buffer -> pull_ready();

    // All done, return
    return true;
}

// -------------------------------------------------------------------------------------------------------------
// STATION DOUBLE BUFFER
// -------------------------------------------------------------------------------------------------------------

// Default double buffer constructor
StationDoubleBuffer::StationDoubleBuffer(uint16_t nof_channels, uint32_t nof_samples, uint8_t nof_pols, uint8_t nbuffers) :
        nof_channels(nof_channels), nof_samples(nof_samples), nof_pols(nof_pols), nof_buffers(nbuffers)
{
    // Make sure that nof_buffers is a power of 2
    nbuffers = (uint8_t) pow(2, ceil(log2(nbuffers)));

    // Allocate the double buffer
    allocate_aligned((void **) &double_buffer, (size_t) CACHE_ALIGNMENT, nbuffers * sizeof(StationBuffer));

    // Initialise and allocate buffers in each struct instance
    for(unsigned i = 0; i < nbuffers; i++)
    {
        double_buffer[i].ref_time     = 0;
        double_buffer[i].ready        = false;
        double_buffer[i].index        = 0;
        double_buffer[i].nof_packets  = 0;
        double_buffer[i].nof_saturations  = 0;
        double_buffer[i].nof_channels = nof_channels;
        double_buffer[i].nof_samples  = nof_samples;
        double_buffer[i].mutex = new std::mutex;
        allocate_aligned((void **) &(double_buffer[i].integrators), CACHE_ALIGNMENT, nof_pols * nof_channels * sizeof(double));
        allocate_aligned((void **) &(double_buffer[i].read_samples), CACHE_ALIGNMENT, nof_channels * sizeof(uint32_t));
        memset(double_buffer[i].integrators, 0, nof_pols * nof_channels * sizeof(double));
        memset(double_buffer[i].read_samples, 0, nof_channels * sizeof(uint32_t));
    }
    
    // Initialise producer and consumer
    producer = 0;
    consumer = 0;

    // Set up timing variables
    tim.tv_sec  = 0;
    tim.tv_nsec = 1000;
}

// Class destructor
StationDoubleBuffer::~StationDoubleBuffer()
{
    for(unsigned i = 0; i < nof_buffers; i++)
    {
        delete double_buffer[i].mutex;
        free(double_buffer[i].integrators);
        free(double_buffer[i].read_samples);
    }
    free(double_buffer);
}

// Write data to buffer
void StationDoubleBuffer::write_data(uint16_t channel_id, uint32_t samples, uint64_t packet_counter,
                                     uint16_t *data_ptr, double timestamp)
{
    // Check whether the current consumer buffer is empty, and if so set index of the buffer
    if (this -> double_buffer[this->producer].index == 0)
        this -> double_buffer[this->producer].index = packet_counter;

    // Check if we are receiving a packet from a previous buffer, if so place in previous buffer
    else if (this -> double_buffer[this->producer].index > packet_counter)
    {
        // Select buffer to place data into
        int local_producer = (this->producer == 0) ? this->nof_buffers - 1 : (this->producer - 1);

        // Check if packet belongs in previous buffer
        if (this -> double_buffer[local_producer].index > packet_counter)
            // Packet belongs to an older buffer (or is invalid). Ignoring
            return;

        // Copy data into selected buffer
        this->process_data(local_producer, channel_id, samples, data_ptr,  timestamp);

        // Ready from packet
        return;
    }

    // Check if packet counter is within current buffer or if we have skipped buffer boundary
    else if (packet_counter - this->double_buffer[this->producer].index >= nof_samples / samples)
    {
        // Store current buffers's index
        uint64_t current_index = this -> double_buffer[this->producer].index;

        // Check if packet's counter is beyond next buffer as well, and if so ignore
        if (packet_counter > current_index + (nof_samples / samples) * 2)
            return;

        // We have skipped buffer borders, mark buffer before previous one as ready and switch to next one
        int local_producer = (this->producer < 2) ? (this -> producer - 2) + this->nof_buffers : (this -> producer - 2);
        if (this->double_buffer[local_producer].index != 0)
            this -> double_buffer[local_producer].ready = true;

        // Update producer pointer
        this -> producer = (this -> producer + 1) % this -> nof_buffers;

        // Wait for next buffer to become available
        unsigned int index = 0;
        while (index * tim.tv_nsec < 1e6)
        {
            if (this->double_buffer[this->producer].index != 0) {
                nanosleep(&tim, &tim2);
                index++;
            }
            else
                break;
        }

        if (index * tim.tv_nsec >= 1e6 )
            LOG(WARN, "Warning: Overwriting buffer [%d]!\n", this ->producer);

        // Start using new buffer. Note that current packet's packet counter could be invalid, so we
        // assign the buffer's index to be the next increment after the previous buffer
        this -> double_buffer[this -> producer].index = current_index + nof_samples / samples;
        memset(double_buffer[this->producer].read_samples, 0, nof_channels * sizeof(uint32_t));
    }

    // Copy data to buffer
    this->process_data(producer, channel_id, samples, data_ptr, timestamp);

    // Update buffer index if required
    if (this->double_buffer[producer].index > packet_counter)
        this->double_buffer[producer].index = packet_counter;
}

// Fast absolute implementation for singed 8-bit values
inline uint32_t StationDoubleBuffer::get_abs(char value)
{
    int const mask = value >> (sizeof(int) * 8 - 1);
    return static_cast<uint32_t>((value + mask) ^ mask);
}

inline void StationDoubleBuffer::process_data(int producer_index, uint16_t channel, uint32_t samples,
                                              uint16_t *data_ptr, double timestamp)
{
    // Process data
    auto *ptr = reinterpret_cast<complex8_t *>(data_ptr);
    double *buffer_x = this->double_buffer[producer_index].integrators;
    double *buffer_y = this->double_buffer[producer_index].integrators + nof_channels;

    for(unsigned i = 0; i < samples; i++) 
    {
        complex8_t x = *ptr++;
        complex8_t y = *ptr++;

        // Check if this samples is saturated, and if so exclude it from integration
        if (get_abs(x.real) >= 127 || get_abs(x.imag) >= 127 || get_abs(y.real) >= 127 || get_abs(y.imag) >= 127)
            this->double_buffer[producer_index].nof_saturations++;

        // Otherwise add to integrator and increase number of associated samples
        else {
            buffer_x[channel] += static_cast<double>(x.real * x.real + x.imag * x.imag);
            buffer_y[channel] += static_cast<double>(y.real * y.real + y.imag * y.imag);

            // Update number of samples in the current buffer
            this -> double_buffer[producer_index].read_samples[channel] += 1;
        }
    }

    // Update number of packets
    this->double_buffer[producer_index].nof_packets++;

    // Update timings
    if (this->double_buffer[producer_index].ref_time > timestamp || this->double_buffer[producer_index].ref_time == 0)
        this->double_buffer[producer_index].ref_time = timestamp;
}

// Read buffer
StationBuffer* StationDoubleBuffer::read_buffer()
{
    // Wait for buffer to become available
    if (!(this->double_buffer[this->consumer].ready)) {
        nanosleep(&tim, &tim2); // Wait using nanosleep
        return nullptr;
    }

    // Buffer is ready, finalise integration by diving with number of read samples
    // per channel for both X and Y pol
    for (unsigned i = 0; i < this->nof_channels; i++) {
        uint32_t nof_samples = this->double_buffer[this->consumer].read_samples[i];        
        this->double_buffer[this->consumer].integrators[i] /= nof_samples;
        this->double_buffer[this->consumer].integrators[i + this->nof_channels] /= nof_samples;
    }

    return &(this->double_buffer[this->consumer]);
}

// Ready from buffer, mark as processed
void StationDoubleBuffer::release_buffer()
{
    // Set buffer as processed
    this->double_buffer[this->consumer].mutex -> lock();
    this->double_buffer[this->consumer].index = 0;
    this->double_buffer[this->consumer].ready = false;
    this->double_buffer[this->consumer].ref_time = DBL_MAX;
    this->double_buffer[this->consumer].nof_packets=0;
    this->double_buffer[this->consumer].nof_saturations=0;
    memset(double_buffer[this->consumer].integrators, 0, nof_pols * nof_channels * sizeof(double));
    memset(double_buffer[this->consumer].read_samples, 0, nof_channels * sizeof(uint32_t));
    this->double_buffer[this->consumer].mutex -> unlock();

    // Update consumer pointer
    this->consumer = (this->consumer + 1) % nof_buffers;
}

// Clear double buffer
void StationDoubleBuffer::clear()
{
    // Initialise and allocate buffers in each struct instance
    for(unsigned i = 0; i < nof_buffers; i++)
    {
        double_buffer[i].ref_time = DBL_MAX;
        double_buffer[i].ready    = false;
        double_buffer[i].index  = 0;
        double_buffer[i].nof_samples = 0;
        double_buffer[i].nof_packets = 0;
        double_buffer[i].nof_saturations = 0;
        double_buffer[i].nof_channels = nof_channels;
        memset(double_buffer[this->consumer].integrators, 0, nof_pols * nof_channels * sizeof(double));
        memset(double_buffer[this->consumer].read_samples, 0, nof_channels * sizeof(uint32_t));
    }
}

// Main event loop for StationPersister
void StationPersister::threadEntry()
{
    // Infinite loop: Process buffers
    while (!this->stop_thread) {

        // Get new buffer
        StationBuffer *buffer;
        do {
            buffer = double_buffer->read_buffer();
            if (this->stop_thread)
                return;
        } while (buffer == nullptr);

        // Call callback if set
        if (callback != nullptr)
            callback(buffer->integrators, buffer->ref_time, 
                     buffer->nof_packets, buffer->nof_saturations);
        else
            LOG(INFO, "Received station beam");

        // Ready from buffer
        double_buffer->release_buffer();
    }
}
