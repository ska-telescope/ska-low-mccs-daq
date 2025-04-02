#!/usr/bin/env python2
from builtins import input
from builtins import range
from pydaq import daq_receiver as receiver
from pyaavs import station
import pyaavs.logger

from matplotlib import pyplot as plt
from threading import Thread
from time import sleep
import numpy as np
import logging
import h5py
import os

# Frequencies
# Sky     Chan    LO2
# 50      64       0
# 70      90      -312500
# 110     141     -156250
# 137     175      281250
# 160     205     -156250
# 230     294      312500
# 320     410     -312500

# Global parameters
narrowband_bitfile = "/opt/aavs/bitfiles/itpm_v1_1_tpm_test_wrap_sbf347.bit"
parent_data_directory = "/storage/uav_tests"

# Store for channel RMS
stop_thread = False
channel_rms = []

def daq_callback(data_type, filename, tile):
    """ DAQ continuous data callback """
    if tile == 0:
        logging.info("Received narrowband data")

    with h5py.File(filename, 'r') as f:
        data = f['chan_']['data'][-512:, 1]
    
    logging.info("{}".format(data['imag'][:512:32]))
    data = np.sqrt(np.mean(np.abs(data['real'] + 1j*data['imag']) ** 2))
    channel_rms[tile].append(data)


def initialise_daq(interface, directory, nof_tiles):
    """ Configure DAQ"""

    # DAQ configuration
    daq_config = {"receiver_interface": interface,
                  "nof_tiles": nof_tiles,
                  'directory': directory,
                  "nof_channel_samples": 16384,
                  "sampling_rate": ((400e6 / 512.0) * (32.0 / 27.0)) / 128.0 }
    
    # Turn off DAQ logging
    receiver.LOG = False

    # Initialise and start DAQ
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_continuous_channel_data_consumer(daq_callback)

def live_plot(nof_tiles):
    """ Handle live plotting """
    global channel_rms
    global stop_thread

    plt.ion()

    # Initialise plot
    nof_plot_points = 25
    channel_rms = [[0] * nof_plot_points for i in range(nof_tiles)]

    # Create lines
    plot_lines = []
    for i in range(nof_tiles):
        line, = plt.plot([0] * nof_plot_points, label="Tile {}".format(i))
        plot_lines.append(line)

    # Show figure
    plt.title("Antenna 0, Pol Y RMS")
    plt.xlabel("RMS")
    plt.xlabel("Timestep")
    plt.legend()
    plt.show()

    # Update loop
    while not stop_thread:
        for i in range(nof_tiles):
            plot_lines[i].set_ydata(channel_rms[i][-nof_plot_points:])

        # Update plot
        ax = plt.gca()
        ax.relim()
        ax.autoscale_view()
        plt.draw()
        plt.pause(0.001)

        # Sleep one second at a time to be able to stop correctly
        for i in range(2):
            if stop_thread:
                plt.close('all')
                return
            sleep(1)


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %uav_campaign [options]")
    parser.add_option("--config", action="store", dest="config", default=None, 
                      help="Station configuration file to use")
    parser.add_option("--directory", action="store", dest="data_directory", default=None,
                      help="Directory where acquired data will be stored")
    parser.add_option("--frequency", action="store", dest="frequency", 
                      default=0, type="float", help="Frequency to acquire MHz")
    parser.add_option("--round-bits", action="store", dest="round_bits", 
                      default=7, type="int", help="Number of bits to round (default: 7)")    
    parser.add_option("--truncation", action="store", dest="truncation", 
                      default=4, type="int", help="Channel truncation (default: 4)")
    parser.add_option("-P", "--program", action="store_true", dest="program", 
                      default=False, help="Program and initialise station (default: False)")
    parser.add_option("--interface", action="store", dest="interface",
                      help="Network interface")
    parser.add_option("--preadu-attenuation", action="store", dest="preadu", type=int, default=31,
                      help="Preadu attenuation")
    parser.add_option("--live-plot", action="store_true", dest="live_plot",
                      default=False, help="Show live plot (default: False)")

    (opts, args) = parser.parse_args(argv[1:])

    # Check if a configuration file was defined
    if opts.config is None or not os.path.exists(opts.config):
        logging.error("A station configuration file is required, exiting")
        exit()
    
    # Sanity checks on data directory
    if opts.data_directory is None:
        logging.error("Data directory must be specified")
        exit()

    # Check if interface is specified
    if opts.interface is None:
        logging.error("Network interface must be specified")
        exit()

    if not os.path.exists(parent_data_directory):
        try:
            os.mkdir(parent_data_directory)
        except Exception as e:
            logging.error("Could not create parent data directory {}: {}".format(
                           parent_data_directory, e))
            exit()

    data_directory = os.path.join(parent_data_directory, opts.data_directory)
    
    # If directory does not exist, create it
    if not os.path.exists(data_directory):
        try:
            os.mkdir(data_directory)
        except Exception as e:
            logging.error("Could not create data directory {}: {}".format(
                          data_directory, e))
            exit()
        
    # If directory contains data, check if user want to delete them. If not, exit
    elif len(os.listdir(data_directory)) != 0 :
        while True:
            response = input("Data directory {} already exists. Overwrite? [Y / N]: ".format(data_directory))
            response = response.strip().upper()
            if response not in ['Y', 'N']:
                continue
            elif response == 'Y':
                import shutil
                try:
                    shutil.rmtree(data_directory)
                    os.mkdir(data_directory)
                    break
                except Exception as e:
                    logging.error("Could not empty directory {}: {}. Please check".format(data_directory, e))
                    exit(0)
            else:
                logging.info("An empty directory must be specified. Exiting")
                exit()
    
    # Otherwise directory exists but is empty. Use it
    
    # Sanity check on frequency
    if not 50e6 < opts.frequency * 1e6 < 350e6:
        logging.error("Frequency should be between 50 MHz and 350 MHz")
        exit()

    #  Sanity check on bit rounding
    if not 0 <= opts.round_bits <= 7:
        logging.error("Rounding bits should be between 0 and 7")
        exit()

    # Load configuration file
    station.load_configuration_file(opts.config)

    # Override bitfile to use narrowband firmware
    station.configuration['station']['bitfile'] = narrowband_bitfile

    # Override program/initialise directives if required
    if opts.program:
        station.configuration['station']['program'] = True
        station.configuration['station']['initialise'] = True

    # Override channel truncation
    station.configuration['station']['channel_truncation'] = opts.truncation

    # Connect to station and check
    aavs_station = station.Station(station.configuration)
    aavs_station.connect()
    if not aavs_station.properly_formed_station:
        logging.error("Station not configured properly, please check. Exiting")
        exit()

    # Set preadu to maximum attenuation and channel truncation
    for tile in aavs_station.tiles:
        tile.set_channeliser_truncation = opts.truncation

    logging.info("Setting preadu attenuation to {}".format(opts.preadu))
    aavs_station.set_preadu_attenuation(opts.preadu)

    # Get number of tiles
    nof_tiles = len(station.configuration['tiles'])

    # Initialise DAQ
    initialise_daq(opts.interface, data_directory, nof_tiles)

    # Start data transmission
    aavs_station.send_channelised_data_narrowband(opts.frequency * 1e6, opts.round_bits)

    # Wait for stopping clause (keyboard press of letter 'q')
    logging.info("---------------------------------")
    logging.info("Press q followed by Enter to stop")
    logging.info("---------------------------------")

    # Create plotting thread if required
    if opts.live_plot:
        plotting_thread = Thread(target=live_plot, args=(nof_tiles, ))
        plotting_thread.start()
    
    # Wait for exit
    while input("").strip().upper() != "Q":
        pass

    # Clean up
    logging.info("Finishing up")
    receiver.stop_daq()

    # If plotting, stop plotting thread
    if opts.live_plot:
        stop_thread = True
        plotting_thread.join()
