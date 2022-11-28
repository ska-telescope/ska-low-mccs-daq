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


class TestTileBeamformer():
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
        # beam data
        #
        tf.disable_test_generator_and_pattern(tile)
        tile.set_channeliser_truncation(5)
        tile['fpga1.jesd204_if.regfile_channel_disable'] = 0xFFFF
        tile['fpga2.jesd204_if.regfile_channel_disable'] = 0xFFFF

        channels = range(int(first_channel), int(last_channel) + 1)
        single_input_data = np.zeros((2, 16), dtype='complex')
        coeff = np.zeros((2, 16), dtype='complex')
        errors = 0
        for c in channels:
            channel_errors = 0
            frequency = (self._beam_start_channel + c) * self._channel_width
            tile.test_generator_set_tone(0, frequency, 0.5)
            tile.test_generator_input_select(0xFFFFFFFF)
            time_delays = [random.randrange(-32, 32, 1) for x in range(32)]
            tf.set_delay(tile, time_delays)
            ref_antenna = random.randrange(0, 16, 1)
            ref_pol = random.randrange(0, 2, 1)
            tf.reset_beamf_coeff(tile, gain=1.0)
            time_delays_hw = [[0.0, 0.0]]*16
            tile.set_pointing_delay(time_delays_hw, 0.0)
            tile.load_pointing_delay()
            time.sleep(0.5)

            # Loop over the antennas with all antenna masked except one, build antenna response matrix
            inputs = 0x3
            for i in range(16):

                tile.test_generator_input_select(inputs)
                # Set data received to False
                data_received = False
                # Send data from tile
                tile.send_beam_data()
                # Wait for data to be received
                while not data_received:
                    time.sleep(0.1)

                single_input_data[0][i] = tf.get_beam_value(data, 0, c)  # - self._beam_start_channel)
                single_input_data[1][i] = tf.get_beam_value(data, 1, c)  # - self._beam_start_channel)

                inputs = (inputs << 2)
                self._logger.info("Antenna %d value before phasing: " % i)
                self._logger.info("Pol 0: " + str(single_input_data[0][i]))
                self._logger.info("Pol 1: " + str(single_input_data[1][i]))

            # Calculate coeffs to phase all antennas to the ref antenna
            ref_value = single_input_data[ref_pol][ref_antenna]
            self._logger.debug("Ref Antenna: %d", ref_antenna)
            self._logger.debug("Ref Pol: %d", ref_pol)
            for p in range(2):
                for n in range(16):
                    coeff[p][n] = ref_value / single_input_data[p][n]
            self._logger.debug("Coefficients:")
            self._logger.debug(coeff)

            # Setting beamformer coefficients in the TPM
            tf.set_beamf_coeff(tile, coeff, c)  # - self._beam_start_channel)

            # Loop over the antennas with all antenna masked except one, build antenna response matrix
            inputs = 0x3
            for i in range(16):

                tile.test_generator_input_select(inputs)
                # Set data received to False
                data_received = False
                # Send data from tile
                tile.send_beam_data()
                # Wait for data to be received
                while not data_received:
                    time.sleep(0.1)

                single_input_data[0][i] = tf.get_beam_value(data, 0, c)  # + self._beam_start_channel)
                single_input_data[1][i] = tf.get_beam_value(data, 1, c)  # + self._beam_start_channel)

                inputs = (inputs << 2)
                self._logger.debug("Antenna %d value after phasing: " % i)
                self._logger.debug("Pol 0: " + str(single_input_data[0][i]))
                self._logger.debug("Pol 1: " + str(single_input_data[1][i]))

            self._logger.debug("Checking beamformed values...")
            for p in range(2):
                for a in range(16):
                    exp_val = ref_value
                    rcv_val = single_input_data[p][a]
                    if abs(exp_val.real - rcv_val.real) > 1 or abs(exp_val.imag - rcv_val.imag) > 1:
                        self._logger.error("Error in beamformed values!")
                        self._logger.error("Reference Antenna:")
                        self._logger.error(ref_value)
                        self._logger.error("Received values:")
                        self._logger.error(single_input_data)
                        channel_errors += 1
                        break

            # Now form a beam of all antennas
            inputs = 0xFFFFFFFF
            tile.test_generator_input_select(inputs)
            # Set data received to False
            data_received = False
            # Send data from tile
            tile.send_beam_data()
            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            # Checking beam
            for p in range(2):
                beam_val = tf.get_beam_value(data, p, c) # - self._beam_start_channel)
                single_val = ref_value

                if abs(beam_val.real / 16 - single_val.real) > 1 or abs(beam_val.imag / 16 - single_val.imag) > 1:
                    self._logger.error("Error in beam sum:")
                    self._logger.error("Individual antenna values:")
                    self._logger.error(single_input_data)
                    self._logger.error("Beam Sum value:")
                    self._logger.error(tf.get_beam_value(data, p, c)) # - self._beam_start_channel))
                    channel_errors += 1
                    break

            self._logger.info("Checking beam pointing...")
            tf.reset_beamf_coeff(tile, gain=1.0)
            time_delays = [0]*32
            tf.set_delay(tile, time_delays)

            time.sleep(0.5)

            data_received = False
            # Send data from tile
            tile.send_beam_data()
            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            beam_val_reference_pol0 = tf.get_beam_value(data, 0, c)
            beam_val_reference_pol1 = tf.get_beam_value(data, 1, c)
            self._logger.info("Reference value pol0:")
            self._logger.info(beam_val_reference_pol0)

            time_delays = []
            for n in range(32):
                random_val = random.randrange(-32, 32, 1)
                time_delays.append(random_val)
                time_delays.append(random_val)
            tf.set_delay(tile, time_delays)

            time.sleep(0.2)

            data_received = False
            # Send data from tile
            tile.send_beam_data()
            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            beam_val_uncorrected_pol0 = tf.get_beam_value(data, 0, c)
            beam_val_uncorrected_pol1 = tf.get_beam_value(data, 1, c)
            self._logger.info("Uncorrected value pol0:")
            self._logger.info(beam_val_uncorrected_pol0)

            time_delays_hw = []
            for n in range(16):
                time_delays_hw.append([float(time_delays[2*n]) * 1.25 * 1e-9, 0.0])
            tile.set_pointing_delay(time_delays_hw, 0.0)
            tile.load_pointing_delay(load_delay=512)
            time.sleep(0.5)

            data_received = False
            # Send data from tile
            tile.send_beam_data()
            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            beam_val_corrected_pol0 = tf.get_beam_value(data, 0, c)
            beam_val_corrected_pol1 = tf.get_beam_value(data, 0, c)
            self._logger.info(beam_val_corrected_pol0)
            self._logger.info(beam_val_corrected_pol1)
            self._logger.info("Corrected value pol0:")
            self._logger.info(beam_val_corrected_pol0)

            if abs(beam_val_reference_pol0.real - beam_val_corrected_pol0.real) >= 2 or abs(beam_val_reference_pol0.imag - beam_val_corrected_pol0.imag) >= 2 or \
               abs(beam_val_reference_pol1.real - beam_val_corrected_pol1.real) >= 2 or abs(beam_val_reference_pol1.imag - beam_val_corrected_pol1.imag) >= 2:
                self._logger.error("Error in beam pointing:")
                self._logger.error("Reference value pol0/pol1:")
                self._logger.error(beam_val_reference_pol0)
                self._logger.error(beam_val_reference_pol1)
                self._logger.error("Corrected value pol0/pol1:")
                self._logger.error(beam_val_corrected_pol0)
                self._logger.error(beam_val_corrected_pol1)
                channel_errors += 1

            if channel_errors == 0:
                self._logger.info("Channel " + str(c) + " PASSED!")
            else:
                self._logger.info("Channel " + str(c) + " FAILED!")
            errors += channel_errors

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
                        filename='test_log/test_tile_beamformer.log',
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

    test_logger = logging.getLogger('TEST_BEAMFORMER')

    test_inst = TestTileBeamformer(tpm_config, test_logger)
    test_inst.execute(int(conf.first_channel), int(conf.last_channel))

