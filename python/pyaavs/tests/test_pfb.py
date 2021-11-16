# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile_wrapper import Tile
from config_manager import ConfigManager

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
import re

data = []
data_received = False
channel_samples = 512

data_pattern = [ 28,  30,  23,  -8, -11,   3,  26,   2, -30, -16, -17, -27, -18,
       -32,   0, -17,  20, -30,  22,   3,  -3,  12,  26,  -2,  18, -25,
       -14,   1,  17,   5, -20, -18, -31,  17, -26,  28, -21, -13, -26,
       -19, -12,  -5,  -3, -22,  20, -28, -16,  17, -26,  -4,  24,  22,
         2, -26,   6,  -6, -27, -30,  17,  26,  -1, -26,  -1,  -7,   7,
         9, -18, -11,   9,   2, -24,   8, -30, -26,   4,  28, -10, -26,
        18,  29,  -9, -14,  15, -21,   8,  22,   6,  14, -16,  -4, -13,
       -31,   0,  30,  31,  19, -31, -19,  21,  17, -32, -13,  23,   5,
        19, -30, -13,  18, -13, -13, -21, -27, -25, -23,  -6, -30, -21,
        17, -18,  28,  31,  20,  -8, -29, -30, -26,  -1, -12,   2,  -2,
         6,  18,  23,   5,   8,   3,  16,  -9, -17,  26,   6, -12,  -3,
        -8,   0,  27,  23,  -6,  -8, -30,  13,  -8,  26, -12,  21,  17,
        16, -14,  26,  12, -19, -28,   1,   4,  10, -27,  -3,  12, -27,
        25,   3,  28,  -4,  -8,  13, -11, -30,  -8,  14, -17, -18,  22,
         5,  26,  -8,  30,  21, -26,  28,   3,   3,  21,  -3, -21,   1,
        19,  14,  15,   4, -26,  31,   2,  16,  18, -19, -15,   9,  -7,
        30, -27, -22, -13,  23,  12,  -4, -20,  19,  10,  19, -21, -10,
         4,   7,  26, -21,  17,  -3, -16,  19, -21,   0,   7, -16, -13,
       -23,  13,  23, -24,   0,  21, -11, -20, -19, -24,  31,   7, -18,
        20, -24, -25,  23, -14,   2,  -5,  -7, -24, -30, -11,  19, -20,
       -12,  10, -16,  -5,  21, -26,  -4,  26, -27, -21, -28,   7,  23,
         3,  29, -27,  31,   6,  27, -11,   2,  25, -19,  12,  -5,  15,
        29, -24,  -7,  25, -24,   5,  17, -26,  21,  25,  -9,   9,  12,
        26,   1, -12, -16,  -4, -10,   8, -22,  18,  16,  22,  24,   7,
         4, -15, -16,  15,  29,  19,   4,  10,   9,  20,   7,   5, -23,
        10,  18,  19, -15,   6,  25,  28, -20,  12,  15, -21,  -6,  13,
       -32, -11,  30, -28, -27, -30,  -4,  23, -19,  -4,   2,  -1, -15,
         6, -29,  16, -27,  11,  -1,   1,  14, -10,  20,  11, -19,  20,
       -14,  31, -29,  19,   4,   6, -19,  21,  30,  14,  21,  -4,  27,
         7, -21, -23,   5,  23,  13, -13, -29,  -2, -17,   6,  19,  18,
        22,  10,  -1, -21,  19,  -4, -23,  -9,  -4,  31, -15,  24,   8,
        11,   6,  14,  17, -14, -19, -10, -25, -21, -32, -12,   0,  -9,
        24,   6, -11, -25,  -6, -16,   5,  -8, -19,   1, -15,   3, -22,
        25, -11,  28,  12, -17,  17, -29,   9, -26,   5,  16,  -2,  23,
        30,  26,  -8, -19,   2,  10,  14, -10,  -5,  29,  23,  29,  19,
       -12,  -6,   3,  -6, -23,  -4,   4,   7,  -3,  -6,  21,  14, -23,
        10, -12, -32,  21,  -9,   9,  -5, -21, -12, -25, -14, -25,   0,
        25,   3,  10,  -2, -23,  25,  10, -28,  24,   9, -16,  29, -21,
        -6,  22,  26,  -4,  -7, -32,  -8, -25,  19,  19,  14,  10, -26,
        26,   5, -18,   0,   4,  23, -23,  26,  27,  26,  26, -29,   5,
       -31,  -8,   3,  -7, -10,  19,   9,  16,  -1, -24,  -5,  -9,  12,
        25,  -2,   0,   5,  -8,  17,   9,   4, -25,   7,  25, -19,  -7,
        28,  23,  -2, -20, -21, -30,  21, -28,  26,   7,   3,  15,  31,
        30, -29,  -6, -25,   2,  10,  12,   7,   6,  16,  23,  16,  26,
         3,   4,  30,   8, -30, -25,  26,  19,   1, -12,   1,  -2, -22,
       -11,  13, -18, -18, -13, -10,  30,  -3,  20,   2,  18, -20,  29,
       -27,   3,   6, -13, -28, -31,  22,  -3,   7,  12, -15,   1,  14,
       -29,   0, -13,  -8,  -8, -17,   4,  -7,  30, -14,   3,   4,   7,
        15,   1,   4,  -8,  -8,  15,  11,  27, -24,  27,  -7, -21, -26,
        15, -12, -27,   5, -13, -24, -31, -22,  -1, -15,   8,   8, -22,
       -13,  20,  -7, -23,  -2,  12,  -2,  20, -31,  30,  25,  23,  29,
         2, -22,  17, -31, -30,  19, -23,  -6, -13, -24, -25,  13, -13,
       -25,  11,  11, -30, -15, -31,  17, -19,  -8,  16,  25, -12, -25,
         9,  16,   9,  23,   4, -13,  -6,  17,  23, -19,   2,   8, -21,
       -16,  -1,  23,   4,   9,   7,  30, -22, -25, -19, -25,  14,  -6,
       -10,   7,  15,  -6,   3,   4, -14,  -9,   2,  -1,  21,  14, -19,
         8,  19, -17,  -7,  13,  -8, -25,   5, -31,  23,  -8,  -6,   5,
        19,  -3,  -5, -27,  25,   4,  23, -25, -28, -19,  -2, -24, -20,
        24,  21,  -2,  23,  11,  27,  13, -11, -28,  18,  12,   7,  21,
       -25,  31, -21,   5, -12, -15, -10,  30,  21, -29,  25,  16,  -9,
       -28,  13,  24, -11, -21,  -3,  16,  10,   5,  -5,  -6,  20,  10,
        11,   4, -28,  -5, -10,  25,   0,  28,  -8, -12,  -2,  18,  29,
       -29,   9, -26,   8,   0,  12, -10,  29, -27, -24,  -9, -27,  17,
        17,  12,  -3,   4,  -8,   3,   3,  -2,  13, -13, -15,  11,  16,
       -10, -22, -30, -30,  29, -24, -18, -30,   8,   1,   1,  15,  -3,
        -6,  12, -13,  11,  -8,   5,  -4,  -1,  -9, -14,  23,  28,   6,
        26,  30,  -8, -32, -29,  -3]


def data_callback(mode, filepath, tile):
    global data_received
    global data
    global channel_samples

    if mode == "burst_channel":
        channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = channel_file.read_data(channels=range(512),  # List of channels to read (not use in raw case)
                                               antennas=range(16),
                                               polarizations=[0, 1],
                                               n_samples=channel_samples)
    data_received = True


class TestPfb():
    def __init__(self, tpm_config, logger):
        self._logger = logger
        self._tpm_config = tpm_config
        self._antennas_per_tile = tpm_config['test_config']['antennas_per_tile']
        self._pfb_nof_channels = tpm_config['test_config']['pfb_nof_channels']
        self._channel_width = float(tpm_config['test_config']['total_bandwidth']) / \
                              tpm_config['test_config']['pfb_nof_channels']
        self._filter_response = np.zeros((512, 32, 2), dtype=np.int8)

    def clean_up(self, tile):
        # tf.disable_test_generator_and_pattern(tile)
        daq.stop_daq()
        del tile

    def read_filter_name(self, tile):
        if not tile.tpm.has_register('fpga1.dsp_regfile.polyphase_filter_name_0'):
            return ""
        ba = tile.tpm.memory_map['fpga1.dsp_regfile.polyphase_filter_name_0'].address
        mem = tile.tpm.read_address(ba, 8)
        txt = ""
        for n in range(8):
            hex_str = format(mem[n], 'x')
            bytes_object = bytes.fromhex(hex_str)
            txt += bytes_object.decode("ASCII")
        txt = txt.replace(" ", "")
        self._logger.info("Implemented filter is " + txt)
        return txt

    def read_pfb_response(self, filter_file, conjugate=False):
        self._logger.info("Reading filter response file " + filter_file)
        if not os.path.isfile(filter_file):
            return False

        pfb_response = open(filter_file, "r")

        idx = 0
        value_list = []
        for line in pfb_response:
            line = re.sub("\t", " ", line)
            line = re.sub("\s+", " ", line)
            line = line.lstrip()
            value_list = line.split(" ")
            self._filter_response[idx % 512, idx // 512, 0] = int(value_list[1])
            self._filter_response[idx % 512, idx // 512, 1] = int(value_list[2])
            if conjugate:
                self._filter_response[idx % 512, idx // 512, 1] *= -1
            idx += 1
            self._filter_response[idx % 512, idx // 512, 0] = int(value_list[3])
            self._filter_response[idx % 512, idx // 512, 1] = int(value_list[4])
            if conjugate:
                self._filter_response[idx % 512, idx // 512, 1] *= -1
            idx += 1
        return True

    def check_response(self, channel):
        global data

        a = 0
        p = 0
        for d in range(32):
            sequence_found = 1
            for n in range(32):
                if abs(int(self._filter_response[channel, (n + d) % 32, 0]) - int(data[channel, a, p, n][0])) > 1 or \
                   abs(int(self._filter_response[channel, (n + d) % 32, 1]) - int(data[channel, a, p, n][1])) > 1:
                    sequence_found = 0
            if sequence_found == 1:
                return True
        return False

    def execute(self, iterations=1, conjugate=False, user_response_file=""):
        global data_received
        global data
        global data_pattern
        global channel_samples

        temp_dir = "./temp_daq_test"
        data_received = False

        tf.remove_hdf5_files(temp_dir)

        # Connect to tile (and do whatever is required)
        tile = Tile(ip=self._tpm_config['single_tpm_config']['ip'], port=self._tpm_config['single_tpm_config']['port'])
        tile.connect()

        filter_name = self.read_filter_name(tile)
        if filter_name == "":
            self._logger.error("Running FPGA firmware does not support PFB test!")
            return 1
        filter_file = "pfb_response_" + filter_name + ".txt"
        if user_response_file != "":
            filter_file = user_response_file
        if not self.read_pfb_response(filter_file, conjugate):
            self._logger.error("Response file " + filter_file + " not found!")
            return 1

        # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
        # I'll change this to make it nicer
        daq_config = {
                      'receiver_interface': self._tpm_config['eth_if'],  # CHANGE THIS if required
                      'directory': temp_dir,  # CHANGE THIS if required
                      'nof_beam_channels': 384,
                      'nof_beam_samples': 32,
                      'nof_channel_samples': channel_samples,
                      'receiver_frame_size': 9000
                     }

        # Configure the DAQ receiver and start receiving data
        daq.populate_configuration(daq_config)
        daq.initialise_daq()

        daq.start_channel_data_consumer(callback=data_callback)

        tile.set_channeliser_truncation(0)
        tf.set_delay(tile, [0]*32)

        #data_pattern = range(1024)
        pattern = data_pattern
        tf.set_pattern(tile, "jesd", pattern, [0]*4*32, start=True, shift=0)

        time.sleep(1)

        for i in range(iterations):

            tf.remove_hdf5_files(temp_dir)
            data_received = False
            tile.send_channelised_data(channel_samples)

            while not data_received:
                time.sleep(0.1)

            #tf.stop_pattern(tile, "jesd")

            ch, ant, pol, sam = data.shape
            for c in range(ch):
                if not self.check_response(c):
                    self._logger.error("Test channel " + str(c) + " Error")
                    self._logger.error("Incorrect PFB response found!")
                    return 1

            self._logger.info("Test Iteration %i PASSED!" % (i + 1))
                #self._logger.info("Channel " + str(c) + " PASSED!")


        self._logger.info("Test PASSED!")
        self.clean_up(tile)
        return 0


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-i", "--iterations", action="store", dest="iterations",
                      default="1", help="Iterations [default: 1]")
    parser.add_option("-f", action="store", dest="response_file",
                      default="", help="Use specified response file [default: Auto_detected]")
    parser.add_option("-c", "--conjugate", action="store_true", dest="conjugate",
                      default=False, help="Conjugate expected values [default: False]")
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_channelizer.log',
                        filemode='w')
    # define a Handler which writes INFO messages or higher to the sys.stderr
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    # set a format which is simpler for console use
    formatter = logging.Formatter(logging_format)
    # tell the handler to use this format
    console.setFormatter(formatter)
    # add the handler to the root logger
    logging.getLogger('').addHandler(console)

    test_logger = logging.getLogger('TEST_CHANNEL')

    test_inst = TestPfb(tpm_config, test_logger)
    test_inst.execute(int(conf.iterations), conf.conjugate, conf.response_file)
