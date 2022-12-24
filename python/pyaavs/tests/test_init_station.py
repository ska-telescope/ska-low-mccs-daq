#!/usr/bin/env python2
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt

from pydaq import daq_receiver as receiver
from datetime import datetime, timedelta
from pydaq.persisters import *
from pyaavs import station
from config_manager import ConfigManager
from numpy import random
from spead_beam_power_realtime import SpeadRxBeamPowerRealtime
from spead_beam_power_offline import SpeadRxBeamPowerOffline
import spead_beam_power_realtime
import spead_beam_power_offline
import test_functions as tf
import numpy as np
import tempfile
import logging
import shutil
import copy
import time
import os

# Number of samples to process
nof_samples = 256*1024
# Global variables to track callback
tiles_processed = None
buffers_processed = 0
data_ready = False


class TestInitStation():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._test_station = None
        self._station_config = station_config
        self._daq_eth_if = station_config['eth_if']
        self._total_bandwidth = station_config['test_config']['total_bandwidth']
        self._observation_bandwidth = self._station_config['observation']['bandwidth']

    def execute(self, iteration=4):

        station_config = copy.deepcopy(self._station_config)
        station_config['station']['program'] = True
        station_config['station']['initialise'] = True
        station_config['station']['start_beamformer'] = True

        # Expected data rate in byte/s
        expected_data_rate = self._observation_bandwidth * 32.0 / 27.0 * 2 * 2
        expected_data_rate_low = expected_data_rate * 14.0 / 16.0
        expected_data_rate_hi = expected_data_rate * 16.0 / 14.0

        for iter in range(1, iteration + 1):
            self._logger.info("Initialising station. Iteration %d" % iter)
            self._test_station = station.Station(station_config)
            self._test_station.connect()
            time.sleep(1)
            spead_rx_realtime_inst = SpeadRxBeamPowerRealtime(4660, self._daq_eth_if)
            received_data_rate = np.asarray(spead_rx_realtime_inst.get_data_rate_net_io(expected_data_rate))
            self._logger.info("Station beam data rate: %d bytes/s" % int(received_data_rate))

            if received_data_rate < expected_data_rate_low or received_data_rate > expected_data_rate_hi:
                self._logger.error("Station Initialisation failed. Expected data rate %f, received data rate %f" % (expected_data_rate, received_data_rate))
                return 1

            for t, tile in enumerate(self._test_station.tiles):
                for fpga in ['fpga1', 'fpga2']:
                    if tile['%s.beamf_fd.f2f_latency.count' % fpga] > 100:
                        self._logger.error("Tile %d, F2F latency error!" % t)
                        return 1
                    if tile['%s.beamf_fd.f2f_latency.count_start' % fpga]!= 1:
                        self._logger.error("Tile %d, F2F latency start error!" % t)
                        return 1
                    if tile['%s.beamf_fd.f2f_latency.count_stop' % fpga] != 1:
                        self._logger.error("Tile %d, F2F latency stop error!" % t)
                        return 1
                    if tile['%s.beamf_fd.errors' % fpga] != 0:
                        self._logger.error("Tile %d, Tile Beamformer error!" % t)
                        return 1
                    for core in range(2):
                        for lane in range(8):
                            if tile["%s.jesd204_if.core_id_%d_lane_%d_buffer_adjust" % (fpga, core, lane)] >= 32:
                                self._logger.error("Tile %d, JESD204B fill buffer level larger than 32 octets" % t)
                                return 1

            self._logger.info("Iteration %d OK!" % iter)

        self._logger.info("TEST PASSED!")
        return 0


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %test_init_station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("--iteration", action="store", dest="iteration",
                      type="str", default="4", help="Number of iterations [default: 4]")

    (opts, args) = parser.parse_args(argv[1:])

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_full_station.log',
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

    test_inst = TestInitStation(station_config, test_logger)
    test_inst.execute(int(opts.iteration))
