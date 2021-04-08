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

import test_functions as tf
import numpy as np
import os.path
import logging
import random
import time

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
    data_received = True


class TestAdc():
    def __init__(self, tpm_config, logger):
        self._logger = logger
        self._tpm_config = tpm_config

    def clean_up(self, tile):
        daq.stop_daq()
        tf.disable_adc_test_pattern(tile, list(range(16)))
        del tile

    def check_adc_pattern(self, pattern_type, fixed_pattern):

        global data

        self._logger.debug("Checking " + pattern_type + " ADC pattern")
        if pattern_type == "fixed":
            self._logger.debug("Pattern data: ")
            for n in range(16):
                self._logger.debug(fixed_pattern[n])

        for a in range(16):
            for p in range(2):
                buffer = np.array(data[a, p, 0:32768], dtype='uint8')
                if pattern_type == "ramp":
                    seed = buffer[0]
                    for n in range(len(buffer)):
                        exp_value = (seed + n) % 256
                        if buffer[n] != exp_value:
                            self._logger.error("Error detected, ramp pattern")
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
                            self._logger.error("Buffer position: " + str(n))
                            self._logger.error("Expected value: " + str(fixed_pattern[a][(n + m) % 4]))
                            self._logger.error("Received value: " + str(buffer[n]))
                            self._logger.debug(buffer[0:128])
                            self._logger.error("ADC TEST FAILED!")
                            return 1

        self._logger.debug("Data pattern checked!\n")
        return 0

    def execute(self, iterations=8):
        global data_received
        temp_dir = "./temp_daq_test"
        data_received = False
        fixed_pattern = [[191, 254, 16, 17]] * 16

        tf.remove_hdf5_files(temp_dir)

        # Connect to tile (and do whatever is required)
        tile = Tile(ip=self._tpm_config['single_tpm_config']['ip'], port=self._tpm_config['single_tpm_config']['port'])
        tile.connect()

        self._logger.debug("Disable test and pattern generators...")
        tf.disable_test_generator_and_pattern(tile)
        self._logger.debug("Setting 0 delays...")
        tf.set_delay(tile, [0] * 32)

        time.sleep(0.2)

        iter = int(iterations)
        if iter == 0:
            return

        # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
        # I'll change this to make it nicer
        daq_config = {
            'receiver_interface': self._tpm_config['eth_if'],  # CHANGE THIS if required
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
        tf.remove_hdf5_files(temp_dir)

        self._logger.info("Executing %d test iterations" % iter)

        errors = 0
        k = 0
        while k != iter:
            pattern_type = "ramp"
            tf.enable_adc_test_pattern(tile, range(16), pattern_type)
            time.sleep(0.1)

            data_received = False
            # Send data from tile
            tile.send_raw_data()
            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            if self.check_adc_pattern(pattern_type, fixed_pattern) > 0:
                errors += 1
                break

            for n in range(16):
                fixed_pattern[n] = [random.randrange(0, 255, 1) for x in range(4)]
            pattern_type = "fixed"
            tf.enable_adc_test_pattern(tile, range(16), pattern_type, fixed_pattern)
            time.sleep(0.1)

            data_received = False
            # Send data from tile
            tile.send_raw_data()
            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            if self.check_adc_pattern(pattern_type, fixed_pattern) > 0:
                errors += 1
                break

            k += 1

            self._logger.info("Iteration %d PASSED!" % k)

        self.clean_up(tile)
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
    tpm_config = config_manager.apply_test_configuration(conf)

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

    test_adc = TestAdc(tpm_config, test_logger)
    test_adc.execute(conf.iteration)
