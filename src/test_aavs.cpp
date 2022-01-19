//
// Created by Alessio Magro on 30/04/2018.
//

#include "DAQ.h"

void test_raw_data()
{
    LOG(INFO, "Testing Raw Data");

    const char *ip = "192.168.11.11";
    startReceiver("enp7s0", ip, 9000, 32, 64);
    addReceiverPort(7200);

    // Set parameters
    json j = {
                {"nof_antennas", 32},
                {"samples_per_buffer", 65536},
                {"nof_tiles", 1},
                {"nof_pols", 2},
                {"max_packet_size", 9000}
            };

    if (loadConsumer("libaavsdaq.so", "rawdata") != SUCCESS) {
        LOG(ERROR, "Failed to load raw data conumser");
        return;
    }

    if (initialiseConsumer("rawdata", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise raw data conumser");
        return;
    }

    if (startConsumer("rawdata", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start raw data conumser");
        return;
    }

    sleep(2);

    if (stopConsumer("rawdata") != SUCCESS) {
        LOG(ERROR, "Failed to stop raw data conumser");
        return;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return;
    }
}

void test_burst_beam_data()
{
    LOG(INFO, "Testing Burst Beam Data");

    const char *ip = "10.0.10.20";
    startReceiver("eth1", ip, 9000, 32, 64);
    addReceiverPort(4660);

    // Set parameters
    json j = {
            {"nof_channels", 392},
            {"nof_samples", 32},
            {"nof_tiles", 1},
            {"nof_pols", 2},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "burstbeam") != SUCCESS) {
        LOG(ERROR, "Failed to load burst beam data conumser");
        return;
    }

    if (initialiseConsumer("burstbeam", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise burst beam data conumser");
        return;
    }

    if (startConsumer("burstbeam", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start burst beam data conumser");
        return;
    }

    sleep(5);

    if (stopConsumer("burstbeam") != SUCCESS) {
        LOG(ERROR, "Failed to stop burst beam data conumser");
        return;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return;
    }
}

void test_integrated_beam_data()
{
    LOG(INFO, "Testing Integrated Beam Data");

    const char *ip = "192.168.11.11";
    startReceiver("enp7s0", ip, 9000, 32, 64);
    addReceiverPort(7200);

    // Set parameters
    json j = {
            {"nof_channels", 392},
            {"nof_samples", 1},
            {"nof_tiles", 1},
            {"nof_beams", 1},
            {"nof_pols", 2},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "integratedbeam") != SUCCESS) {
        LOG(ERROR, "Failed to load integrated beam data conumser");
        return;
    }

    if (initialiseConsumer("integratedbeam", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise integrated beam data conumser");
        return;
    }

    if (startConsumer("integratedbeam", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start integrated beam data conumser");
        return;
    }

    sleep(2);

    if (stopConsumer("integratedbeam") != SUCCESS) {
        LOG(ERROR, "Failed to stop integarted beam data conumser");
        return;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return;
    }
}

void test_burst_channel_data()
{
    LOG(INFO, "Testing Burst Channel Data");

    const char *ip = "10.0.10.10";
    startReceiver("enp5s0", ip, 9000, 32, 64);
    addReceiverPort(4660);

    // Set parameters
    json j = {
            {"nof_channels", 512},
            {"nof_samples", 256},
            {"nof_antennas", 16},
            {"nof_tiles", 1},
            {"nof_pols", 2},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "burstchannel") != SUCCESS) {
        LOG(ERROR, "Failed to load burst channel data conumser");
        return;
    }

    if (initialiseConsumer("burstchannel", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise burst channel data conumser");
        return;
    }

    if (startConsumer("burstchannel", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start burst channel data conumser");
        return;
    }

    sleep(10);

    if (stopConsumer("burstchannel") != SUCCESS) {
        LOG(ERROR, "Failed to stop burst channel data conumser");
        return;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return;
    }
}

void test_continuous_channel_data()
{
    LOG(INFO, "Testing Continuous Channel Data");

    const char *ip = "10.0.10.10";
    startReceiver("enp5s0", ip, 9000, 32, 64);
    addReceiverPort(4660);

    // Set parameters
    json j = {
            {"nof_channels", 1},
            {"nof_samples", 262144},
            {"nof_antennas", 16},
            {"nof_tiles", 16},
            {"nof_pols", 2},
            {"nof_buffer_skips", 0},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "continuouschannel") != SUCCESS) {
        LOG(ERROR, "Failed to load continuous channel data conumser");
        return;
    }
    LOG(INFO, "Loaded consumer");

    if (initialiseConsumer("continuouschannel", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise continuous channel data conumser");
        return;
    }
    LOG(INFO, "Initialised consumer");

    if (startConsumer("continuouschannel", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start continuous channel data conumser");
        return;
    }
    LOG(INFO, "Started consumer");

    sleep(10);

    if (stopConsumer("continuouschannel") != SUCCESS) {
        LOG(ERROR, "Failed to stop continuous channel data conumser");
        return;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return;
    }
}

void test_integrated_channel_data()
{
    LOG(INFO, "Testing Integrated Channel Data");

    const char *ip = "192.168.11.11";
    startReceiver("enp7s0", ip, 9000, 32, 64);
    addReceiverPort(7200);

    // Set parameters
    json j = {
            {"nof_channels", 512},
            {"nof_antennas", 16},
            {"nof_tiles", 1},
            {"nof_pols", 2},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "integratedchannel") != SUCCESS) {
        LOG(ERROR, "Failed to load integrated channel data conumser");
        return;
    }

    if (initialiseConsumer("integratedchannel", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise integrated  channel data conumser");
        return;
    }

    if (startConsumer("integratedchannel", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start integrated  channel data conumser");
        return;
    }

    sleep(2);

    if (stopConsumer("integratedchannel") != SUCCESS) {
        LOG(ERROR, "Failed to stop integrated  channel data conumser");
        return;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return;
    }
}

void test_correlator_data()
{
    LOG(INFO, "Testing Correlator");

    for(unsigned i = 0; i < 10; i++) {

        // Telescope information
        const char *ip = "10.0.10.201";

        startReceiver("eth3:1", ip, 9000, 32, 64);
        addReceiverPort(7200);

        // Set parameters
        json j = {
                {"nof_channels",      1},
                {"nof_fine_channels", 1},
                {"nof_antennas",      16},
                {"nof_tiles",         16},
                {"nof_samples",       1835008},
                {"nof_pols",          2},
                {"max_packet_size",   9000}
        };

        if (loadConsumer("libaavsdaq.so", "correlator") != SUCCESS) {
            LOG(ERROR, "Failed to load correlator data conumser");
            return;
        }

        if (initialiseConsumer("correlator", j.dump().c_str()) != SUCCESS) {
            LOG(ERROR, "Failed to initialise correlator data conumser");
            return;
        }

        if (startConsumer("correlator", nullptr) != SUCCESS) {
            LOG(ERROR, "Failed to start correlator data conumser");
            return;
        }

        sleep(200);

        if (stopConsumer("correlator") != SUCCESS) {
            LOG(ERROR, "Failed to stop integrated  channel data conumser");
            return;
        }

        if (stopReceiver() != SUCCESS) {
            LOG(ERROR, "Failed to stop receiver");
            return;
        }
    }
}

void test_station_data()
{
    LOG(INFO, "Testing Station Data");

    // Telescope information
    const char *ip = "10.0.10.250";
    startReceiver("eth2", ip, 9000, 32, 64);
    addReceiverPort(4660);

    // Set parameters
    json j = {
            {"nof_channels", 384},
            {"nof_samples", 262144},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "stationdata") != SUCCESS) {
        LOG(ERROR, "Failed to load station data conumser");
        return;
    }

    if (initialiseConsumer("stationdata", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise station data conumser");
        return;
    }

    if (startConsumer("stationdata", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start station data conumser");
        return;
    }

    sleep(200);

    if (stopConsumer("stationdata") != SUCCESS) {
        LOG(ERROR, "Failed to stop station data conumser");
        return;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return;
    }
}


void test_multi() {
    LOG(INFO, "Testing Multiple receivers");

    const char *ip = "10.0.10.10";
    startReceiver("enp5s0", ip, 9000, 32, 64);
    addReceiverPort(4660);

    // Set parameters
    json j = {
            {"nof_channels", 1},
            {"nof_samples", 262144},
            {"nof_antennas", 16},
            {"nof_tiles", 16},
            {"nof_pols", 2},
            {"nof_buffer_skips", 0},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "continuouschannel") != SUCCESS) {
        LOG(ERROR, "Failed to load continuous channel data conumser");
        return;
    }
    LOG(INFO, "Loaded cont channel consumer");

    if (initialiseConsumer("continuouschannel", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise continuous channel data conumser");
        return;
    }
    LOG(INFO, "Initialised cont channel consumer");

    if (startConsumer("continuouschannel", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start continuous channel data conumser");
        return;
    }
    LOG(INFO, "Started cont channel consumer");

    // Set parameters
    j = {
            {"nof_channels", 512},
            {"nof_samples", 256},
            {"nof_antennas", 16},
            {"nof_tiles", 1},
            {"nof_pols", 2},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "burstchannel") != SUCCESS) {
        LOG(ERROR, "Failed to load burst channel data conumser");
        return;
    }

    if (initialiseConsumer("burstchannel", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise burst channel data conumser");
        return;
    }

    if (startConsumer("burstchannel", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start burst channel data conumser");
        return;
    }

    // Set parameters
    j = {
            {"nof_antennas", 32},
            {"samples_per_buffer", 65536},
            {"nof_tiles", 1},
            {"nof_pols", 2},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "rawdata") != SUCCESS) {
        LOG(ERROR, "Failed to load raw data conumser");
        return;
    }

    if (initialiseConsumer("rawdata", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise raw data conumser");
        return;
    }

    if (startConsumer("rawdata", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start raw data conumser");
        return;
    }

    // Set parameters
    j = {
            {"nof_channels", 392},
            {"nof_samples", 1},
            {"nof_tiles", 1},
            {"nof_beams", 1},
            {"nof_pols", 2},
            {"max_packet_size", 9000}
    };

    if (loadConsumer("libaavsdaq.so", "integratedbeam") != SUCCESS) {
        LOG(ERROR, "Failed to load integrated beam data conumser");
        return;
    }

    if (initialiseConsumer("integratedbeam", j.dump().c_str()) != SUCCESS) {
        LOG(ERROR, "Failed to initialise integrated beam data conumser");
        return;
    }

    if (startConsumer("integratedbeam", nullptr) != SUCCESS) {
        LOG(ERROR, "Failed to start integrated beam data conumser");
        return;
    }


    sleep(5);

    if (stopConsumer("rawdata") != SUCCESS) {
        LOG(ERROR, "Failed to stop raw data conumser");
        return;
    }

    if (stopConsumer("burstchannel") != SUCCESS) {
        LOG(ERROR, "Failed to stop raw data conumser");
        return;
    }

    if (stopConsumer("continuouschannel") != SUCCESS) {
        LOG(ERROR, "Failed to stop raw data conumser");
        return;
    }

    if (stopConsumer("integratedbeam") != SUCCESS) {
        LOG(ERROR, "Failed to stop raw data conumser");
        return;
    }

    if (stopReceiver() != SUCCESS) {
        LOG(ERROR, "Failed to stop receiver");
        return;
    }


}

int main()
{
//    test_raw_data();
//    test_burst_beam_data();
//    test_integrated_beam_data();
    //test_burst_channel_data();
    //test_continuous_channel_data();
//    test_integrated_beam_data();
//    test_correlator_data();
//    test_station_data();
     test_multi();
}

