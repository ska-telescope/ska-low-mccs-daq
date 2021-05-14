# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile_wrapper import Tile
from pyaavs import station
from config_manager import ConfigManager

# Import required persisters
from pydaq.persisters import *

from sys import stdout
import numpy as np
import test_functions as tf
import test_requirements as tr
import os.path
import logging
import random
import math
import time

data_received = False
beam_int_data_received = False
channel_int_data_received = False
data = []
channel_int_data = []
beam_int_data = []
nof_tiles = 1
nof_antennas_per_tile = 16
tiles_processed = None


def integrated_sample_calc(data_re, data_im, integration_length, round_bits, max_width):
    power = data_re ** 2 + data_im ** 2
    accumulator = power * integration_length
    round = tf.s_round(accumulator, round_bits, max_width)
    return round


def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global nof_antennas_per_tile
    global tiles_processed
    global data_received
    global data

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    # if mode == "burst_raw":
    #     raw_file = RawFormatFileManager(root_path=os.path.dirname(filepath))
    #     data, timestamps = raw_file.read_data(antennas=range(16),  # List of channels to read (not use in raw case)
    #                                        polarizations=[0, 1],
    #                                        n_samples=32*1024)
    if mode == "burst_raw":
        tiles_processed[tile] = 1
        if np.all(tiles_processed >= 1):
            data = np.zeros((nof_tiles * nof_antennas_per_tile, 2, 32 * 1024), dtype=np.int8)
            raw_file = RawFormatFileManager(root_path=os.path.dirname(filepath))
            for tile_id in list(range(nof_tiles)):
                tile_data, timestamps = raw_file.read_data(antennas=range(nof_antennas_per_tile),
                                                           polarizations=[0, 1],
                                                           n_samples=32 * 1024,
                                                           tile_id=tile_id)
                data[nof_antennas_per_tile * tile_id:nof_antennas_per_tile * (tile_id + 1), :, :] = tile_data
            data_received = True

    # if mode == "burst_channel":
    #     channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath))
    #     data, timestamps = channel_file.read_data(channels=range(512),  # List of channels to read (not use in raw case)
    #                                            antennas=range(16),
    #                                            polarizations=[0, 1],
    #                                            n_samples=128)
    if mode == "burst_channel":
        tiles_processed[tile] = 1
        if np.all(tiles_processed >= 1):
            data = np.zeros((512, nof_tiles * nof_antennas_per_tile, 2, 128, 2), dtype=np.int8)
            channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath))
            for tile_id in list(range(nof_tiles)):
                tile_data, timestamps = channel_file.read_data(channels=range(512),  # List of channels to read (not use in raw case)
                                                               antennas=range(16),
                                                               polarizations=[0, 1],
                                                               n_samples=128,
                                                               tile_id=tile_id)
                data[:, tile_id * nof_antennas_per_tile: (tile_id + 1) * nof_antennas_per_tile, :, :, 0] = tile_data['real']
                data[:, tile_id * nof_antennas_per_tile: (tile_id + 1) * nof_antennas_per_tile, :, :, 1] = tile_data['imag']
            data_received = True


    if mode == "burst_beam":
        tiles_processed[tile] = 1
        if np.all(tiles_processed >= 1):
            data = np.zeros((nof_tiles, 2, 384, 32, 2), dtype=np.int16)
            beam_file = BeamFormatFileManager(root_path=os.path.dirname(filepath))
            for tile_id in list(range(nof_tiles)):
                tile_data, timestamps = beam_file.read_data(channels=range(384),  # List of channels to read (not use in raw case)
                                                            polarizations=[0, 1],
                                                            n_samples=32,
                                                            tile_id=tile_id)
                data[tile_id, :, :, :, 0] = tile_data['real'][:, :, :, 0]
                data[tile_id, :, :, :, 1] = tile_data['imag'][:, :, :, 0]
            data_received = True


def integrated_data_callback(mode, filepath, tile):

    global channel_int_tiles_processed
    global channel_int_data_received
    global channel_int_data
    global beam_int_tiles_processed
    global beam_int_data_received
    global beam_int_data

    if mode == "integrated_channel":
        channel_int_tiles_processed[tile] = 1
        if np.all(channel_int_tiles_processed >= 1):
            channel_int_data = np.zeros((512, nof_tiles * nof_antennas_per_tile, 2, 1), dtype=np.uint32)
            channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath), daq_mode=FileDAQModes.Integrated)
            for tile_id in list(range(nof_tiles)):
                tile_data, timestamps = channel_file.read_data(antennas=range(16),
                                                               polarizations=[0, 1],
                                                               n_samples=1,
                                                               tile_id=tile_id)
                channel_int_data[:, tile_id * nof_antennas_per_tile: (tile_id + 1) * nof_antennas_per_tile, :, :] = tile_data
            channel_int_data_received = True

    if mode == "integrated_beam":
        beam_int_tiles_processed[tile] = 1
        if np.all(beam_int_tiles_processed >= 1):
            beam_int_data = np.zeros((2, 384, nof_tiles, 1), dtype=np.uint32)
            beam_file = BeamFormatFileManager(root_path=os.path.dirname(filepath), daq_mode=FileDAQModes.Integrated)
            for tile_id in list(range(nof_tiles)):
                tile_data, timestamps = beam_file.read_data(channels=range(384),
                                                            polarizations=[0, 1],
                                                            n_samples=1,
                                                            tile_id=tile_id)
                beam_int_data[:, :, tile_id, :] = tile_data[:, :, 0, :]
            beam_int_data_received = True

class TestDaq():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config

    def clean_up(self, test_station):
        daq.stop_daq()
        for tile in test_station.tiles:
            tf.disable_test_generator_and_pattern(tile)

    def check_raw(self, pattern, adders, data, raw_data_synchronised):
        ant, pol, sam = data.shape
        if raw_data_synchronised == 1:
            sam = int(sam / 8)
        for a in range(ant):
            for p in range(pol):
                for i in range(sam):
                    if i % 864 == 0:
                        sample_idx = 0
                    signal_idx = ((a % 16) * 2 + p)
                    exp = pattern[sample_idx] + adders[signal_idx]
                    if tf.signed(exp) != data[a, p, i]:
                        self._logger.error("Data Error!")
                        self._logger.error("Antenna: " + str(a))
                        self._logger.error("Polarization: " + str(p))
                        self._logger.error("Sample index: " + str(i))
                        self._logger.error("Expected data: " + str(tf.signed(exp)))
                        self._logger.error("Received data: " + str(data[a, p, i]))
                        return 1
                    else:
                        sample_idx += 1
        return 0

    def check_channel(self, pattern, adders, data):
        ch, ant, pol, samples, _ = data.shape
        for c in range(ch):
            for a in range(ant):
                for p in range(pol):
                    sample_idx = 2 * c
                    signal_idx = ((a % 16) * 2 + p)
                    exp_re = pattern[sample_idx] + adders[signal_idx]
                    exp_im = pattern[sample_idx + 1] + adders[signal_idx]
                    exp = (tf.signed(exp_re), tf.signed(exp_im))
                    for i in range(samples):
                        if exp[0] != data[c, a, p, i, 0] or exp[1] != data[c, a, p, i, 1]:
                            self._logger.error("Data Error!")
                            self._logger.error("Frequency Channel: " + str(c))
                            self._logger.error("Antenna: " + str(a))
                            self._logger.error("Polarization: " + str(p))
                            self._logger.error("Sample index: " + str(i))
                            self._logger.error("Expected data: " + str(exp))
                            self._logger.error("Received data: " + str(data[c, a, p, i, :]))
                            return 1
        return 0

    def check_beam(self, pattern, adders, data):
        tile, pol, ch, sam, _ = data.shape
        for t in range(tile):
            for c in range(ch):
                for p in range(pol):
                    sample_idx = int(c / 2) * 4 + 2 * p
                    signal_idx = 16 * (c % 2)
                    exp_re = (pattern[sample_idx] + adders[signal_idx]) * 16
                    exp_im = (pattern[sample_idx + 1] + adders[signal_idx]) * 16
                    exp = (tf.signed(exp_re, 12, 16), tf.signed(exp_im, 12, 16))
                    for s in range(sam):
                        if exp[0] != data[t, p, c, s, 0] or exp[1] != data[t, p, c, s, 1]:
                            self._logger.error("Data Error!")
                            self._logger.error("Tile: " + str(t))
                            self._logger.error("Frequency Channel: " + str(c))
                            self._logger.error("Polarization: " + str(p))
                            self._logger.error("Sample index: " + str(s))
                            self._logger.error("Expected data real: " + str(exp[0]))
                            self._logger.error("Received data real: " + str(data[t, p, c, s, 0]))
                            self._logger.error("Expected data imag: " + str(exp[1]))
                            self._logger.error("Received data imag: " + str(data[t, p, c, s, 1]))
                            return 1
        return 0

    def check_integrated_channel(self, pattern, adders, data, integration_length, accumulator_width, round_bits):
        ch, ant, pol, sam = data.shape
        for c in range(ch):
            for a in range(ant):
                for p in range(pol):
                    sample_idx = 2 * c
                    signal_idx = ((a % 16) * 2 + p)
                    exp_re = pattern[sample_idx] + adders[signal_idx]
                    exp_im = pattern[sample_idx + 1] + adders[signal_idx]
                    exp = integrated_sample_calc(tf.signed(exp_re), tf.signed(exp_im), integration_length, round_bits, accumulator_width)
                    for i in range(1):  # range(sam):
                        if exp != data[c, a, p, i]:
                            self._logger.error("Data Error!")
                            self._logger.error("Frequency Channel: " + str(c))
                            self._logger.error("Antenna: " + str(a))
                            self._logger.error("Polarization: " + str(p))
                            self._logger.error("Sample index: " + str(i))
                            self._logger.error("Expected data: " + str(exp))
                            self._logger.error("Expected data re: " + str(tf.signed(exp_re)))
                            self._logger.error("Received data im: " + str(tf.signed(exp_im)))
                            self._logger.error("Received data: " + str(data[c, a, p, i]))
                            return 1
        return 0

    def check_integrated_beam(self, pattern, adders, data, integration_length, accumulator_width, round_bits):
        pol, ch, tile, sam = data.shape
        for c in range(ch):
            for t in range(tile):
                for p in range(pol):
                    sample_idx = int(c / 2) * 4 + 2 * p
                    signal_idx = 16 * (c % 2)
                    exp_re = (pattern[sample_idx] + adders[signal_idx]) * 16
                    exp_im = (pattern[sample_idx + 1] + adders[signal_idx]) * 16
                    exp_re_sign = tf.signed(exp_re, 12, 12)
                    exp_im_sign = tf.signed(exp_im, 12, 12)
                    exp = integrated_sample_calc(exp_re_sign, exp_im_sign, integration_length, round_bits,
                                                 accumulator_width)
                    for i in range(1):  # range(sam):
                        if exp != data[p, c, t, i]:
                            self._logger.error("Data Error!")
                            self._logger.error("Frequency Channel: " + str(c))
                            self._logger.error("Tile: " + str(t))
                            self._logger.error("Polarization: " + str(p))
                            self._logger.error("Sample index: " + str(i))
                            self._logger.error("Expected data: " + str(exp))
                            self._logger.error("Expected data re: " + str(exp_re) + " " + hex(exp_re))
                            self._logger.error("Received data im: " + str(exp_im) + " " + hex(exp_im))
                            self._logger.error("Received data: " + str(data[p, c, t, i]))
                            return 1
        return 0

    def execute(self, test_type="all"):
        global tiles_processed
        global data_received
        global data

        global channel_int_tiles_processed
        global channel_int_data_received
        global channel_int_data

        global beam_int_tiles_processed
        global beam_int_data_received
        global beam_int_data

        global nof_tiles
        global nof_antennas_per_tile

        # Connect to tile (and do whatever is required)
        test_station = station.Station(self._station_config)
        test_station.connect()
        tiles = test_station.tiles
        nof_tiles = len(tiles)
        nof_antennas_per_tile = self._station_config['test_config']['antennas_per_tile']

        if not tr.check_eth(self._station_config, "lmc", 1500, self._logger):
            return 1
        if not tr.check_eth(self._station_config, "integrated", 1800, self._logger):
            return 1
        self._logger.info("Using Ethernet Interface %s" % self._station_config['eth_if'])

        # Connect to tile (and do whatever is required)
        # tile = Tile(ip=self._tpm_config['single_tpm_config']['ip'], port=self._tpm_config['single_tpm_config']['port'])
        # tile.connect()

        temp_dir = "./temp_daq_test"
        tiles_processed = np.zeros(nof_tiles)

        # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
        daq_config = {
            'receiver_interface': self._station_config['eth_if'],  # CHANGE THIS if required
            'directory': temp_dir,  # CHANGE THIS if required
            'nof_beam_channels': 384,
            'nof_beam_samples': 42,
            'receiver_frame_size': 9000,
            'nof_tiles': len(tiles)
        }

        # Configure the DAQ receiver and start receiving data
        daq.populate_configuration(daq_config)
        daq.initialise_daq()

        # Start whichever consumer is required and provide callback
        daq.start_raw_data_consumer(callback=data_callback)
        daq.start_channel_data_consumer(callback=data_callback)
        daq.start_beam_data_consumer(callback=data_callback)

        test_pattern = list(range(1024))
        #
        # raw data
        #
        tf.remove_hdf5_files(temp_dir)
        raw_data_synchronised = 0
        if test_type in ["all", "raw", "non-integrated"]:
            tf.remove_hdf5_files(temp_dir)
            for i in range(4):
                # Set data received to False
                data_received = False
                tiles_processed = np.zeros(nof_tiles)

                # Start pattern generator
                for n in range(1024):
                    if i % 2 == 0:
                        test_pattern[n] = n
                    else:
                        test_pattern[n] = random.randrange(0, 255, 1)

                test_adders = list(range(32))
                for tile in tiles:
                    tf.set_pattern(tile, "jesd", test_pattern, test_adders, start=True)
                # Send data from station
                test_station.send_raw_data()

                # Wait for data to be received
                while not data_received:
                    time.sleep(0.1)

                if self.check_raw(test_pattern, test_adders, data, raw_data_synchronised) > 0:
                    self.clean_up(test_station)
                    return 1

                self._logger.info("Raw ADC data iteration %d PASSED!" % (i+1))
            #
            # raw data synchronised
            #
            tf.remove_hdf5_files(temp_dir)
            raw_data_synchronised = 1
            for i in range(4):
                # Set data received to False
                data_received = False
                tiles_processed = np.zeros(nof_tiles)

                # Start pattern generator
                for n in range(1024):
                    if i % 2 == 0:
                        test_pattern[n] = n
                    else:
                        test_pattern[n] = random.randrange(0, 255, 1)

                test_adders = list(range(32))
                for tile in tiles:
                    tf.set_pattern(tile, "jesd", test_pattern, test_adders, start=True)
                # Send data from station
                test_station.send_raw_data_synchronised()

                # Wait for data to be received
                while not data_received:
                    time.sleep(0.1)

                if self.check_raw(test_pattern, test_adders, data, raw_data_synchronised) > 0:
                    self.clean_up(test_station)
                    return 1

                self._logger.info("Raw ADC data synchronized iteration %d PASSED!" %(i+1))
        #
        # channel data
        #
        if test_type in ["all", "channel", "non-integrated"]:
            tf.remove_hdf5_files(temp_dir)
            for i in range(4):
                # Set data received to False
                data_received = False
                tiles_processed = np.zeros(nof_tiles)

                # Start pattern generator
                for n in range(1024):
                    if i % 2 == 0:
                        test_pattern[n] = n
                    else:
                        test_pattern[n] = random.randrange(0, 255, 1)

                test_adders = range(32)
                for tile in tiles:
                    tf.set_pattern(tile, "channel", test_pattern, test_adders, start=True)
                # Send data from station
                test_station.send_channelised_data(1024)

                # Wait for data to be received
                while not data_received:
                    time.sleep(0.1)

                if self.check_channel(test_pattern, test_adders, data) > 0:
                    self.clean_up(test_station)
                    return 1

                self._logger.info("Channel data iteration %d PASSED!" % (i + 1))
        #
        # beam data
        #
        if test_type in ["all", "beam", "non-integrated"]:
            tf.remove_hdf5_files(temp_dir)
            for i in range(4):
                # Set data received to False
                data_received = False
                tiles_processed = np.zeros(nof_tiles)

                # Start pattern generator
                for n in range(1024):
                    if i % 2 == 0:
                        test_pattern[n] = n
                    else:
                        test_pattern[n] = random.randrange(0, 255, 1)

                test_adders = list(range(16)) + list(range(2, 16 + 2))
                for tile in tiles:
                    tf.set_pattern(tile, "beamf", test_pattern, test_adders, start=True)
                time.sleep(1)
                # Send data from station
                test_station.send_beam_data()

                # Wait for data to be received
                while not data_received:
                    time.sleep(0.1)

                if self.check_beam(test_pattern, test_adders, data) > 0:
                    self.clean_up(test_station)
                    return 1

                self._logger.info("Tile beam data iteration %d PASSED!" % (i + 1))

        if test_type in ["all", "raw", "channel", "beam", "non-integrated"]:
            daq.stop_daq()

        if test_type in ["all", "integrated"]:
            self._logger.info("Checking integrated data format now...")

            daq_config = {
                'receiver_interface': self._station_config['eth_if'],  # CHANGE THIS if required
                'directory': temp_dir,  # CHANGE THIS if required
                'nof_beam_channels': 384,
                'nof_beam_samples': 1,
                'nof_tiles': len(tiles)
            }

            test_station = station.Station(self._station_config)
            test_station.connect()
            # for n, _tile in enumerate(test_station.tiles):
            #     if self._station_config['tiles'][n] != self._station_config['single_tpm_config']['ip']:
            #         self._logger.info("Stopping integrated data on Tile %s" % self._station_config['tiles'][n])
            #         _tile.stop_integrated_data()

            if not tr.check_integrated_data_enabled(test_station, "channel", self._logger) or \
               not tr.check_integrated_data_enabled(test_station, "beamf", self._logger):
                return 1

            tile = test_station.tiles[0]

            channel_integration_length = tile['fpga1.lmc_integrated_gen.channel_integration_length']
            channel_accumulator_width = tile['fpga1.lmc_integrated_gen.channel_accumulator_width']
            channel_round_bits = tile['fpga1.lmc_integrated_gen.channel_scaling_factor']

            beamf_integration_length = tile['fpga1.lmc_integrated_gen.beamf_integration_length']
            beamf_accumulator_width = tile['fpga1.lmc_integrated_gen.beamf_accumulator_width']
            beamf_round_bits = tile['fpga1.lmc_integrated_gen.beamf_scaling_factor']

            daq.populate_configuration(daq_config)
            daq.initialise_daq()

            for i in range(2):
                # Start pattern generator
                for n in range(1024):
                    if i % 2 == 0:
                        test_pattern[n] = n
                    else:
                        test_pattern[n] = random.randrange(0, 255, 1)

                channel_test_adders = list(range(32))
                beam_test_adders = list(range(16)) + list(range(2, 16 + 2))
                for tile in tiles:
                    tf.set_pattern(tile, "channel", test_pattern, channel_test_adders, start=True)
                    tf.set_pattern(tile, "beamf", test_pattern, beam_test_adders, start=True)

                self._logger.info("Sleeping for " + str(channel_integration_length * 1.08e-6 + 0.5) + " seconds...")
                time.sleep(channel_integration_length * 1.08e-6 + 0.5)

                # Set data received to False
                tf.remove_hdf5_files(temp_dir)

                channel_int_data_received = False
                channel_int_tiles_processed = np.zeros(nof_tiles)
                beam_int_data_received = False
                beam_int_tiles_processed = np.zeros(nof_tiles)
                beam_done = False
                channel_done = False

                daq.start_integrated_channel_data_consumer(callback=integrated_data_callback)
                daq.start_integrated_beam_data_consumer(callback=integrated_data_callback)

                while not beam_done or not channel_done:
                    if not channel_done and channel_int_data_received:
                        daq.stop_integrated_channel_data_consumer()
                        channel_done = True
                        if self.check_integrated_channel(test_pattern, channel_test_adders, channel_int_data,
                                                         channel_integration_length, channel_accumulator_width,
                                                         channel_round_bits) == 0:
                            self._logger.info("Channel integrated data iteration %d PASSED!" % (i + 1))
                        else:
                            self.clean_up(test_station)
                            return 1
                    if not beam_done and beam_int_data_received:
                        daq.stop_integrated_beam_data_consumer()
                        beam_done = True
                        if self.check_integrated_beam(test_pattern, beam_test_adders, beam_int_data,
                                                      beamf_integration_length, beamf_accumulator_width,
                                                      beamf_round_bits) == 0:
                            self._logger.info("Tile beam integrated data iteration %d PASSED!" % (i + 1))
                        else:
                            self.clean_up(test_station)
                            return 1

                    time.sleep(0.1)

        self.clean_up(test_station)
        return 0


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("--test", action="store", dest="test_type",
                      default="all", help="Test stage [raw, channel, beam, integrated, non-integrated. default: all]")
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    station_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_daq.log',
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

    test_logger = logging.getLogger('TEST_DAQ')

    test_daq = TestDaq(station_config, test_logger)
    test_daq.execute(conf.test_type)
