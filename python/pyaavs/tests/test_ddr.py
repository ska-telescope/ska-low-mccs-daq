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
from copy import deepcopy


class TestDdr():
    def __init__(self, station_config, logger):
        self.ddr_size_list = []
        self._logger = logger
        self._station_config = station_config
        self._test_station = None

    def clean_up(self):
        if self.restart_beamformer:
            self._test_station.start_beamformer()
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

        self.restart_beamformer = False 
        if stop_transmission == 1:
            self.restart_beamformer = self._test_station.tiles[0].beamformer_is_running()
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
                self._logger.error(f"Tile {n} FPGA1 not initialising. Test FAILED")
                errors += 1
            if tile['fpga2.regfile.status.ddr_init_done'] == 0:
                self._logger.error(f"Tile {n} FPGA2 not initialising. Test FAILED")
                errors += 1
            if errors > 0:
                return 1

        self.ddr_size_list = []
        # Preparing test
        if last_addr == -1:
            for index, tile in enumerate(self._test_station.tiles):
                if hasattr(tile.tpm, "get_board_info"):
                    ddr_size = int(tile.tpm.get_board_info()["DDR_SIZE_GB"])
                else:
                    ddr_size = 1

                self.ddr_size_list.append(ddr_size)
                self._logger.info(f"Tile {index}, ddr size: {int(2*ddr_size)} GB")
                last_addr = (ddr_size*0x8000000) - 8
                self._logger.info(f"Tile {index}, last_addr: {last_addr}")

                self._test_station.tiles[index]['fpga1.ddr_simple_test.last_addr'] = last_addr
                self._test_station.tiles[index]['fpga2.ddr_simple_test.last_addr'] = last_addr
        else:
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

    def execute(self, duration=20, first_addr=0x0, last_addr=-1, burst_length=0, pause=0,
                reset_dsp=0, reset_ddr=1, stop_transmission=1, stop_on_error=False):
        # -1 in last_addr will test the TPM's max capacity
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
        current_time = 0
        previous_errors = 0
        checks = [0 for index in range(len(self._test_station.tiles))]
        while current_time < duration:
            time.sleep(1)
            curr_rd_cnt_fpga1 = self._test_station['fpga1.ddr_simple_test.rd_cnt']
            curr_rd_cnt_fpga2 = self._test_station['fpga2.ddr_simple_test.rd_cnt']
            for n, tile in enumerate(self._test_station.tiles):
                # If ddr is larger than 8 GB wait for size/8s between checks
                if self.ddr_size_list[n] <= 4 or (current_time - 1) % int((self.ddr_size_list[n]/4)) == 0:
                    checks[n] += 1
                    if prev_rd_cnt_fpga1[n] == curr_rd_cnt_fpga1[n]:
                        self._logger.error(f"Tile {n} FPGA1 test is not running")
                        errors += 1
                    if prev_rd_cnt_fpga2[n] == curr_rd_cnt_fpga2[n]:
                        self._logger.error(f"Tile {n} FPGA2 test is not running")
                        errors += 1

                    for fpga in ["fpga1", "fpga2"]:
                        if self._test_station[f'{fpga}.ddr_simple_test.error'][n] == 1:
                            self._logger.error(f"Tile {n} {fpga} error. Test FAILED.")
                            if self._test_station.tiles[0].has_register("fpga1.ddr_simple_test.error_loc_0"):
                                self._logger.error(f"ERROR location bits (4 bit resolution, 127 - 0) : {hex(self._test_station[f'{fpga}.ddr_simple_test.error_loc_0'][n])}")
                                self._logger.error(f"ERROR location bits (4 bit resolution, 255 - 128) : {hex(self._test_station[f'{fpga}.ddr_simple_test.error_loc_1'][n])}")
                                self._logger.error(f"ERROR location bits (4 bit resolution, 383 - 256) : {hex(self._test_station[f'{fpga}.ddr_simple_test.error_loc_2'][n])}")
                                self._logger.error(f"ERROR location bits (4 bit resolution, 511 - 384) : {hex(self._test_station[f'{fpga}.ddr_simple_test.error_loc_3'][n])}")
                                error_rd_cnt = self._test_station[f'{fpga}.ddr_simple_test.error_rd_cnt'][n]
                                error_addr = first_addr + (error_rd_cnt*8) % (last_addr - first_addr)
                                self._logger.error(f"ERROR address : {hex(error_addr)}")
                            else:
                                self._logger.warning("Cant give DDR error location or address, this version of the firmware does not support it")
                            errors += 1

                    if (self._test_station['fpga1.ddr_if.status'][n] & 0xF00) != (fpga1_status[n] & 0xF00):
                        self._logger.error(f"Tile {n} FPGA1 error. DDR reinitialised during test error. Test FAILED..")
                        errors += 1
                    if (self._test_station['fpga2.ddr_if.status'][n] & 0xF00) != (fpga2_status[n] & 0xF00):
                        self._logger.error(f"Tile {n} FPGA2 error. DDR reinitialised during test error. Test FAILED.")
                        errors += 1

                    prev_rd_cnt_fpga1[n] = curr_rd_cnt_fpga1[n]
                    prev_rd_cnt_fpga2[n] = curr_rd_cnt_fpga2[n]

            if errors > previous_errors:
                previous_errors = deepcopy(errors)
                self._logger.info(f"Test running with {errors} errors detected, elapsed time {current_time + 1} seconds")
                if stop_on_error:

                    self.stop()
                    input("ERROR FOUND: Press enter to continue")
                    self._logger.info("Resetting ddr test")
                    current_time = -1
                    prev_rd_cnt_fpga1 = [0] * nof_tiles
                    prev_rd_cnt_fpga2 = [0] * nof_tiles
                    for fpga in ["fpga1", "fpga2"]:
                        self._test_station[f'{fpga}.ddr_simple_test.error'] = 0
                        self._test_station[f'{fpga}.regfile.reset.ddr_rst'] = 1
                        self._test_station[f'{fpga}.regfile.reset.ddr_rst'] = 0
                    time.sleep(1)
                    self.start()
                else:
                    self.stop()
                    self.clean_up()
                    self._logger.error("DDR Test FAILED!")
                    return 1
            elif errors == 0:
                self._logger.info(f"Test running with no errors detected, elapsed time {current_time + 1} seconds")
            else:
                self._logger.info(f"Test running with {errors} errors detected, elapsed time {current_time + 1} seconds")
            current_time += 1

        for index, check_num in enumerate(checks):
            if check_num == 0:
                self._logger.error(f"No ddr checks happened for tile {index}")
                errors += 1

        self.stop()
        self.clean_up()

        if errors > 0:
            self._logger.error("DDR Test FAILED!")
            return 1
        else:
            self._logger.info("Test PASSED!")
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
