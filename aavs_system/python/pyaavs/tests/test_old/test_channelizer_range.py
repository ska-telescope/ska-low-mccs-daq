# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile import Tile

# Import required persisters
from pydaq.persisters.aavs_file import FileModes
from pydaq.persisters.raw import RawFormatFileManager
from pydaq.persisters.channel import ChannelFormatFileManager
from pydaq.persisters.beam import BeamFormatFileManager
from pydaq.persisters import *

from sys import stdout
import test_functions as tf
import numpy as np
import os.path
import logging
import random
import math
import time

temp_dir = "./temp_daq_test"
data = []
data_received = False


def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received
    global data

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    if mode == "burst_channel":
        channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = channel_file.read_data(channels=range(512),  # List of channels to read (not use in raw case)
                                               antennas=range(16),
                                               polarizations=[0, 1],
                                               n_samples=128)
        print("Channel data: {}".format(data.shape))

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
    # daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    daq.start_channel_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    # daq.start_beam_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    #
    # beam data
    #
    tile.stop_pattern("all")
    tile.disable_all_adcs()
    tile.test_generator_disable_tone(0)
    tile.test_generator_disable_tone(1)
    tile.test_generator_set_noise(0.0)
    tile.test_generator_input_select(0xFFFFFFFF)
    tf.set_delay(tile, [0]*32)

    tile.set_channeliser_truncation(3)

    points_per_channel = 5
    channels = [57]
    channel_width = 400e6 / 512.0

    saturation = []
    channel_abs = []
    for channel in channels:
        print("Channel " + str(channel))
        for ampl in range(11):
            frequency = channel * channel_width
            tile.test_generator_set_tone(0, frequency, 0.1*ampl)

            time.sleep(1)

            remove_files()
            data_received = False
            tile.send_channelised_data(256)

            while not data_received:
                time.sleep(0.1)

            ch, ant, pol, sam = data.shape
            for i in range(1):  # range(sam):
                channel_value = data[channel, 0, 0, i][0] + data[channel, 0, 0, i][1]*1j
                print("CW amplitude: " + str(ampl))
                print(channel_value)
                print(abs(channel_value))
                if channel_value.real == -128 or channel_value.imag == -128:
                    saturation.append("Saturated     - Amplitude: ")
                    channel_abs.append(0)
                else:
                    saturation.append("No saturation - Amplitude: ")
                    channel_abs.append(abs(channel_value))

    daq.stop_daq()

    print()
    for n in range(len(channel_abs)):
        print("CW amplitude " + str(0.1*n) + " => " + str(saturation[n]) + str(channel_abs[n]))
    print()
    print("Amplitude difference:")
    for n in range(1,len(channel_abs)):
        if channel_abs[n] > 0:
            print("A" + str(n) + "-A" + str(n-1) + ": " + str(channel_abs[n] - channel_abs[n-1]))

