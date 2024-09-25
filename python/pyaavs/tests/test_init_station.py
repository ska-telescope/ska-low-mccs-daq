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


def format_data_rate(bytes_per_second):
    """Formats data rate based on size in appropriate units (B, KiB, MiB, GiB)"""
    if bytes_per_second < 1024:
        return f"{bytes_per_second} B/s"
    elif bytes_per_second < 1024**2:
        return f"{round(bytes_per_second / 1024, 2)} KiB/s"
    elif bytes_per_second < 1024**3:
        return f"{round(bytes_per_second / 1024**2, 2)} MiB/s"
    else:
        return f"{round(bytes_per_second / 1024**3, 2)} GiB/s"

def format_time(seconds):
    """Formats seconds into days, hours minutes and seconds"""
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        return f"{seconds // 60} minutes, {seconds % 60} seconds"
    elif seconds < 86400:
        return f"{seconds // 3600} hours, {(seconds % 3600) // 60} minutes, {seconds % 60} seconds"
    else:
        return f"{seconds // 86400} days, {(seconds % 86400) // 3600} hours, {(seconds % 3600) // 60} minutes, {seconds % 60} seconds"
        
class TestInitStation():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._test_station = None
        self._station_config = station_config
        self._daq_eth_if = station_config['eth_if']
        self._csp_port = station_config['network']['csp_ingest']['dst_port']  # Test typically uses a raw socket so port is ignored
        self._total_bandwidth = station_config['test_config']['total_bandwidth']
        self._observation_bandwidth = self._station_config['observation']['bandwidth']

    def execute(self, iteration=4, stop_on_error=True, data_rate_check_duration=10):

        station_config = copy.deepcopy(self._station_config)
        station_config['station']['program'] = True
        station_config['station']['initialise'] = True
        station_config['station']['start_beamformer'] = True

        # Expected data rate in byte/s
        expected_data_rate = self._observation_bandwidth * 32.0 / 27.0 * 2 * 2
        expected_data_rate_low = expected_data_rate * 14.0 / 16.0
        expected_data_rate_hi = expected_data_rate * 16.0 / 14.0

        iter_fail_count = 0
        for iter in range(1, iteration + 1):
            errors = 0
            self._logger.info(f"Initialising station. Iteration {iter}")
            self._test_station = station.Station(station_config)
            self._test_station.connect()
            time.sleep(1)
            spead_rx_realtime_inst = SpeadRxBeamPowerRealtime(self._csp_port, self._daq_eth_if)
            received_data_rate = np.asarray(spead_rx_realtime_inst.get_data_rate_net_io(expected_data_rate))

            if received_data_rate < expected_data_rate_low or received_data_rate > expected_data_rate_hi:
                self._logger.error(f"Station Initialisation failed. Expected data rate {format_data_rate(expected_data_rate)}, received data rate {format_data_rate(received_data_rate)}")
                if stop_on_error:
                    self._logger.error(f"Iteration {iter} Error!")
                    return 1
                errors += 1
            else:
                self._logger.info(f"Station beam data rate: {format_data_rate(int(received_data_rate))}")

            for t, tile in enumerate(self._test_station.tiles):
                for fpga in ['fpga1', 'fpga2']:
                    if tile[f'{fpga}.beamf_fd.f2f_latency.count'] > 100:
                        self._logger.error(f"Tile {t}, F2F latency error!")
                        if stop_on_error:
                            self._logger.error(f"Iteration {iter} Error!")
                            return 1
                        errors += 1
                    if tile[f'{fpga}.beamf_fd.f2f_latency.count_start']!= 1:
                        self._logger.error(f"Tile {t}, F2F latency start error!")
                        if stop_on_error:
                            self._logger.error(f"Iteration {iter} Error!")
                            return 1
                        errors += 1
                    if tile[f'{fpga}.beamf_fd.f2f_latency.count_stop'] != 1:
                        self._logger.error("Tile {t}, F2F latency stop error!")
                        if stop_on_error:
                            self._logger.error(f"Iteration {iter} Error!")
                            return 1
                        errors += 1
                    if tile[f'{fpga}.beamf_fd.errors'] != 0:
                        self._logger.error(f"Tile {t}, Tile Beamformer error!")
                        if stop_on_error:
                            self._logger.error(f"Iteration {iter} Error!")
                            return 1
                        errors += 1
                    for core in range(2):
                        for lane in range(8):
                            if tile[f"{fpga}.jesd204_if.core_id_{core}_lane_{lane}_buffer_adjust"] >= 32:
                                self._logger.error(f"Tile {t}, JESD204B fill buffer level larger than 32 octets")
                                if stop_on_error:
                                    self._logger.error(f"Iteration {iter} Error!")
                                    return 1
                                errors += 1

            for d in range(0, data_rate_check_duration, 10):
                time.sleep(10)
                received_data_rate = np.asarray(spead_rx_realtime_inst.get_data_rate_net_io(expected_data_rate))
                if received_data_rate < expected_data_rate_low or received_data_rate > expected_data_rate_hi:
                    self._logger.error(f"Station beam data rate: {format_data_rate(int(received_data_rate))} after {format_time(d+10)}. Expected data rate {format_data_rate(expected_data_rate)}")
                    if stop_on_error:
                        self._logger.error(f"Iteration {iter} Error!")
                        return 1
                    errors += 1
                else:
                    self._logger.info(f"Station beam data rate: {format_data_rate(int(received_data_rate))} after {format_time(d+10)}")

            if not stop_on_error and errors:
                iter_fail_count += 1
                self._logger.error(f"Iteration {iter} Error! (P={iter-iter_fail_count} F={iter_fail_count} T={iteration})")
            else:
                self._logger.info(f"Iteration {iter} OK! (P={iter-iter_fail_count} F={iter_fail_count} T={iteration})")

        if not stop_on_error and iter_fail_count:
            self._logger.error(f"TEST FAILED! {iter_fail_count} iterations failed ({(iter_fail_count / iteration) * 100:.2f}%)")
            return 1
        self._logger.info("TEST PASSED!")
        return 0


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %test_init_station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("--iteration", action="store", dest="iteration",
                      type="str", default="4", help="Number of iterations [default: 4]")
    parser.add_option("--stop_on_error", action="store_true", dest="stop_on_error",
                      default=True, help="Fail immediately on error [default: True]")
    parser.add_option("--data_rate_check_duration", action="store", dest="data_rate_check_duration",
                      type="str", default="10", help="Duration of data rate checks between iterations [default: 10]")


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
    test_inst.execute(int(opts.iteration), opts.stop_on_error, int(opts.data_rate_check_duration))
