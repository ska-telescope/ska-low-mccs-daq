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
import math
import time

temp_dir = "./temp_daq_test"
data = []
data_received = False
first_channel_offset = 64
gain = 2


def check_beam(pattern, adders, data):
    pol, ch, sam, x = data.shape
    x = 0
    for c in range(ch):
        for p in range(pol):
            for s in [0]:#range(sam):
                sample_idx = 2 * c + first_channel_offset
                signal_idx = 0
                exp_re = int(pattern[sample_idx] % 256) << 4
                exp_im = int(pattern[sample_idx+1] % 256) << 4
                #print(exp_re)
                #print(exp_im)
                exp_re = tf.signed(exp_re, 12, 12)
                exp_im = tf.signed(exp_im, 12, 12)
                #print(exp_re)
                #print(exp_im)

                exp_re = int(exp_re * 8 / 2) * 2
                exp_im = int(exp_im * 8 / 2) * 2

                exp_re_round = tf.s_round(exp_re, 4, 16)
                exp_im_round = tf.s_round(exp_im, 4, 16)
                exp = (exp_re_round*2, exp_im_round*2)

                if abs(exp[0] - data[p, c, s, x][0]) > 2 or abs(exp[1] != data[p, c, s, x][1]) > 2:
                    print("Data Error!")
                    print("Frequency Channel: " + str(c))
                    print("Polarization: " + str(p))
                    print("Sample index: " + str(s))
                    print("Expected data real: " + str(exp_re_round))
                    print("Expected data imag: " + str(exp_im_round))
                    print("Expected data: " + str(exp))
                    print("Received data: " + str(data[p, c, s, x]))
                    input("Press a key")
                    # exit(-1)
    print("Beam data are correct")



def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received
    global data

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

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
    #daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    #daq.start_channel_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    daq.start_beam_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    #
    # beam data
    #
    tile.stop_pattern("all")
    tile.disable_all_adcs()
    tile.test_generator_disable_tone(0)
    tile.test_generator_disable_tone(0)
    tile.test_generator_set_noise(0.0)
    tile.test_generator_input_select(0x0)
    tile['fpga1.pattern_gen.channel_left_shift'] = 4
    tile['fpga2.pattern_gen.channel_left_shift'] = 4

    tile.set_channeliser_truncation(0)
    tf.reset_beamf_coeff(tile, gain)

    remove_files()

    # channels = range(64, 448)

    for n in range(0,256,1):
        print(n)
        pattern = [n]*1024 #range(1024)
        adders = [0] * 128

        tile.set_pattern("channel", pattern, adders, True)


        # Set data received to False
        data_received = False
        # Send data from tile

        tile.send_beam_data()

        # Wait for data to be received
        while not data_received:
            time.sleep(0.1)

        check_beam(pattern, adders, data)


    daq.stop_daq()
