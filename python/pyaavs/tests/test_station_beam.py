import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt

from pydaq import daq_receiver as receiver
from datetime import datetime, timedelta
from pydaq.persisters import *
from pyaavs import station
from config_manager import ConfigManager
from numpy import random
from spead_beam_pattern_check import SpeadRxBeamPatternCheck
import test_functions as tf
import numpy as np
import tempfile
import logging
import shutil
import time
import os
from test_ddr import TestDdr
from test_antenna_buffer import TestAntennaBuffer

# Number of samples to process
nof_samples = 256*1024
# Global variables to track callback
tiles_processed = None
buffers_processed = 0
data_ready = False


def delete_files(directory):
    """ Delete all files in directory """
    for f in os.listdir(directory):
        os.remove(os.path.join(directory, f))

class TestStationBeam():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self._test_station = None
        self._daq_eth_if = station_config['eth_if']
        self._total_bandwidth = station_config['test_config']['total_bandwidth']
        self._antennas_per_tile = station_config['test_config']['antennas_per_tile']
        self._pfb_nof_channels = station_config['test_config']['pfb_nof_channels']
        self._test_ddr_inst = TestDdr(station_config, logger)
        self._test_antenna_buffer_inst = TestAntennaBuffer(station_config, logger)
        self._csp_scale = 0
        self._channeliser_scale = 0
        self._pattern = [[0, 0, 0, 0]] * 384
        # for n in range(384):
        #     if n % 4 == 0:
        #         self._pattern[n] = [n // 4, 0, 0, 0]
        #     elif n % 4 == 1:
        #         self._pattern[n] = [1, n // 4, 1, 1]
        #     elif n % 4 == 2:
        #         self._pattern[n] = [2, 2, n // 4, 2]
        #     else:
        #         self._pattern[n] = [3, 3, 3, n // 4]
        for n in range(384):
            self._pattern[n] = [n % 32, n // 32, n % 128, n // 4]

    def prepare_test(self, pattern_type):
        for i, tile in enumerate(self._test_station.tiles):
            tile.set_channeliser_truncation(5)
            tf.disable_test_generator_and_pattern(tile)
            tile['fpga1.jesd204_if.regfile_channel_disable'] = 0xFFFF
            tile['fpga2.jesd204_if.regfile_channel_disable'] = 0xFFFF
            self._test_station.tiles[i].test_generator_input_select(0xFFFFFFFF)
        self._test_station.test_generator_set_tone(0, frequency=100e6, ampl=0.0)
        self._test_station.test_generator_set_tone(1, frequency=100e6, ampl=0.0)
        self._test_station.test_generator_set_noise(ampl=0.35, delay=1024)
        self._csp_scale = int(np.ceil(np.log2(len(self._test_station.tiles))))
        self._channeliser_scale = 0
        for tile in self._test_station.tiles:
            tile['fpga1.beamf_ring.csp_scaling'] = self._csp_scale
            tile['fpga2.beamf_ring.csp_scaling'] = self._csp_scale
            tile.set_channeliser_truncation(self._channeliser_scale)
        self._test_station['fpga1.beamf_ring.control.enable_pattern_generator'] = pattern_type
        self._test_station['fpga2.beamf_ring.control.enable_pattern_generator'] = pattern_type

        # Set time delays to 0
        for tile in self._test_station.tiles:
            tf.set_delay(tile, [0]*32)

        tf.set_station_beam_pattern(self._test_station, self._pattern,
                                    start=True, shift=0, zero=0, csp_rounding=self._csp_scale)

    def check_station(self):
        station_ok = True
        if not self._test_station.properly_formed_station:
            station_ok = False
        else:
            for tile in self._test_station.tiles:
                if not tile.is_programmed():
                    station_ok = False
                if not tile.beamformer_is_running():
                    station_ok = False
        return station_ok

    def execute(self, iterations=16, background_ddr_access=True, pattern_type=1):
        global nof_samples

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self.prepare_test(pattern_type)

        # Update channel numbers
        channel_bandwidth = float(self._total_bandwidth) / int(self._pfb_nof_channels)
        nof_channels = int(self._station_config['observation']['bandwidth'] / channel_bandwidth)

        try:

            errors = 0

            if background_ddr_access:

                for tile in self._test_station.tiles:
                    tile.tpm.set_shutdown_temperature(70)

                self._logger.info("Enabling DDR background access...")
                # Set DDR address for background DDR and antenna buffer instances
                ddr_test_base_address = 512 * 1024 * 1024
                ddr_test_length = 256 * 1024 * 1024
                antenna_buffer_base_address = 768 * 1024 * 1024
                antenna_buffer_length = 256 * 1024 * 1024

                # start DDR test
                errors = self._test_ddr_inst.prepare(first_addr=ddr_test_base_address // 8,
                                                     last_addr=(ddr_test_base_address + ddr_test_length) // 8 - 8,
                                                     burst_length=3,
                                                     pause=64,
                                                     reset_dsp=0,
                                                     reset_ddr=0,
                                                     stop_transmission=0)
                if errors > 0:
                   self._logger.error("Not possible to start DDR background test")
                   self._logger.error("TEST FAILED!")
                   return 1
                self._test_ddr_inst.start()
                self._logger.info("DDR test started.")

                # start antenna buffer write into DDR
                if self._test_station.tiles[0]['fpga1.dsp_regfile.feature.antenna_buffer_implemented'] == 1:
                    for n, tile in enumerate(self._test_station.tiles):
                        for i in [0, 1]:
                            ab_inst = tile.tpm.tpm_antenna_buffer[i]
                            ab_inst.configure_ddr_buffer(
                                ddr_start_byte_address=antenna_buffer_base_address,  # DDR buffer base address
                                byte_size=antenna_buffer_length)
                            ab_inst.buffer_write(continuous_mode=True)
                self._logger.info("Antenna buffer write into DDR started.")

            iter = 0
            while iter < iterations:

                iter += 1

                self._logger.info("Acquiring realtime beamformed data")
                spead_rx_realtime_inst = SpeadRxBeamPatternCheck(4660, self._daq_eth_if)
                errors += np.asarray(spead_rx_realtime_inst.check_data(self._pattern, pattern_type))
                self._logger.info("Checking pattern iteration %d, errors: %d" % (iter, errors))

                del spead_rx_realtime_inst

                if background_ddr_access:
                    self._logger.info("Checking DDR test results...")
                    # Get DDR background test result
                    for fpga in ["fpga1", "fpga2"]:
                        for n, tile in enumerate(self._test_station.tiles):
                            if tile['%s.ddr_simple_test.error' % fpga] == 1:
                                self._logger.error("Background DDR test error detected in Tile %d, %s" % (n, fpga.upper()))
                                errors += 1
                    self._logger.info("...DDR result check finished.")

            if errors > 0:
                self._logger.error("TEST FAILED!")
            else:
                self._logger.info("TEST PASSED!")

        except Exception as e:
            errors += 1
            import traceback
            self._logger.error(traceback.format_exc())
            self._logger.error("TEST FAILED!")

        finally:
            if background_ddr_access:
                # stop DDR test
                self._test_ddr_inst.stop()
                # stop antenna buffer
                if self._test_station.tiles[0]['fpga1.dsp_regfile.feature.antenna_buffer_implemented'] == 1:
                    for n, tile in enumerate(self._test_station.tiles):
                        for i in [0, 1]:
                            ab_inst = tile.tpm.tpm_antenna_buffer[i]
                            ab_inst.stop_now()

            for tile in self._test_station.tiles:
                tile.tpm.set_shutdown_temperature(65)

            return errors


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout
    
    parser = OptionParser(usage="usage: %test_full_station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("--iterations", action="store", dest="iterations",
                      type="str", default="128", help="Number of iterations [default: 128]")
    parser.add_option("--pattern_type", action="store", dest="pattern_type",
                      type="str", default="0", help="Pattern type. 0: default pattern, 1: embedded pattern [default: 0]")

    (opts, args) = parser.parse_args(argv[1:])

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_station_beam.log',
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

    test_logger = logging.getLogger('TEST_FULL_STATION')

    # Check if a config file is specified
    if opts.config is None:
        test_logger.error("No station configuration file was defined. Exiting")
        exit()
    elif not os.path.exists(opts.config) or not os.path.isfile(opts.config):
        test_logger.error("Specified config file does not exist or is not a file. Exiting")
        exit()

    config_manager = ConfigManager(opts.test_config)
    station_config = config_manager.apply_test_configuration(opts)

    test_inst = TestStationBeam(station_config, test_logger)
    test_inst.execute(int(opts.iterations),
                      int(opts.pattern_type))
