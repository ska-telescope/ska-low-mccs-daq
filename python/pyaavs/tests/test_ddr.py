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


class TestDdr():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self._test_station = None

    def clean_up(self):
        return

    def prepare(self, first_addr=0x0, last_addr=0x7FFFFF8, burst_length=0, pause=0,
                reset_dsp=0, reset_ddr=1, stop_transmission=1):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        errors = 0

        try:
            self._test_station['fpga1.ddr_if.status']
        except:
            self._logger.error("DDR Test not supported by FPGA firmware!")
            self._logger.error("DDR Test FAILED!")
            self.clean_up()
            return 1

        self._test_station['fpga1.ddr_simple_test.start'] = 0
        self._test_station['fpga2.ddr_simple_test.start'] = 0

        if stop_transmission == 1:
            tf.stop_all_data_transmission(self._test_station)

        # Resetting DSP to get exclusive access to DDR
        if reset_dsp == 1:
            self._test_station['fpga1.regfile.reset.dsp_rst'] = 1
            self._test_station['fpga2.regfile.reset.dsp_rst'] = 1

        # Resetting DDR and checking initialisation
        if reset_ddr == 1:
            self._test_station['fpga1.regfile.reset.ddr_rst'] = 1
            self._test_station['fpga2.regfile.reset.ddr_rst'] = 1
            self._test_station['fpga1.regfile.reset.ddr_rst'] = 0
            self._test_station['fpga2.regfile.reset.ddr_rst'] = 0
            time.sleep(1)

        for n, tile in enumerate(self._test_station.tiles):
            if tile['fpga1.regfile.status.ddr_init_done'] == 0:
                self._logger.error("Tile %d FPGA1 not initialising. Test FAILED" % n)
                errors += 1
            if tile['fpga2.regfile.status.ddr_init_done'] == 0:
                self._logger.error("Tile %d FPGA2 not initialising. Test FAILED" % n)
                errors += 1
            if errors > 0:
                return 1

        # Preparing test
        self._test_station['fpga1.ddr_simple_test.last_addr'] = last_addr
        self._test_station['fpga2.ddr_simple_test.last_addr'] = last_addr
        self._test_station['fpga1.ddr_simple_test.first_addr'] = first_addr
        self._test_station['fpga2.ddr_simple_test.first_addr'] = first_addr
        if self._test_station.tiles[0].tpm.has_register('fpga1.ddr_simple_test.addr_increment'):
            self._test_station['fpga1.ddr_simple_test.addr_increment'] = 8
            self._test_station['fpga2.ddr_simple_test.addr_increment'] = 8
        if self._test_station.tiles[0].tpm.has_register("fpga1.ddr_simple_test.burst_length"):
            self._test_station['fpga1.ddr_simple_test.burst_length'] = burst_length
            self._test_station['fpga2.ddr_simple_test.burst_length'] = burst_length
        self._test_station['fpga1.ddr_simple_test.pause'] = pause
        self._test_station['fpga2.ddr_simple_test.pause'] = pause
        self._test_station['fpga1.ddr_simple_test.error'] = 0
        self._test_station['fpga2.ddr_simple_test.error'] = 0

        return 0

    def start(self):
        self._test_station['fpga1.ddr_simple_test.start'] = 1
        self._test_station['fpga2.ddr_simple_test.start'] = 1

    def stop(self):
        self._test_station['fpga1.ddr_simple_test.start'] = 0
        self._test_station['fpga2.ddr_simple_test.start'] = 0

    def execute(self, duration=16, first_addr=0x0, last_addr=0x7FFFFF8, burst_length=0, pause=0,
                reset_dsp=0, reset_ddr=1, stop_transmission=1):

        self._logger.debug("Preparing DDR test, duration %d seconds" % duration)

        errors = self.prepare(first_addr=first_addr,
                              last_addr=last_addr,
                              burst_length=burst_length,
                              pause=pause,
                              reset_dsp=reset_dsp,
                              reset_ddr=reset_ddr,
                              stop_transmission=stop_transmission)

        nof_tiles = len(self._test_station.tiles)

        if errors > 0:
            self._logger.error("DDR Test FAILED!")
            self.clean_up()
            return 1

        time.sleep(0.1)

        # Running test
        prev_rd_cnt_fpga1 = [0] * nof_tiles
        prev_rd_cnt_fpga2 = [0] * nof_tiles
        fpga1_status = self._test_station['fpga1.ddr_if.status']
        fpga2_status = self._test_station['fpga2.ddr_if.status']
        self.start()
        for t in range(duration):
            time.sleep(1)
            curr_rd_cnt_fpga1 = self._test_station['fpga1.ddr_simple_test.rd_cnt']
            curr_rd_cnt_fpga2 = self._test_station['fpga2.ddr_simple_test.rd_cnt']
            for n, tile in enumerate(self._test_station.tiles):
                if prev_rd_cnt_fpga1[n] == curr_rd_cnt_fpga1[n]:
                    self._logger.error("Tile %d FPGA1 test is not running" % n)
                    errors += 1
                if prev_rd_cnt_fpga2[n] == curr_rd_cnt_fpga2[n]:
                    self._logger.error("Tile %d FPGA2 test is not running" % n)
                    errors += 1
                if self._test_station['fpga1.ddr_simple_test.error'][n] == 1:
                    self._logger.error("Tile %d FPGA1 error. Test FAILED." % n)
                    errors += 1
                if self._test_station['fpga2.ddr_simple_test.error'][n] == 1:
                    self._logger.error("Tile %d FPGA2 error. Test FAILED." % n)
                    errors += 1
                if (self._test_station['fpga1.ddr_if.status'][n] & 0xF00) != (fpga1_status[n] & 0xF00):
                    self._logger.error("Tile %d FPGA1 error. DDR reinitialised during test error. Test FAILED.." % n)
                    errors += 1
                if (self._test_station['fpga2.ddr_if.status'][n] & 0xF00) != (fpga2_status[n] & 0xF00):
                    self._logger.error("Tile %d FPGA2 error. DDR reinitialised during test error. Test FAILED." % n)
                    errors += 1
            if errors > 0:
                self._logger.error("DDR Test FAILED!")
                self.clean_up()
                return 1
            prev_rd_cnt_fpga1 = curr_rd_cnt_fpga1
            prev_rd_cnt_fpga2 = curr_rd_cnt_fpga2
            self._logger.info("Test running with no errors detected, elapsed time %d seconds" % (t + 1))

        self.stop()
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
                        filename='test_log/test_ddr.log',
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

    test_logger = logging.getLogger('TEST_DDR')

    test_inst = TestDdr(tpm_config, test_logger)
    test_inst.execute(int(conf.duration))
