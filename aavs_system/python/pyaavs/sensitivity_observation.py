#! /usr/bin/env python

from pydaq import daq_receiver as receiver
from pyaavs import station
import pyaavs.logger

import threading
import logging
import time


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser.add_option("--config", action="store", dest="config",
                      type="str", default=None, help="Configuration file [default: None]")
    parser.add_option("-d", "--data-directory", action="store", dest="directory",
                     default=".", help="Parent directory where data will be stored [default: current directory]")

    parser.add_option("--channels", action="store", dest="channels", 
                      default="", help="Comma-separated list of channels to acquire. Note that for each chan, nof_contiguous_channels will be acquired [default: Empty]")
    parser.add_option("--time_per_channel", "--inttime", "--dwell-time", action="store", dest="time_per_channel",
                     type="int", default=10, help="Time on each channel per iteration in seconds [default: %default seconds]")
    parser.add_option("--nof_contiguous_channels", action="store", dest="nof_cont_channels",
                     type="int", default=2, help="Number of contiguous channels [default: 2 channel]")
    parser.add_option("--start_ux", "--start_unixtime", action="store", dest="start_unixtime",
                      type="int", default=-1, help="Start unixtime [default: %default]")                      
    parser.add_option("--n_iterations", "--n_iter", "--iterations", action="store", dest="n_iterations", default=1, 
                      help="Number of iterations over channels [default %default]",type="int")
    (conf, args) = parser.parse_args(argv[1:])

    # Set current thread name
    threading.currentThread().name = "Station"

    # Sanity check on list of channels
    try:
        # Extract provided channels and include channel + 1
        conf.channels = [[int(x) + i for i in range(conf.nof_cont_channels)] for x in conf.channels.split(',')]

        # Flatten generated list
        conf.channels = [item for sublist in conf.channels for item in sublist]

    except Exception as e:
        logging.error("Could not process provided list of channels: ", e)
   
    # Load station configuration file
    try:
       station.load_configuration_file(conf.config)
    except:
       print("Check station configuration file")
       exit()

    # Override parameters
    station_config = station.configuration
    station_config['station']['program'] = True
    station_config['station']['initialise'] = True
    station_config['station']['start_beamformer'] = False

    # Connect to the station
    test_station = station.Station(station_config)
    test_station.connect()

    # Re-set program and initialise to False otherwise DAQ will re-do the action
    station_config['station']['program'] = False
    station_config['station']['initialise'] = False

    # Generate DAQ configuration
    daq_config = {"station_config": conf.config,
                  "directory": conf.directory,
                  "nof_correlator_samples": 1835008,
                  "nof_correlator_channels": 1,
                  "description": "Performing sensitivity observation",
                  "nof_tiles": len(test_station.tiles),
                  "receiver_interface": "enp216s0f0",
                  "receiver_frame_size": 9000}

    # First wait until specified time 
    if conf.start_unixtime > 0 :
        wait_time = int(conf.start_unixtime - time.time() )
        logging.info("Waiting {} seconds to start data acuisition ...".format(wait_time))
        time.sleep( wait_time )   

    # Start correlator
    logging.info("Starting DAQ")
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_correlator()

    # Wait for correlator to load
    time.sleep(5)

    # Go through all iterations
    for i in range(conf.n_iterations):
        logging.info("Acqusition iteration {}".format(i))
        for channel in conf.channels:
            # Instruct station to start transmitting channels
            test_station.send_channelised_data_continuous(channel)
            # Wait for the required duration
            time.sleep(conf.time_per_channel)

    # Wait for data from last station to be processed
    time.sleep(5)

    # All done, stop DAQ
    try:
        receiver.stop_daq()
    except Exception as e:
        logging.error("Failed to stop DAQ cleanly: {}".format(e))

    # Stop data transmission
    test_station.stop_data_transmission()

    logging.info("All done")
    
