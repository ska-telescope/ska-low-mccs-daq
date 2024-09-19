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

data = []
data_received = False
channel_samples = 512


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
        tf.disable_test_generator_and_pattern(tile)
        daq.stop_daq()
        del tile

    def execute(self, points=1, first_channel=100, last_channel=108):
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
                      'receiver_interface': self._tpm_config['eth_if'],  # CHANGE THIS if required
                      'receiver_ports': str(self._tpm_config['network']['lmc']['lmc_port']),
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

        tf.disable_test_generator_and_pattern(tile)
        tile['fpga1.jesd204_if.regfile_channel_disable'] = 0xFFFF
        tile['fpga2.jesd204_if.regfile_channel_disable'] = 0xFFFF
        tile.test_generator_input_select(0xFFFFFFFF)

        # TODO: Update Test to also test channeliser truncation
        tile.set_channeliser_truncation(5)

        points_per_channel = int(points)
        channels = range(int(first_channel), int(last_channel) + 1)

        for channel in channels:
            for point in range(points_per_channel):
                frequency = channel * self._channel_width - self._channel_width / 2 + self._channel_width / (points_per_channel + 1) * (point + 1)
                tile.test_generator_set_tone(0, frequency, 1.0)
                delays = [0] + [random.randrange(0, 4, 1) for x in range(31)]
                tf.set_delay(tile, delays)
                self._logger.info("setting frequency: " + str(frequency) + " Hz, point " + str(point))
                time.sleep(1)

                tf.remove_hdf5_files(temp_dir)
                data_received = False
                tile.send_channelised_data(channel_samples)

                while not data_received:
                    time.sleep(0.1)

                ref_channel_value = data[channel, 0, 0, 0][0] + data[channel, 0, 0, 0][1] * 1j
                ref_power_value = 20 * np.log10(abs(ref_channel_value))
                self._logger.info("Reference power: " + str(ref_power_value) + " dB")

                ch, ant, pol, sam = data.shape
                for i in range(16):  # range(sam):
                    ref_channel_value = data[channel, 0, 0, i][0] + data[channel, 0, 0, i][1] * 1j
                    if abs(ref_channel_value) > 0:
                        ref_power_value = 20 * np.log10(abs(ref_channel_value))
                    else:
                        ref_power_value = 0
                    ref_phase_value = np.angle(ref_channel_value, deg=True)
                    for a in range(ant):
                        for c in range(2, ch):
                            for p in range(pol):
                                channel_value = data[c, a, p, i][0] + data[c, a, p, i][1]*1j
                                if abs(channel_value):
                                    power_value = 20 * np.log10(abs(channel_value))
                                else:
                                    power_value = 0
                                phase_value = np.angle(channel_value, deg=True)
                                if c != channel:
                                    if power_value > 0.2:
                                        self._logger.error(data[:, a, p, i])
                                        self._logger.error("Test channel " + str(channel))
                                        self._logger.error("Excessive power in channel " + str(c))
                                        self._logger.error("Frequency: " + str(frequency))
                                        self._logger.error("Antenna: " + str(a))
                                        self._logger.error("Polarization: " + str(p))
                                        self._logger.error("Sample index: " + str(i))
                                        self._logger.error("Reference value: " + str(ref_channel_value))
                                        self._logger.error("Reference power " + str(ref_power_value))
                                        self._logger.error("Channel value " + str(channel_value))
                                        self._logger.error("Channel power " + str(power_value))
                                        return 1
                                else:
                                    if abs(ref_power_value - power_value) > 0.2:
                                        self._logger.error(data[:, a, p, i])
                                        self._logger.error("Test channel " + str(channel))
                                        self._logger.error("Low power in channel " + str(c))
                                        self._logger.error("Frequency: " + str(frequency))
                                        self._logger.error("Antenna: " + str(a))
                                        self._logger.error("Polarization: " + str(p))
                                        self._logger.error("Sample index: " + str(i))
                                        self._logger.error("Reference value: " + str(ref_channel_value))
                                        self._logger.error("Reference power " + str(ref_power_value))
                                        self._logger.error("Channel value " + str(channel_value))
                                        self._logger.error("Channel power " + str(power_value))
                                        return 1

                                if c == channel:
                                    ref_phase_value_360 = ref_phase_value % 360
                                    phase_value_360 = phase_value % 360
                                    applied_delay = delays[2*a+p] * 1.25e-9
                                    phase_delay = np.modf(applied_delay / (1.0 / frequency))[0]
                                    expected_phase_delay = 360 - phase_delay * 360 #360 - phase_delay * 360   # before channelizer phase inversion it was:  phase_delay*360
                                    expected_phase = (ref_phase_value_360 + expected_phase_delay) % 360
                                    diff = abs(expected_phase - phase_value_360) % 360
                                    if diff > 3 and 360-diff > 3:
                                        self._logger.error(data[:, a, p, i])
                                        self._logger.error(diff)
                                        self._logger.error("Test channel " + str(channel))
                                        self._logger.error("Excessive phase shift in channel " + str(c))
                                        self._logger.error("Frequency: " + str(frequency))
                                        self._logger.error("Antenna: " + str(a))
                                        self._logger.error("Polarization: " + str(p))
                                        self._logger.error("Sample index: " + str(i))
                                        self._logger.error("Reference value: " + str(ref_channel_value))
                                        self._logger.error("Reference phase " + str(ref_phase_value_360))
                                        self._logger.error("Channel value " + str(channel_value))
                                        self._logger.error("Channel phase " + str(phase_value_360))
                                        self._logger.error("Expected phase: " + str(expected_phase))
                                        self._logger.error("Applied delay: " + str(applied_delay))
                                        self._logger.error("Applied delay steps: " + str(delays[2*a+p]))
                                        self._logger.error("Expected phase delay: " + str(expected_phase_delay))
                                        self._logger.error("Periods delay: " + str(np.modf(applied_delay / (1.0 / frequency))[1]))
                                        return 1


            self._logger.info("Channel " + str(channel) + " PASSED!")

        self.clean_up(tile)
        return 0

if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-p", "--points", action="store", dest="points",
                      default="1", help="Frequency points per channel [default: 1]")
    parser.add_option("-f", "--first", action="store", dest="first_channel",
                      default="64", help="First frequency channel [default: 64]")
    parser.add_option("-l", "--last", action="store", dest="last_channel",
                      default="447", help="Last frequency channel [default: 383]")
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

    test_inst = TestChannelizer(tpm_config, test_logger)
    test_inst.execute(int(conf.points), int(conf.first_channel), int(conf.last_channel))
