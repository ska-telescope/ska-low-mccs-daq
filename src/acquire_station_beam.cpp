#include <iostream>
#include <unistd.h>
#include <fcntl.h>
#include <getopt.h>

#include "DAQ.h"

// Acqusition parameters
std::string base_directory = "/data/";
std::string interface = "eth2";
std::string ip = "10.0.10.40";
uint32_t nof_samples = 262144;
uint32_t channel_to_store = 0;
uint32_t duration = 60;

int fd = 0;

uint32_t counter = 0;
uint32_t cutoff_counter = 0;

void pharos_beam_callback(void *data, double timestamp, unsigned int nof_packets, unsigned int nof_samples)
{
    printf("Received station beam with %d packets and %d samples\n", nof_packets, nof_samples);

    if (counter % cutoff_counter == 0)
    {
        std::string path = base_directory + "channel_" + std::to_string(channel_to_store) + "_" + std::to_string(timestamp) + ".dat";

        fd = open(path.c_str(), O_WRONLY | O_CREAT | O_SYNC | O_TRUNC, (mode_t) 0600);

        // Tell the kernel how the file is going to be accessed (sequentially)
        posix_fadvise(fd, 0, 0, POSIX_FADV_SEQUENTIAL);
    }

    if (write(fd, data, nof_samples * 2 * sizeof(uint16_t)) < 0)
    {
        perror("Failed to write buffer to disk");
        fsync(fd);
        close(fd);
    }

    counter += 1;
}

static void print_usage(char *name)
{
std::cerr << "Usage: " << name << " <option(s)>\n"
          << "Options:\n"
          << "\t-d DIRECTORY \t\tBase directory where to store data\n"
          << "\t-t DURATION \t\tDuration to acquire in seconds\n"
          << "\t-s NOF_SAMPLES\tNumber of samples\n"
          << "\t-c CHANNEL\tLogical channel ID to store\n"
          << "\t-i INTERFACE\tNetwork interface to use\n"
          << "\t-p IP\tInterface IP\n"
          << std::endl;
}

// Parse command line arguments
static void parse_arguments(int argc, char *argv[])
{
    int opt;
    while ((opt = getopt(argc, argv, "d:t:s:i:p:c:")) != -1) {
        switch (opt) {
            case 'd':
                base_directory = string(optarg);
                break;
            case 't':
                duration = (uint32_t) atoi(optarg);
                break;
            case 's':
                nof_samples = (uint32_t) atoi(optarg);
                break;
            case 'c':
                channel_to_store = (uint32_t) atoi(optarg);
                break;
            case 'i':
                interface = string(optarg);
                break;
            case 'p':
                ip = string(optarg);
                break;
            default: /* '?' */
                print_usage(argv[0]);
                exit(EXIT_FAILURE);
        }
    }

    printf("Running acquire_station_beam with %d for logical channel %d channels and saving in directory %s for %ds\n",
            nof_samples, channel_to_store, base_directory.c_str(), duration);
}


int main(int argc, char *argv[])
{
    // Process command-line argument
    parse_arguments(argc, argv);

    // Split files into 1G
    cutoff_counter = (1024 * 1024 * 1024) / (nof_samples * 2 * sizeof(uint16_t));

    // Telescope information
    startReceiver(interface.c_str(), ip.c_str(), 9000, 32, 64);
    addReceiverPort(4660);

    // Set parameters
    json j = {
            {"channel_to_save", channel_to_store},
            {"nof_samples", nof_samples},
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

    if (startConsumer("stationdataraw", pharos_beam_callback) != SUCCESS) {
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
