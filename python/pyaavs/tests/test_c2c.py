from pyaavs.tile import Tile
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


class TestC2c():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self._test_station = None

    def clean_up(self):
        return

    def execute(self, nof_loops=100):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._logger.debug("Preparing C2C test, number of loops %d" % nof_loops)

        errors = 0
        iter = 0

        for t, tile in enumerate(self._test_station.tiles):
            for fpga in ['fpga1', 'fpga2']:
                self._logger.info("Testing Tile %d %s..." % (t, fpga))
                while iter < nof_loops or nof_loops == 0:
                    write_pattern = list(range(iter, 256 * 10 + iter))
                    address = tile.tpm.memory_map['fpga1.bram64k'].address
                    self._test_station[address] = write_pattern
                    read_pattern = tile.tpm.read_address(address, 256 * 10)
                    if read_pattern != write_pattern:
                        self._logger.error("Tile %d %s error. Test FAILED." % (t, fpga))
                        errors += 1
                        break
                    iter += 1
                    if nof_loops == 0:
                        self._logger.info("Tile %d %s iteration %d" % (t, fpga, iter))

        if errors > 0:
            self._logger.error("Test FAILED!")
            self.clean_up()
            return 1

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
                        filename='test_log/test_c2c.log',
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

    test_logger = logging.getLogger('TEST_C2C')

    test_inst = TestC2c(tpm_config, test_logger)
    test_inst.execute(int(conf.duration))
