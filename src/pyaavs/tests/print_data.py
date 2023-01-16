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
    if mode == "burst_raw":
        raw_file = RawFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = raw_file.read_data(antennas=range(16),  # List of channels to read (not use in raw case)
                                           polarizations=[0, 1],
                                           n_samples=32*1024)
        print("Raw data: {}".format(data.shape))

    if mode == "burst_channel":
        channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = channel_file.read_data(channels=range(512),  # List of channels to read (not use in raw case)
                                               antennas=range(16),
                                               polarizations=[0, 1],
                                               n_samples=128)
        print("Channel data: {}".format(data.shape))

    if mode == "burst_beam":
        beam_file = BeamFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = beam_file.read_data(channels=range(384),  # List of channels to read (not use in raw case)
                                               polarizations=[0, 1],
                                               n_samples=32)
        print("Beam data: {}".format(data.shape))

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
    parser.add_option("-t", "--type", action="store", dest="type",
                      default="both", help="channel, beam, both [default=both]")
    parser.add_option("-a", "--antenna", action="store", dest="antenna",
                      default="0", help="Antenna id [default=0]")
    parser.add_option("-b", "--antenna_b", action="store", dest="antenna_b",
                      default="no", help="Second Antenna id [default=0]")
    parser.add_option("-c", "--channel", action="store", dest="channel",
                      default="128", help="Frequency Channel id [default=128]")
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
    daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    daq.start_channel_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    daq.start_beam_data_consumer(callback=data_callback)
    #
    # beam data
    #
    channel = int(conf.channel)
    antenna = int(conf.antenna)



    while True:
        data_received = False
        tile.send_raw_data_synchronised()
        while not data_received:
                time.sleep(0.1)

        print(data[antenna, 0, :128])


        if conf.type in ["channel", "both"]:
            # Set data received to False
            data_received = False
            # Send data from tile
            tile.send_channelised_data(256)

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            # print(data[0, :, 0, 0])

            print("Antenna " + str(antenna) + " Pol 0 Channel " + str(channel) + ": " + str(data[channel, antenna, 0, 0]))  #+ " " + str(np.abs(data[channel, antenna, 0, 0]))
            print("Antenna " + str(antenna) + " Pol 1 Channel " + str(channel) + ": " + str(data[channel, antenna, 1, 0]))  #+ " " + str(np.abs(data[channel, antenna, 1, 0]))

            if conf.antenna_b != "no":
                antenna_b = int(conf.antenna_b)
                print("Antenna " + str(antenna_b) + " Pol 0 Channel " + str(channel) + ": " + str(data[channel, antenna_b, 0, 0]))  #+ " " + str(np.abs(data[channel, antenna, 0, 0]))
                print("Antenna " + str(antenna_b) + " Pol 1 Channel " + str(channel) + ": " + str(data[channel, antenna_b, 1, 0]))

        if conf.type in ["beam", "both"]:
            # Set data received to False
            data_received = False
            # Send data from tile
            tile.send_beam_data()

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            # print(data[0, :, 0, 0])

            print("Pol 0 Channel " + str(channel) + ": " + str(tf.get_beam_value(data, 0, channel-64)) + " " + str(np.abs(tf.get_beam_value(data, 0, channel-64))))
            print("Pol 1 Channel " + str(channel) + ": " + str(tf.get_beam_value(data, 1, channel-64)) + " " + str(np.abs(tf.get_beam_value(data, 1, channel-64))))

    daq.stop_daq()
