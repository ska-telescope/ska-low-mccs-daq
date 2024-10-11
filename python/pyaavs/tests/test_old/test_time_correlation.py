# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile import Tile

# Import required persisters
from pydaq.persisters.aavs_file import FileModes
from pydaq.persisters.raw import RawFormatFileManager
from pydaq.persisters.channel import ChannelFormatFileManager
from pydaq.persisters.beam import BeamFormatFileManager
from pydaq.persisters import *

from builtins import input
from sys import stdout
import test_functions as tf
import numpy as np
import os.path
import logging
import random
import time

temp_dir = "./temp_daq_test"
data_received = False

delays = []

def correlate_raw(data):
    global delays

    ref = np.array(data[0, 0, 0:2048],dtype='int')
    for a in range(16):
        for p in range(2):
            b = np.array(data[a, p, 0:2048],dtype='int')
            correlation = np.correlate(ref, b, 'full')
            max = correlation.max()
            idx = np.where(correlation == max)[0] - 2047
            if delays[2*a+p] != abs(idx):
                print("Correlation Error")
                print("Antenna: " + str(a))
                print("Polarisation " + str(p))
                print(data[0, 0, 0:128])
                print(data[a, p, 0:128])
                print("Expected delay: " + str(delays[2*a+p]))
                print("Calculated delay: " + str(abs(idx[0])))
                print("------------------------------------------------------------------------------------------")
                input("Press a key")
            else:
                print("TEST PASSED:")
                print("Antenna: " + str(a))
                print("Polarisation " + str(p))
                print(data[0, 0, 0:128])
                print(data[a, p, 0:128])
                print("Expected delay - calculated delay: " + str(delays[2*a+p]) + " - " + str(abs(idx[0])))
                print("------------------------------------------------------------------------------------------")


def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    if mode == "burst_raw":
        raw_file = RawFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = raw_file.read_data(antennas=range(16),  # List of channels to read (not use in raw case)
                                           polarizations=[0, 1],
                                           n_samples=32*1024)
        print("Raw data: {}".format(data.shape))
        correlate_raw(data)

    data_received = True



def remove_files():
    # create temp directory
    if not os.path.exists(temp_dir):
        print("Creating temp folder: " + temp_dir)
        os.system("mkdir " + temp_dir)
    os.system("rm " + temp_dir + "/*.hdf5")

if __name__ == "__main__":


    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser.add_option("--port", action="store", dest="port",
                      type="int", default="10000", help="Port [default: 10000]")
    parser.add_option("--tpm_ip", action="store", dest="tpm_ip",
                      default="10.0.10.3", help="IP [default: 10.0.10.3]")
    (conf, args) = parser.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    str_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(str_format)
    log.addHandler(ch)
    remove_files()

    # Connect to tile (and do whatever is required)
    tile = Tile(ip=conf.tpm_ip, port=conf.port)
    tile.connect()

    tile.stop_pattern("all")
    tile.test_generator_disable_tone(0)
    tile.test_generator_disable_tone(1)
    tile.test_generator_set_noise(0.2)
    # tile.test_generator_set_noise(0.0)
    # tile.test_generator_set_tone(0, 101e6, 0.2)
    tile.test_generator_input_select(0xFFFFFFFF)

    time.sleep(0.2)

    # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
    # I'll change this to make it nicer
    daq_config = {
                  'receiver_interface': 'eth3',  # CHANGE THIS if required
                  'directory': temp_dir,  # CHANGE THIS if required
                  'nof_beam_channels': 384,
                  'nof_beam_samples': 32,
                  'receiver_frame_size': 9000
                  }

    # Configure the DAQ receiver and start receiving data
    daq.populate_configuration(daq_config)
    daq.initialise_daq()

    # Start whichever consumer is required and provide callback
    daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    #
    # raw data synchronised
    #
    remove_files()

    print("Setting 0 delays...")
    delays = [0] * 32
    tf.set_delay(tile,delays)

    data_received = False
    # Send data from tile
    tile.send_raw_data_synchronised()
    # Wait for data to be received
    while not data_received:
        time.sleep(0.1)

    print("Setting random delays...")
    delays = [random.randrange(0, 16, 1) for x in range(32)]
    delays[0] = 0
    tf.set_delay(tile, delays)

    data_received = False
    # Send data from tile
    tile.send_raw_data_synchronised()
    # Wait for data to be received
    while not data_received:
        time.sleep(0.1)

    daq.stop_daq()

