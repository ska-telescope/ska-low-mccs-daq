#include <iostream>
#include <unistd.h>
#include <fcntl.h>
#include <getopt.h>
#include <cstring>
#include <cstdlib>
#include <ctime>
#include <bits/stdc++.h>

#include "DAQ.h"

using namespace std;

// Telescope and observation parameters
float channel_bandwidth = (400e6 / 512.0) * (32 / 27.0);
float channel_bandwidth_no_oversampling = (400e6 / 512.0);
float sampling_time = 1.0 / channel_bandwidth;

auto dada_header_size = 4096;
string source = "UNKNOWN";
int nof_bits = 8;
int nof_pols = 2;

// Acquisition parameters
string base_directory = "/data/";
string interface = "eth2";
string ip = "10.0.10.40";
uint64_t nof_samples = 262144 * 4;
uint32_t start_channel = 0;
uint32_t nof_channels = 1;
uint32_t duration = 60;
double capture_start_time = -1;
uint64_t max_file_size_gb = 1;

bool simulate_write = false;
bool individual_channel_files = false;
bool include_dada_header = false;
bool test_acquisition = false;

// File descriptor
std::vector<int> files;

// Callback counters
uint32_t skip = 1;
uint32_t counter = 0;
uint32_t cutoff_counter = 0;

typedef struct raw_station_metadata {
    unsigned frequency;
    unsigned nof_packets;
    unsigned buffer_counter;
    unsigned start_sample_index;
} RawStationMetadata;

// Forward declaration of functions
static int generate_output_file(double timestamp, unsigned int frequency,
                                unsigned int first_channel, unsigned int channels_in_file);
static std::string generate_dada_header(double timestamp, unsigned int frequency, unsigned int channels_in_file);
void seek_to_location(off_t offset, int whence);
void allocate_space(off_t offset, size_t len);
void write_to_file(void* data, unsigned start_sample_index);

timespec t1, t2;

void exit_with_error(const char *message) {
    // Display error message and exit with error
    perror(message);

    // Check whether there are open files, and if so close them
    for(int fd: files)
        if (fd != -1)
            close(fd);

    exit(-1);
}


// Function to compute timing difference
float diff(timespec start, timespec end)
{
    timespec temp;
    if ((end.tv_nsec-start.tv_nsec)<0) {
        temp.tv_sec = end.tv_sec-start.tv_sec-1;
        temp.tv_nsec = 1000000000+end.tv_nsec-start.tv_nsec;
    } else {
        temp.tv_sec = end.tv_sec-start.tv_sec;
        temp.tv_nsec = end.tv_nsec-start.tv_nsec;
    }

    return temp.tv_sec + temp.tv_nsec * 1e-9;
}


// Raw station beam callback
void raw_station_beam_callback(void *data, double timestamp, void *metadata)
{
    // Extract metadata
    unsigned frequency = ((RawStationMetadata *) metadata)->frequency;
    unsigned nof_packets = ((RawStationMetadata *) metadata)->nof_packets;
    unsigned buffer_counter = ((RawStationMetadata *) metadata)->buffer_counter;
    unsigned start_sample_index = ((RawStationMetadata *) metadata)->start_sample_index;

    // start_sample_index is used when a specific start capture time is provided and acquisition starts mid-packet.
    // This will only be applicable to the first buffer in an acquisition, so all buffer skipping logic below does
    // not take a non-zero start_sample_index into consideration (first written buffer cannot be a skipped buffer).

    // Do not write the first skip buffers to disk
    if (counter < skip) {
        counter += 1;
	    return;
    }

    // Compute buffer size that will be written to disk
    unsigned long buffer_size = (nof_samples - start_sample_index) * nof_channels * nof_pols * sizeof(uint16_t);
    if (individual_channel_files)
        buffer_size =  (nof_samples - start_sample_index)* nof_pols * sizeof(uint16_t);

    // Update timestamp with sample offset
    timestamp += start_sample_index * sampling_time;

    // Check whether we need to generate new files
    // Note: Assumption that first buffer in the file is not an overwritten buffer
    if ((counter - skip) % cutoff_counter == 0)
    {
        // Close off any existing files
        for(unsigned i = 0; i < files.size(); i++)
            close(files[i]);

        // Clear array
        files.clear();

        // Create a file for each frequency channel
        if (individual_channel_files) {
            for (unsigned i = 0; i < nof_channels; i++)
                files.push_back(generate_output_file(timestamp, frequency, start_channel + i, 1));
        }
        // Create a single file containing spectra
        else
            files.push_back(generate_output_file(timestamp, frequency, start_channel, nof_channels));
    }

    // Determine where buffer should be written based on the buffer counter
    clock_gettime(CLOCK_REALTIME_COARSE, &t1);

    // If simulating file write, do nothing
    if (simulate_write)
        ;

    // Received expected buffer
    else if (counter == buffer_counter)
        write_to_file(data, start_sample_index);

    // Buffer is further ahead than the current offset
    else if (buffer_counter > counter) {

        // Buffer should go in the next file. Not implemented
        if (buffer_counter % cutoff_counter < (counter - skip) % cutoff_counter)
            printf("WARNING: Cannot write buffer to future file! Skipping!\n");

        else {
            // Get current position in file
            off_t current_offset = lseek(files[0], 0, SEEK_CUR);

            // Allocate empty space in the file up to the beginning of the next buffer
            allocate_space(current_offset + (buffer_counter - counter) * buffer_size, buffer_size);

            // Seek to newly allocated space
            seek_to_location((buffer_counter - counter) * buffer_size, SEEK_CUR);

            // Write buffer
            write_to_file(data, start_sample_index);

            // Seek back to previous position + buffer length for next buffer
            seek_to_location(current_offset + buffer_size, SEEK_SET);
        }
    }

    // Buffer belongs in the previous file. Not implemented
    else if (buffer_counter % cutoff_counter > (counter - skip) % cutoff_counter)
        printf("WARNING: Cannot write buffer to future file! Skipping\n");

    // Buffer belongs in the current file prior to current buffer
    else {
        // Get current position in file
        off_t current_offset = lseek(files[0], 0, SEEK_CUR);

        // Go to required position in the past
        seek_to_location(current_offset - (counter - buffer_counter) * buffer_size, SEEK_SET);

        // Write data
        write_to_file(data, start_sample_index);

        // Seek back to previous offset + 1 extra buffer size
        seek_to_location(current_offset + buffer_size, SEEK_SET);
    }

    clock_gettime(CLOCK_REALTIME_COARSE, &t2);

    // Display user friendly message
    auto now = std::chrono::system_clock::now();
    auto datetime = std::chrono::system_clock::to_time_t(now);
    auto date_text = strtok(ctime(&datetime), "\n");
    cout << date_text <<  ": Written buffer " << buffer_counter << " with " << nof_packets <<
         " packets in " << (unsigned) (diff(t1, t2) * 1000) << "ms" << endl;

    // Increment buffer counter
    counter++;
}

void allocate_space(off_t offset, size_t len) {
    // Wrapper for fallocate which works on multiple files
    for(int fd: files)
        if (fallocate(fd, FALLOC_FL_ZERO_RANGE, offset, len) < 0) {
            perror("Failed to fallocate empty gap in file");
            close(fd);
            exit(-1);
        }
}

void seek_to_location(off_t offset, int whence) {
    // Wrapper to lseek which works for multiple files
    for(int fd: files)
        if (lseek(fd, offset, whence) < 0)
            exit_with_error("WARNING: Cannot seek file after gap allocation. Exiting\n");
}

void write_to_file(void* data, unsigned start_sample_index) {
    // Write the provided data to file

    auto samples_to_write = nof_samples - start_sample_index;

    // If separating channel, split buffer and write each channel into its respective file
    if (individual_channel_files) {
        for (unsigned i = 0; i < nof_channels; i++) {
            auto src = (uint16_t *) data + (i * nof_samples + start_sample_index) * nof_pols;
            if (write(files[i], src, samples_to_write * nof_pols * sizeof(uint16_t)) < 0)
                exit_with_error("Failed to write buffer to disk! Exiting!");
        }
    }
    else {
        // Write entire buffer to file
	    uint16_t *src = ((uint16_t *) data) + start_sample_index * nof_channels * nof_pols * sizeof(uint16_t);
        if (write(files[0], src, samples_to_write * nof_channels * nof_pols * sizeof(uint16_t)) < 0)
            exit_with_error(("Failed to write buffer to disk! Exiting!"));
    }
}

// Generate output files
static int generate_output_file(double timestamp, unsigned int frequency,
                                unsigned int first_channel, unsigned int channels_in_file) {

    // File descriptor placeholder
    int fd;

    // Create output file
    std::string suffix = include_dada_header ? ".dada" : ".dat";
    std::string path = base_directory + "channel_" + std::to_string(first_channel)
                       + "_" + std::to_string(channels_in_file)
                       + "_" + std::to_string(timestamp) + suffix;

    if ((fd = open(path.c_str(), O_WRONLY | O_CREAT | O_SYNC | O_TRUNC, (mode_t) 0600)) < 0) {
        perror("Failed to create output data file, check directory");
        exit(-1);
    }

    // Tell the kernel how the file is going to be accessed (sequentially)
    posix_fadvise(fd, 0, 0, POSIX_FADV_SEQUENTIAL);
    posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED);
    printf("Created file %s\n", path.c_str());

    // If required, generate DADA file and add to file
    if (include_dada_header) {
        // Define full header placeholder
        char *full_header;

        // Allocate full header. Note: using alignment of page size for Direct IO
        allocate_aligned((void **) &full_header, (size_t) PAGE_ALIGNMENT, dada_header_size);

        // Copy generated header
        auto header = generate_dada_header(timestamp,
                                                 frequency + channel_bandwidth_no_oversampling * first_channel,
                                                 channels_in_file);
        strcpy(full_header, header.c_str());

        // Fill in empty space with nulls to match required dada header size
        auto generated_header_size = header.size();
        for (unsigned i = generated_header_size; i < dada_header_size; i++)
            full_header[i] = '\0';

        if (write(fd, full_header, dada_header_size) < 0)
        {
            perror("Failed to write DADA header to disk");
            close(fd);
            exit(-1);
        }

        free(full_header);
    }

    return fd;
}

static std::string generate_dada_header(double timestamp, unsigned int frequency, unsigned int channels_in_file) {
    // Convert unix time to UTC and then to a formatted string
    const char* fmt = "%Y-%m-%d-%H:%M:%S";
    char time_string[200];
    auto t = static_cast<time_t>(timestamp);
    auto utc_time = gmtime(&t);
    strftime(time_string, sizeof(time_string), fmt, utc_time);

    // Generate DADA header
    std::stringstream header;

    // Required entries
    header << "HDR_VERSION 1.0" << endl;
    header << "HDR_SIZE " << dada_header_size << endl;
    header << "BW " << fixed << setprecision(4) << channel_bandwidth_no_oversampling * channels_in_file * 1e-6 << endl;
    header << "FREQ " << fixed << setprecision(6) << frequency * 1e-6<< endl;
    header << "TELESCOPE " << "LFAASP" << endl;
    header << "RECEIVER " << "LFAASP" << endl;
    header << "INSTRUMENT " << "LFAASP" << endl;
    header << "SOURCE " << source << endl;
    header << "MODE PSR" << endl;
    header << "NBIT " << nof_bits << endl;
    header << "NPOL " << nof_pols << endl;
    header << "NCHAN " << channels_in_file << endl;
    header << "NDIM " << 2 << endl;
    header << "OBS_OFFSET 0" << endl;
    header << "TSAMP " << fixed << setprecision(4) << (1.0 / channel_bandwidth) * 1e6 << endl;
    header << "UTC_START " << time_string << endl;

    // Additional entries to match post-processing requirements
    header << "POPULATED 1" << endl;
    header << "OBS_ID 0" << endl;
    header << "SUBOBS_ID 0" << endl;
    header << "COMMAND CAPTURE" << endl;

    header << "NTIMESAMPLES 1" << endl;
    header << "NINPUTS " << fixed << channels_in_file * nof_pols << endl;
    header << "NINPUTS_XGPU " << fixed << channels_in_file * nof_pols << endl;
    header << "METADATA_BEAMS 2" << endl;
    header << "APPLY_PATH_WEIGHTS 1" << endl;
    header << "APPLY_PATH_DELAYS 2" << endl;
    header << "INT_TIME_MSEC 0" << endl;
    header << "FSCRUNCH_FACTOR 1" << endl;
    header << "TRANSFER_SIZE 81920000" << endl;
    header << "PROJ_ID LFAASP" << endl;
    header << "EXPOSURE_SECS 8" << endl;
    header << "COARSE_CHANNEL " << channels_in_file << endl;
    header << "CORR_COARSE_CHANNEL 2" << endl;
    header << "SECS_PER_SUBOBS 8" << endl;
    header << "UNIXTIME " << (int) timestamp << endl;
    header << "UNIXTIME_MSEC " << fixed << setprecision(6) << (timestamp - (int) (timestamp)) * 1e3  << endl;
    header << "FINE_CHAN_WIDTH_HZ " << fixed << setprecision(6) << channel_bandwidth / 1  << endl;
    header << "NFINE_CHAN " << 1 << endl;
    header << "BANDWIDTH_HZ " << fixed << setprecision(6) << channel_bandwidth_no_oversampling * channels_in_file << endl;
    header << "SAMPLE_RATE " << fixed << setprecision(6) << channel_bandwidth << endl;
    header << "MC_IP 0" << endl;
    header << "MC_SRC_IP 0.0.0.0" << endl;
    header << "FILE_SIZE 0" << endl;
    header << "FILE_NUMBER 0" << endl;

    return header.str();
}

static void print_usage(char *name)
{
    std::cerr << "Usage: " << name << " <option(s)>\n"
              << "Options:\n"
              << "\t-d/--directory DIRECTORY \tBase directory where to store data\n"
              << "\t-t/--duration DURATION \t\tDuration to acquire in seconds\n"
              << "\t-s/--nof_samples NOF_SAMPLES\tNumber of samples\n"
              << "\t-c/--start_channel CHANNEL\tLogical channel ID to store\n"
              << "\t-n/--nof_channels NOF_CHANNELS \tNumber of channels to store from logical channel ID\n"
              << "\t-i/--interface INTERFACE\tNetwork interface to use\n"
              << "\t-p/--ip IP\t\t\tInterface IP\n"
              << "\t-m/--max_file_size\t\tMAX_FILE_SIZE in GB\n"
              << "\t-S/--source SOURCE\t\tObserved source\n"
              << "\t-D/--dada\t\t\tGenerate binary file with DADA header\n"
	          << "\t-I/--individual\t\t\tGenerate separate channels files\n"
	          << "\t-W/--simulate\t\t\tSimulate writing to disk\n"
              << "\t-C/--capture_time\t\tSet a start capture time (UTC). Format should be YYYY/MM/DD_hh:mm:ss\n"
              << "\t-T/--test_acquisition\t\tTest acquisition of station beam with fake data"
              << std::endl;
}

// Parse command line arguments
static void parse_arguments(int argc, char *argv[])
{
    // Define options
    const char* const short_opts = "d:t:s:i:p:c:m:n:C:S:DIWT";
    const option long_opts[] = {
            {"directory", required_argument, nullptr, 'd'},
            {"max_file_size", required_argument, nullptr, 'm'},
            {"duration", required_argument, nullptr, 't'},
            {"nof_samples", required_argument, nullptr, 's'},
            {"start_channel", required_argument, nullptr, 'c'},
            {"nof_channels", required_argument, nullptr, 'n'},
            {"interface", required_argument, nullptr, 'i'},
            {"ip", required_argument, nullptr, 'p'},
            {"source", required_argument, nullptr, 'S'},
            {"dada", no_argument, nullptr, 'D'},
	        {"simulate", no_argument, nullptr, 'W'},
            {"individual", no_argument, nullptr, 'I'},
            {"test_acquisition", no_argument, nullptr, 'T'},
            {"capture_time", required_argument, nullptr, 'C'},
            {nullptr, no_argument, nullptr, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, short_opts, long_opts, nullptr)) != -1) {
        switch (opt) {
            case 'd': {
                    base_directory = string(optarg);
                    // Check that path end with path separator
                    auto dir_len = base_directory.length();
                    if (strncmp(base_directory.c_str() + dir_len - 1, "/", 1) != 0)
                        base_directory += '/';
                }
                break;
            case 'm':
                max_file_size_gb = atoi(optarg);
                break;
            case 't':
                duration = (uint32_t) atoi(optarg);
                break;
            case 's':
                nof_samples = (uint32_t) atoi(optarg);
                break;
            case 'c':
                start_channel = (uint32_t) atoi(optarg);
                break;
            case 'n':
                nof_channels = (uint32_t) atoi(optarg);
                break;
            case 'i':
                interface = string(optarg);
                break;
            case 'p':
                ip = string(optarg);
                break;
            case 'S':
                source = string(optarg);
                break;
            case 'D':
                include_dada_header = true;
                break;
	        case 'W':
		        simulate_write = true;
		        break;
            case 'I':
                individual_channel_files = true;
                break;
            case 'T':
                test_acquisition = true;
                break;
            case 'C': {
                // Parse capture time
                std::string utc_date = string(optarg);

                // Convert UTC datetime string to Unix timestamp
                std::tm tm_utc = {};
                std::stringstream ss(utc_date);
                ss >> std::get_time(&tm_utc, "%Y/%m/%d_%H:%M");
                capture_start_time = static_cast<double>(timegm(&tm_utc));

                // Set number of skips to 0
                skip = 0;

                break;
            }
            default: /* '?' */
                print_usage(argv[0]);
                exit(EXIT_FAILURE);
        }
    }

    // Display acquisition information
    printf("Running acquire_station_beam with %ld samples starting from logical channel %d and saving %d channels.\n",
		    nof_samples, start_channel, nof_channels);

    if (capture_start_time > 0) {
        char datetime_str[20];
        auto unix_time = (std::time_t) capture_start_time;
        std::tm *tm_utc = std::gmtime(&unix_time);
        std::strftime(datetime_str, 20, "%Y/%m/%d_%H:%M", tm_utc);
        std::cout << "Capture will start at " << datetime_str << " UTC (epoch time: " << (int) capture_start_time << ") in "
		  << (int) (capture_start_time - std::time(nullptr)) << "s"  << std::endl;
    }

    if (simulate_write)
	    printf("Simulating disk write, nothing will be physically written to disk\n");
    else
	    printf("Saving in directory %s with maximum file size of %ld GB\n", base_directory.c_str(), max_file_size_gb);
        printf("Observing source %s for %d seconds\n", source.c_str(), duration);
}

// -----------------------------------------------------------------------------------------------------------
// -------------------------------------------------- TESTS --------------------------------------------------
// -----------------------------------------------------------------------------------------------------------

void test_call_station_beam_callback(uint16_t *buffer, unsigned test_counter) {
    RawStationMetadata metadata = {0,0,test_counter};

    if (individual_channel_files) {
        for (unsigned i = 0; i < nof_channels; i++)
            for (unsigned j = 0; j < nof_samples; j++) {
                buffer[(i * nof_samples + j) * 2] = ((test_counter + i) << 8) | (test_counter + i);
                buffer[(i * nof_samples + j) * 2 + 1] = ((test_counter + i) << 8) | (test_counter + i);
            }
    }
    else
        for (unsigned i = 0; i < nof_samples; i++)
            for (unsigned j = 0; j < nof_channels; j++) {
                buffer[(i * nof_channels + j) * 2] = ((test_counter + j) << 8) | (test_counter + j);
                buffer[(i * nof_channels + j) * 2 + 1] = ((test_counter + j) << 8) | (test_counter + j);
            }

    raw_station_beam_callback(buffer, 0, &metadata);
}

void test_acquire_station_beam() {
    printf("Testing shit out\n");

    // Generate buffer for passing to callback
    uint16_t *buffer;
    allocate_aligned((void **) &buffer, PAGE_ALIGNMENT, nof_samples * nof_channels * nof_pols * sizeof(uint16_t));

    test_call_station_beam_callback(buffer, 0);
    test_call_station_beam_callback(buffer, 1);
    test_call_station_beam_callback(buffer, 2);
    test_call_station_beam_callback(buffer, 3);
    test_call_station_beam_callback(buffer, 4);
    test_call_station_beam_callback(buffer, 5);
    test_call_station_beam_callback(buffer, 6);
    test_call_station_beam_callback(buffer, 8);
    test_call_station_beam_callback(buffer, 7);
    test_call_station_beam_callback(buffer, 20);
}

// -----------------------------------------------------------------------------------------------------------
// -----------------------------------------------------------------------------------------------------------
// -----------------------------------------------------------------------------------------------------------

int main(int argc, char *argv[])
{
    // Process command-line argument
    parse_arguments(argc, argv);

    // Split files into max_file_size_gb x 1G. If DADA header is being generated, set do not split file (set
    // cutoff counter to "infinity"
    if (include_dada_header)
        cutoff_counter = INT_MAX;
    else if (individual_channel_files)
        cutoff_counter = (max_file_size_gb * 1024 * 1024 * 1024) / (nof_samples * nof_pols * sizeof(uint16_t));
    else
        cutoff_counter = (max_file_size_gb * 1024 * 1024 * 1024) / (nof_samples * nof_channels * nof_pols * sizeof(uint16_t));

    // If received only 1 channel, then individual_channel_files can be disabled
    if (nof_channels == 1)
        individual_channel_files = false;

    // If in test mode, just call test, otherwise communicate with DAQ
    if (test_acquisition) {
        test_acquire_station_beam();
        exit(0);
    }

    // Configure receiver
    startReceiver(interface.c_str(), ip.c_str(), 9000, 32, 64);
    addReceiverPort(4660);

    // Set station raw consumer parameters
    json j = {
            {"start_channel", start_channel},
            {"nof_channels", nof_channels},
            {"nof_samples", nof_samples},
            {"transpose_samples", (individual_channel_files) ? 0 : 1},
            {"max_packet_size", 9000},
            {"capture_start_time", capture_start_time}
    };

    // Check whether a LIBAAVSDAQ environment variable is defined
    string libaavsdaq_location = "/opt/aavs/lib/libaavsdaq.so";
    if (std::getenv("AAVS_DAQ_LIBRARY") != nullptr)
        libaavsdaq_location = std::getenv("AAVS_DAQ_LIBRARY");

    // Workaround to avoid shared object not found, specify default location
    std::cout << "Using AAVS DAQ library " << libaavsdaq_location << std::endl;
    auto res = loadConsumer(libaavsdaq_location.c_str(), "stationdataraw");
    if (res != SUCCESS) {
        LOG(ERROR, "Failed to load station data consumser");
        return 0;
    }

    if (initialiseConsumer("stationdataraw", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise station data consumser");
        return 0;
    }

    if (startConsumerDynamic("stationdataraw", raw_station_beam_callback) != SUCCESS) {
        LOG(ERROR, "Failed to start station data consumser");
        return 0;
    }

    auto time_diff = capture_start_time - std::time(0);
    if (time_diff > 0)
        duration += time_diff;
    sleep(duration);

    if (stopConsumer("stationdataraw") != SUCCESS) {
        LOG(ERROR, "Failed to stop station data consumser");
        return 0;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return 0;
    }
}
