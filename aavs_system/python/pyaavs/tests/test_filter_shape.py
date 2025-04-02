# test filter shape
# Generates a tone with frequency sweeping across first channel specified, using internal tone
# generator. Phase is set to random values for differetn antennas, to increase sampling
# and decrease noise.
# Then acquires channelised samples and computes the digital power in channels
# comprised between first and last. 
# Stores the result on the log file, which must be edited and processed to retrieve the 
# total power data. 
#
# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile import Tile
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

data = []
data_received = False
channel_samples = 1024


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


class TestChannelizer():
    def __init__(self, tpm_config, logger):
        self._logger = logger
        self._tpm_config = tpm_config
        self._antennas_per_tile = tpm_config['test_config']['antennas_per_tile']
        self._pfb_nof_channels = tpm_config['test_config']['pfb_nof_channels']
        self._channel_width = float(tpm_config['test_config']['total_bandwidth']) / \
                              tpm_config['test_config']['pfb_nof_channels']

    def clean_up(self, tile):
        #tf.disable_test_generator_and_pattern(tile)
        daq.stop_daq()
        del tile

    def execute(self, points=1, first_channel=100, last_channel=108, truncation=4):
        global data_received
        global data
        global channel_samples

        temp_dir = "./temp_daq_test"
        data_received = False

        tf.remove_hdf5_files(temp_dir)

        # Connect to tile (and do whatever is required)
        tile = Tile(ip=self._tpm_config['single_tpm_config']['ip'], port=self._tpm_config['single_tpm_config']['port'])
        tile.connect()

        # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
        # I'll change this to make it nicer
        daq_config = {
                      'receiver_interface': self._tpm_config['eth_if']['lmc'],
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

        #tf.disable_test_generator_and_pattern(tile)
        tile.disable_all_adcs()
        tile.test_generator_input_select(0xFFFFFFFF)
        tile.test_generator_set_noise(0.01)
        tile.test_generator_set_tone(0, 0.0, 0.0)

        tile.set_channeliser_truncation(truncation)

        points_per_channel = int(points)
        channels = range(int(first_channel), int(last_channel) + 1)
        nof_channels = int(last_channel) + 1 - int(first_channel)
        delays = [0] + [random.randrange(0, 4, 1) for x in range(31)]
        tf.set_delay(tile, delays)

        channel = int(first_channel)
        for point in range(points_per_channel+1):
            frequency = channel * self._channel_width - self._channel_width / 2 + self._channel_width / (points_per_channel + 1) * (point + 1)
            tile.test_generator_set_tone(0, frequency, 1.0)
            self._logger .info("setting frequency: " + str(frequency) + " Hz, point " + str(point))
            time.sleep(0.2)

            tf.remove_hdf5_files(temp_dir)
            data_received = False
            tile.send_channelised_data(channel_samples)

            while not data_received:
                time.sleep(0.1)

            ch, ant, pol, sam = data.shape
            channel_power = np.zeros(nof_channels)

            for c in channels:
                tp = 0
                for a in range(ant):
                    for i in range(sam):
                        ref_channel_value = (data[c, a, 0, i][0] + data[c, a, 0, i][1]*1j)
                        tp = tp + ref_channel_value * np.conj(ref_channel_value)
                channel_power[c-channel] = tp

            self._logger.info("Channel power " + str(channel_power))

        self.clean_up(tile)
        return 0

if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-p", "--points", action="store", dest="points",
                      default="128", help="Frequency points per channel [default: 128]")
    parser.add_option("-f", "--first", action="store", dest="first_channel",
                      default="128", help="First frequency channel [default: 128]")
    parser.add_option("-l", "--last", action="store", dest="last_channel",
                      default="135", help="Last frequency channel [default: 135]")
    parser.add_option("-t", "--truncation", action="store", dest="truncation",
                      default="4", help="Channelizer truncation [default: 4]")
    parser.add_option("-s", "--channel_samples", action="store", dest="channel_samples",
            default="1024", help="Channelizer samples [default: 1024, max: 32768]")
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)

    channel_samples = int(conf.channel_samples)
    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_channelizer.log',
                        filemode='a')
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

    test_inst = TestChannelizer(tpm_config, test_logger)
    test_inst.execute(int(conf.points), int(conf.first_channel), int(conf.last_channel), int(conf.truncation))
