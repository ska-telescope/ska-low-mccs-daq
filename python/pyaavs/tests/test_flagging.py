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
nof_channels = 0
tile_id = 0

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
        data, timestamps = beam_file.read_data(channels=range(nof_channels),  # List of channels to read (not use in raw case)
                                               polarizations=[0, 1],
                                               n_samples=32,
                                               tile_id=tile_id)
    data_received = True


class TestFlagging():
    def __init__(self, tpm_config, logger):
        self._logger = logger
        self._tpm_config = tpm_config
        self._channel_width = float(tpm_config['test_config']['total_bandwidth']) / \
                              tpm_config['test_config']['pfb_nof_channels']
        self._beam_start_channel = int(tpm_config['observation']['start_frequency_channel'] / self._channel_width)
        self._nof_channels = int(tpm_config['observation']['bandwidth'] / self._channel_width)

    def clean_up(self, tile):
        tf.disable_test_generator_and_pattern(tile)
        daq.stop_daq()

    def execute(self, first_channel=0, last_channel=7):
        global data_received
        global data
        global nof_channels
        global tile_id

        random.seed(0)

        temp_dir = "./temp_daq_test"
        data_received = False

        tf.remove_hdf5_files(temp_dir)

        # Connect to tile (and do whatever is required)
        tile = Tile(ip=self._tpm_config['single_tpm_config']['ip'], port=self._tpm_config['single_tpm_config']['port'])
        tile.connect()

        tile_id = tile['fpga1.dsp_regfile.config_id.tpm_id']
        nof_channels = self._nof_channels

        # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
        # I'll change this to make it nicer
        daq_config = {
            'receiver_interface': self._tpm_config['eth_if'],  # CHANGE THIS if required
            'directory': temp_dir,  # CHANGE THIS if required
            #     'nof_beam_channels': nof_channels,
            #    'nof_beam_channels': 384,
            'nof_beam_samples': 42,
            #     'receiver_frame_size': 9000
        }

        # Configure the DAQ receiver and start receiving data
        daq.populate_configuration(daq_config)
        daq.initialise_daq()

        # Start whichever consumer is required and provide callback
        daq.start_beam_data_consumer(callback=data_callback)
        self._logger.info("Sleeping 2 seconds...")
        time.sleep(2)
        #
        # preparing test
        #
        tf.disable_test_generator_and_pattern(tile)
        tf.reset_beamf_coeff(tile, gain=1.0)
        time_delays_hw = [[0.0, 0.0]] * 16
        tile.set_pointing_delay(time_delays_hw, 0.0)
        tile.load_pointing_delay()
        time.sleep(0.2)
        #
        #
        #
        errors = 0
        for c_test in range(4):  # channel
            for p_test in range(2):  # pol
                for i_test in range(2):  # imag/real
                    pattern_idx = 2 * (self._beam_start_channel + c_test) + i_test
                    pattern = [0] * 1024  # list(range(1024)) #
                    pattern[pattern_idx] = 0x80
                    if p_test == 0:
                        mask = 0xFFFE
                    else:
                        mask = 0xFFFD
                    tf.set_pattern(tile, "channel", pattern, [0] * 32, True, shift=4, zero=mask)

                    # Set data received to False
                    data_received = False
                    # Send data from tile
                    tile.send_beam_data()
                    # Wait for data to be received
                    while not data_received:
                        time.sleep(0.1)

                    for c in range(self._nof_channels):
                        for p in range(2):
                            beam_data = tf.get_beam_value(data, p, c)
                            if c == c_test:
                                if beam_data != -2**15 - 2**15*1j:
                                    errors += 1
                                    self._logger.error("Error in beamformed values, test iteration channel-pol-complex: %d-%d-%d" % (c_test, p_test, i_test))
                                    self._logger.error("                                  received channel-pol:         %d-%d" % (c, p))
                                    self._logger.error("Expecting 0x800 flagged data, received: " + str(beam_data))
                            else:
                                if beam_data != 0.0:
                                    errors += 1
                                    self._logger.error("Error in beamformed values, test iteration channel-pol-complex: %d-%d-%d" % (c_test, p_test, i_test))
                                    self._logger.error("                                  received channel-pol:         %d-%d" % (c, p))
                                    self._logger.error("Expecting 0.0 data, received: " + str(beam_data))

        tf.remove_hdf5_files(temp_dir)
        self.clean_up(tile)
        if errors == 0:
            self._logger.info("Test PASSED!")
        else:
            self._logger.info("Test FAILED!")
        return errors


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-f", "--first", action="store", dest="first_channel",
                      default="0", help="First frequency channel [default: 0]")
    parser.add_option("-l", "--last", action="store", dest="last_channel",
                      default="383", help="Last frequency channel [default: 383]")
    parser.add_option("-i", "--receiver_interface", action="store", dest="receiver_interface",
                      default="eth0", help="Receiver interface [default: eth0]")
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_flagging.log',
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

    test_logger = logging.getLogger('TEST_FLAGGING')

    test_inst = TestFlagging(tpm_config, test_logger)
    test_inst.execute(int(conf.first_channel), int(conf.last_channel))

