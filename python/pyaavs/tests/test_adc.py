# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile_wrapper import Tile
from pyaavs import station
from config_manager import ConfigManager

# Import required persisters
from pydaq.persisters.aavs_file import FileModes
from pydaq.persisters.raw import RawFormatFileManager
from pydaq.persisters.channel import ChannelFormatFileManager
from pydaq.persisters.beam import BeamFormatFileManager
from pydaq.persisters import *

from builtins import input
from sys import stdout

import test_requirements as tr
import test_functions as tf
import numpy as np
import os.path
import logging
import random
import time

nof_tiles = 1
nof_antennas = 16
tiles_processed = None

def data_callback(mode, filepath, tile):
    global data
    global nof_tiles
    global data_received
    global tiles_processed

    if mode == "burst_raw":
        tiles_processed[tile] = 1
        if np.all(tiles_processed >= 1):
            data = np.zeros((nof_tiles * nof_antennas, 2, 32 * 1024), dtype=np.int8)
            raw_file = RawFormatFileManager(root_path=os.path.dirname(filepath))
            for tile_id in list(range(nof_tiles)):
                tile_data, timestamps = raw_file.read_data(antennas=range(nof_antennas),
                                                           polarizations=[0, 1],
                                                           n_samples=32 * 1024,
                                                           tile_id=tile_id)
                data[nof_antennas * tile_id:nof_antennas * (tile_id + 1), :, :] = tile_data
            data_received = True


class TestAdc():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config

    def clean_up(self, test_station):
        daq.stop_daq()
        for tile in test_station.tiles:
            tf.disable_adc_test_pattern(tile, list(range(16)))

    def check_adc_pattern(self, pattern_type, fixed_pattern):

        global data

        self._logger.debug("Checking " + pattern_type + " ADC pattern")
        # if pattern_type == "fixed":
        #     self._logger.debug("Pattern data: ")
        #     for n in range(16):
        #         self._logger.debug(fixed_pattern[n])

        for a in range(data.shape[0]):
            for p in range(2):
                buffer = np.array(data[a, p, 0:32768], dtype='uint8')
                if pattern_type == "ramp":
                    seed = buffer[0]
                    for n in range(len(buffer)):
                        exp_value = (seed + n) % 256
                        if buffer[n] != exp_value:
                            self._logger.error("Error detected, ramp pattern")
                            self._logger.error("Antenna index: " + str(a))
                            self._logger.error("Buffer position: " + str(n))
                            self._logger.error("Expected value: " + str(exp_value))
                            self._logger.error("Received value: " + str(buffer[n]))
                            self._logger.debug(buffer[0:128])
                            self._logger.error("ADC TEST FAILED!")
                            return 1
                if pattern_type == "fixed":
                    for n in range(4):
                        seed = n
                        for m in range(4):
                            if buffer[m] != fixed_pattern[a][(m + n) % 4]:
                                seed = -1
                        if seed >= 0:
                            break
                    for n in range(0, len(buffer)):
                        exp_value = fixed_pattern[a][(seed + n) % 4]
                        if buffer[n] != exp_value:
                            self._logger.error("Error detected, fixed pattern")
                            self._logger.error(fixed_pattern[a])
                            self._logger.error("Antenna index: " + str(a))
                            self._logger.error("Buffer position: " + str(n))
                            self._logger.error("Expected value: " + str(fixed_pattern[a][(n + m) % 4]))
                            self._logger.error("Received value: " + str(buffer[n]))
                            self._logger.debug(buffer[0:128])
                            self._logger.error("ADC TEST FAILED!")
                            return 1

        self._logger.info("Data pattern check OK!")
        return 0

    def execute(self, iterations=4, single_tpm_id=0):
        global tiles_processed
        global data_received
        global nof_tiles
        global nof_antennas

        # Connect to tile (and do whatever is required)
        test_station = station.Station(self._station_config)
        test_station.connect()

        if single_tpm_id >= 0:
            if single_tpm_id >= len(test_station.tiles):
                self._logger.error("Required TPM Id for single TPM test does not belong to station.")
                return 1
            else:
                self._logger.info("Executing test on tile %d" % single_tpm_id)
                dut = test_station.tiles[single_tpm_id]
                tiles = [test_station.tiles[single_tpm_id]]
        else:
            dut = test_station
            tiles = test_station.tiles
        nof_tiles = len(tiles)

        nof_antennas = self._station_config['test_config']['antennas_per_tile']

        if not tr.check_eth(self._station_config, "lmc", 1500, self._logger):
            return 1
        self._logger.info("Using Ethernet Interface %s" % self._station_config['eth_if'])

        temp_dir = "./temp_daq_test"
        data_received = False
        fixed_pattern = [[191, 254, 16, 17]] * (nof_antennas * nof_tiles)

        tf.remove_hdf5_files(temp_dir)

        self._logger.debug("Disable test and pattern generators...")
        self._logger.debug("Setting 0 delays...")
        for tile in tiles:
            tf.disable_test_generator_and_pattern(tile)
            tf.set_delay(tile, [0] * 32)
        time.sleep(0.2)

        iter = int(iterations)
        if iter == 0:
            return

        # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
        # I'll change this to make it nicer
        daq_config = {
            'receiver_interface': self._station_config['eth_if'],  # CHANGE THIS if required
            'receiver_ports': str(self._station_config['network']['lmc']['lmc_port']),
            'directory': temp_dir,  # CHANGE THIS if required
            'nof_raw_samples': 32768,
            'nof_beam_channels': 384,
            'nof_beam_samples': 32,
            'nof_antennas': 16,
            'receiver_frame_size': 9000,
            'nof_tiles': len(tiles)
        }

        # Configure the DAQ receiver and start receiving data
        daq.populate_configuration(daq_config)
        daq.initialise_daq()

        # Start whichever consumer is required and provide callback
        daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
        #
        # raw data synchronised
        #
        tf.remove_hdf5_files(temp_dir)

        self._logger.info("Executing %d test iterations" % iter)

        errors = 0
        k = 0
        while k != iter:
            pattern_type = "ramp"
            for tile in tiles:
                tf.enable_adc_test_pattern(tile, range(nof_antennas), pattern_type)
            time.sleep(0.1)

            data_received = False
            tiles_processed = np.zeros(nof_tiles)
            # Send data from tile
            dut.send_raw_data()
            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            if self.check_adc_pattern(pattern_type, fixed_pattern) > 0:
                errors += 1
                break

            for n in range(nof_antennas * nof_tiles):
                fixed_pattern[n] = [random.randrange(0, 255, 1) for x in range(4)]
            pattern_type = "fixed"
            for tile_id, tile in enumerate(tiles):
                tf.enable_adc_test_pattern(tile, range(nof_antennas), pattern_type, fixed_pattern[nof_antennas * tile_id : nof_antennas * (tile_id + 1)])
            time.sleep(0.1)

            data_received = False
            tiles_processed = np.zeros(nof_tiles)
            # Send data from tile
            dut.send_raw_data()
            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            if self.check_adc_pattern(pattern_type, fixed_pattern) > 0:
                errors += 1
                break

            k += 1

            self._logger.info("Iteration %d PASSED!" % k)

        self.clean_up(test_station)
        return errors


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-i", "--iteration", action="store", dest="iteration",
                      default="16", help="Number of iterations [default: 16, infinite: -1]")
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    station_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_adc.log',
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

    test_logger = logging.getLogger('TEST_ADC')

    test_adc = TestAdc(station_config, test_logger)
    test_adc.execute(conf.iteration)
