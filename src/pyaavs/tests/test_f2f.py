from pyaavs.tile_wrapper import Tile
from pyaavs import station
from config_manager import ConfigManager

from builtins import input
from sys import stdout
import test_functions as tf
import numpy as np
import os.path
import logging
import random
import time


class TestF2f():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self._test_station = None
        self._plugin_type = None

    def clean_up(self):
        for n, tile in enumerate(self._test_station.tiles):
            for f2f in tile.tpm.tpm_f2f:
                f2f.stop_test()
        del self._test_station

    def execute(self, duration=8):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._plugin_type = self._test_station.tiles[0].tpm.tpm_f2f[0].__class__.__name__

        self._logger.info("Preparing F2F test, duration %d seconds" % duration)

        errors = 0

        tf.stop_all_data_transmission(self._test_station)

        for n, tile in enumerate(self._test_station.tiles):
            for f2f in tile.tpm.tpm_f2f:
                f2f.assert_reset()
        for n, tile in enumerate(self._test_station.tiles):
            for f2f in tile.tpm.tpm_f2f:
                f2f.deassert_reset()

        time.sleep(0.5)

        for n, tile in enumerate(self._test_station.tiles):
            for f2f in tile.tpm.tpm_f2f:
                if f2f.check_channel_up() == 0:
                    self._logger.error("Tile %d F2F not initialising. Test FAILED" % n)
                    errors += 1

        if errors > 0:
            self._logger.error("F2F Test FAILED!")
            self.clean_up()
            return 1

        if self._plugin_type == 'TpmFpga2FpgaAurora':
            tests = ['incremental']
        else:
            if self._test_station.tiles[0].tpm.has_register('fpga1.f2f.test_pattern_rx_check'):
                tests = ['incremental', 'pattern1', 'pattern2']
            else:
                tests = ['incremental']

        for test_type in tests:

            self._logger.info("Starting F2F test, test_type: %s, duration %d seconds" % (test_type, duration))

            for n, tile in enumerate(self._test_station.tiles):
                for f2f in tile.tpm.tpm_f2f:
                    f2f.stop_test()

            if self._plugin_type == 'TpmFpga2Fpga':
                if test_type == "incremental":
                    pattern = 0
                    pattern_enable = 0
                elif test_type == "pattern1":
                    pattern = 0x5A
                    pattern_enable = 0xFFFFFFFF
                elif test_type == "pattern2":
                    pattern = 0xD2
                    pattern_enable = 0xFFFFFFFF
                for n, tile in enumerate(self._test_station.tiles):
                    for f2f in tile.tpm.tpm_f2f:
                        f2f.set_test_pattern(pattern_enable, pattern)

            for n, tile in enumerate(self._test_station.tiles):
                for f2f in tile.tpm.tpm_f2f:
                    f2f.start_tx_test()

            for n, tile in enumerate(self._test_station.tiles):
                for f2f in tile.tpm.tpm_f2f:
                    f2f.start_rx_test()

            for n, tile in enumerate(self._test_station.tiles):
                for f2f in tile.tpm.tpm_f2f:
                    f2f.start_rx_test()

            for t in range(duration):
                time.sleep(1)
                for n, tile in enumerate(self._test_station.tiles):
                    if self._plugin_type == 'TpmFpga2FpgaAurora':
                        for fpga in ["fpga1", "fpga2"]:
                            self._logger.info("Tile " + str(n) + " " + fpga.upper() + " test status:")
                            self._logger.info("    Active: " + str(tile['%s.f2f_aurora.test_status.test_active' % fpga]))
                            self._logger.info("    Errors Detected: " + str(tile['%s.f2f_aurora.test_status.error_detected' % fpga]))
                            self._logger.info("    Lane with Errors: " + hex(tile['%s.f2f_aurora.test_status.error_lane' % fpga]))
                            if tile['%s.f2f_aurora.test_status.test_active' % fpga] == 0 or tile['%s.f2f_aurora.test_status.error_detected' % fpga] == 1:
                                errors += 1
                    elif self._plugin_type == 'TpmFpga2Fpga':
                        self._logger.info("Tile " + str(n) + " test status:")
                        for i in list(range(2)):
                            test_result = tile.tpm.tpm_f2f[i].get_test_result()
                            if test_result > 0:
                                errors += 1
                            self._logger.info("  Core %d Errors Detected: %s" % (i, hex(test_result)))
                    else:
                        self._logger.error("Plugin %s not supported as F2F." % self._plugin_type)
                        errors += 1
                if errors > 0:
                    self._logger.error("F2F Test FAILED!")
                    self.clean_up()
                    return 1
                else:
                    self._logger.info("Test running with no errors detected, elapsed time %d seconds" % (t + 1))

            for n, tile in enumerate(self._test_station.tiles):
                for f2f in tile.tpm.tpm_f2f:
                    f2f.stop_test()

        self._logger.info("Test PASSED!")
        self.clean_up()
        return 0


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-d", "--duration", action="store", dest="duration",
                      default="16", help="Test duration in seconds [default: 16, infinite: -1]")
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_f2f.log',
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

    test_logger = logging.getLogger('TEST_F2F')

    test_inst = TestF2f(tpm_config, test_logger)
    test_inst.execute(int(conf.duration))
