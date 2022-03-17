#include <iostream>
#include <unistd.h>
#include <fcntl.h>
#include <getopt.h>
#include <cstring>
#include <cstdlib>
#include <time.h>
#include <bits/stdc++.h>

#include "DAQ.h"

using namespace std;

// Telescope and observation parameters
float channel_bandwidth = (400e6 / 512.0) * (32 / 27.0);
string source = "UNKNOWN";
string telescope = "LFAASP";
int nbits = 8;
int npol = 2;
int ndim = 2;

int n_fine_channels = 1;

// Acquisition parameters
string base_directory = "/data/";
string interface = "eth2";
string ip = "10.0.10.40";
uint64_t nof_samples = 262144;
uint32_t start_channel = 0;
uint32_t nof_channels = 1;
uint32_t duration = 60;
uint64_t max_file_size_gb = 1;

bool individual_channel_files = false;
bool include_dada_header = false;
auto dada_header_size = 4096;

// File descriptor
std::vector<int> files;

// Callback counters
uint32_t skip = 1;
uint32_t counter = 0;
uint32_t cutoff_counter = 0;

// Forward declaration of functions
static int generate_output_file(double timestamp, unsigned int frequency,
                                unsigned int first_channel, unsigned int channels_in_file);
static std::string generate_dada_header(double timestamp, unsigned int frequency, unsigned int channels_in_file);

// Raw station beam callback
void raw_station_beam_callback(void *data, double timestamp, unsigned int frequency, unsigned int nof_samples)
{
    if (counter < skip) {
        counter += 1;
	    return;
    }

    printf("Received station beam with %d samples\n", nof_samples);

    // Check whether we need to generate new files
    if ((counter - skip) % cutoff_counter == 0)
    {
        // Close off any existing files
        for(unsigned i = 0; i < files.size(); i++)
            close(files[i]);

        // Clear array
        files.clear();

        if (individual_channel_files)
            for(unsigned i = 0; i < nof_channels; i++)
                files.push_back(generate_output_file(timestamp, frequency, start_channel + i, 1));
        else
            files.push_back(generate_output_file(timestamp, frequency, start_channel, nof_channels));
    }

    // Write data to file
    if (individual_channel_files)

        // Write each channel to its own file
        for(unsigned i = 0; i < nof_channels; i++) {

            auto src = (uint16_t *) data + i * nof_samples * npol;
            if (write(files[i], src, nof_samples * npol * sizeof(uint16_t)) < 0)
            {
                perror("Failed to write buffer to disk");

                // Close all files
                for(unsigned j = 0; j < files.size(); j++)
                    close(files[j]);

                exit(-1);
            }
        }

    else
        if (write(files[0], data, nof_samples * nof_channels * npol * sizeof(uint16_t)) < 0)
        {
            perror("Failed to write buffer to disk");
            fsync(files[0]);
            close(files[0]);
            exit(-1);
        }

    counter += 1;
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
    printf("Created file %s\n", path.c_str());

    // If required, generate DADA file and add to file
    if (include_dada_header) {
        // Define full header placeholder
        char full_header[dada_header_size];

        // Copy generated header
        auto generated_header = generate_dada_header(timestamp,
                                                           frequency + channel_bandwidth * first_channel,
                                                           channels_in_file);
        strcpy(full_header, generated_header.c_str());

        // Fill in empty space with nulls to match required dada header size
        auto generated_header_size = generated_header.size();
        for (unsigned i = generated_header_size; i < dada_header_size; i++)
            full_header[i] = '\0';

        if (write(fd, full_header, dada_header_size) < 0)
        {
            perror("Failed to generate DADA header to disk");
            close(fd);
            exit(-1);
        }
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
    header << "BW " << fixed << setprecision(4) << channel_bandwidth * channels_in_file * 1e-6 << endl;
    header << "FREQ " << fixed << setprecision(6) << frequency * 1e-6<< endl;
    header << "TELESCOPE " << telescope << endl;
    header << "RECEIVER " << telescope << endl;
    header << "INSTRUMENT " << telescope << endl;
    header << "SOURCE " << source << endl;
    header << "MODE PSR" << endl;
    header << "NBIT " << nbits << endl;
    header << "NPOL " << npol << endl;
    header << "NCHAN " << channels_in_file << endl;
    header << "NDIM " << ndim << endl;
    header << "OBS_OFFSET 0" << endl;
    header << "TSAMP " << fixed << setprecision(4) << (1.0 / channel_bandwidth) * 1e6 << endl;
    header << "UTC_START " << time_string << endl;

    // Additional entries to match post-processing requiremenents
    header << "POPULATED 1" << endl;
    header << "OBS_ID 0" << endl;
    header << "SUBOBS_ID 0" << endl;
    header << "COMMAND CAPTURE" << endl;

    header << "NTIMESAMPLES 1" << endl;
    header << "NINPUTS " << fixed << channels_in_file * npol << endl;
    header << "NINPUTS_XGPU " << fixed << channels_in_file * npol << endl;
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
    header << "FINE_CHAN_WIDTH_HZ " << fixed << setprecision(6) << channel_bandwidth / n_fine_channels  << endl;
    header << "NFINE_CHAN " << n_fine_channels << endl;
    header << "BANDWIDTH_HZ " << fixed << setprecision(6) << channel_bandwidth * channels_in_file << endl;
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
	      << "\t-I/--individuail\t\t\tGenerate separate channels files\n"
              << std::endl;
}

// Parse command line arguments
static void parse_arguments(int argc, char *argv[])
{
    // Define options
    const char* const short_opts = "d:t:s:i:p:c:m:n:S:DI";
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
            {"individual", no_argument, nullptr, 'I'},
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
            case 'I':
                individual_channel_files = true;
                break;
            default: /* '?' */
                print_usage(argv[0]);
                exit(EXIT_FAILURE);
        }
    }

    printf("Running acquire_station_beam with %ld samples starting from logical channel %d and saving %d channels.\n",
		    nof_samples, start_channel, nof_channels);
    printf("Saving in directory %s with maximum file size of %ld GB\n", base_directory.c_str(), max_file_size_gb);
    printf("Observing source %s for %d seconds\n", source.c_str(), duration);
}


int main(int argc, char *argv[])
{
    // Process command-line argument
    parse_arguments(argc, argv);

    // Split files into max_file_size_gb x 1G. If DADA header is being generated, set do not split file (set
    // cutoff counter to "infinity"
    if (include_dada_header)
        cutoff_counter = INT_MAX;
    else
        cutoff_counter = (max_file_size_gb * 1024 * 1024 * 1024) / (nof_samples * nof_channels * npol * sizeof(uint16_t));

    // If received only 1 channel, then individual_channel_files can be disabled
    if (nof_channels == 1)
        individual_channel_files = false;

    // Telescope information
    startReceiver(interface.c_str(), ip.c_str(), 9000, 32, 64);
    addReceiverPort(4660);

    // Set parameters
    json j = {
            {"start_channel", start_channel},
            {"nof_channels", nof_channels},
            {"nof_samples", nof_samples},
            {"transpose_samples", (individual_channel_files) ? 0 : 1},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "stationdataraw") != SUCCESS) {
        LOG(ERROR, "Failed to load station data conumser");
        return 0;
    }

    if (initialiseConsumer("stationdataraw", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise station data conumser");
        return 0;
    }

    if (startConsumer("stationdataraw", raw_station_beam_callback) != SUCCESS) {
        LOG(ERROR, "Failed to start station data conumser");
        return 0;
    }

    sleep(duration);

    if (stopConsumer("stationdataraw") != SUCCESS) {
        LOG(ERROR, "Failed to stop station data conumser");
        return 0;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return 0;
    }
}
