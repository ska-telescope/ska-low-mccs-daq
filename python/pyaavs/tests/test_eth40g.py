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


class TestEth40g():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self._test_station = None

    def clean_up(self):
        return

    def execute(self, duration=8, single_packet_mode=False, ipg=1):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        errors = 0

        self._logger.debug("Preparing 40G test, duration %d seconds" % duration)

        # Resetting DSP to get exclusive access to DDR
        # self._test_station['fpga1.regfile.reset.dsp_rst'] = 1
        # self._test_station['fpga2.regfile.reset.dsp_rst'] = 1

        time.sleep(0.5)

        # Starting test
        for n, tile in enumerate(self._test_station.tiles):
            if tile.start_40g_test(single_packet_mode, ipg) > 0:
                self._logger.error("ETH40G Test FAILED! Not possible to start test on Tile %d" % n)
                self.clean_up()
                return 1

        for t in range(duration):
            time.sleep(1)
            for n, tile in enumerate(self._test_station.tiles):
                tx_pkt_cnt_fpga1 = tile['fpga1.xg_udp.core0_test_tx_pkt_cnt']
                tx_pkt_cnt_fpga2 = tile['fpga2.xg_udp.core0_test_tx_pkt_cnt']
                rx_pkt_cnt_fpga1 = tile['fpga1.xg_udp.core0_test_rx_pkt_cnt']
                rx_pkt_cnt_fpga2 = tile['fpga2.xg_udp.core0_test_rx_pkt_cnt']
                self._logger.info("Tile %d FPGA1 TX packets:  %d" % (n, tx_pkt_cnt_fpga1))
                self._logger.info("Tile %d FPGA1 RX packets:  %d" % (n, rx_pkt_cnt_fpga1))
                self._logger.info("Tile %d FPGA2 TX packets:  %d" % (n, tx_pkt_cnt_fpga2))
                self._logger.info("Tile %d FPGA2 RX packets:  %d" % (n, rx_pkt_cnt_fpga2))

                if rx_pkt_cnt_fpga1 == 0 and t == 0:
                    self._logger.error("Tile %d FPGA1 not receiving packets. Test FAILED." % n)
                    errors += 1
                if rx_pkt_cnt_fpga2 == 0 and t == 0:
                    self._logger.error("Tile %d FPGA2 not receiving packets. Test FAILED." % n)
                    errors += 1

                if tile['fpga1.xg_udp.core0_test_status.error'] == 1:
                    self._logger.error("Tile %d FPGA1 error. Test FAILED." % n)
                    errors += 1
                if tile['fpga2.xg_udp.core0_test_status.error'] == 1:
                    self._logger.error("Tile %d FPGA2 error. Test FAILED." % n)
                    errors += 1

            if errors == 0:
                self._logger.info("Test running with no errors detected, elapsed time: %d seconds" % (t+1))
            else:
                break

        self._logger.info("----------------- Test Summary -----------------")
        for n, tile in enumerate(self._test_station.tiles):
            tile.stop_40g_test()
            self._logger.info("Tile %d Test result:" % n)
            tx_pkt_cnt_fpga1 = tile['fpga1.xg_udp.core0_test_tx_pkt_cnt']
            tx_pkt_cnt_fpga2 = tile['fpga2.xg_udp.core0_test_tx_pkt_cnt']
            rx_pkt_cnt_fpga1 = tile['fpga1.xg_udp.core0_test_rx_pkt_cnt']
            rx_pkt_cnt_fpga2 = tile['fpga2.xg_udp.core0_test_rx_pkt_cnt']
            test_error_detected_fpga1 = tile['fpga1.xg_udp.core0_test_status.error']
            test_error_detected_fpga2 = tile['fpga2.xg_udp.core0_test_status.error']
            test_error_cnt_fpga1 = tile['fpga1.xg_udp.core0_test_error_cnt']
            test_error_cnt_fpga2 = tile['fpga2.xg_udp.core0_test_error_cnt']
            rx_crc_error_cnt_fpga1 = tile['fpga1.xg_udp.core0_rx_crc_error']
            rx_crc_error_cnt_fpga2 = tile['fpga2.xg_udp.core0_rx_crc_error']
            self._logger.info("Tile %d FPGA1 TX packets:  %d" % (n, tx_pkt_cnt_fpga1))
            self._logger.info("Tile %d FPGA1 RX packets:  %d" % (n, rx_pkt_cnt_fpga1))
            self._logger.info("Tile %d FPGA2 TX packets:  %d" % (n, tx_pkt_cnt_fpga2))
            self._logger.info("Tile %d FPGA2 RX packets:  %d" % (n, rx_pkt_cnt_fpga2))
            self._logger.info("Tile %d FPGA1 Error detected:  %d" % (n, test_error_detected_fpga1))
            self._logger.info("Tile %d FPGA2 Error detected:  %d" % (n, test_error_detected_fpga2))
            self._logger.info("Tile %d FPGA1 Error count:  %d" % (n, test_error_cnt_fpga1))
            self._logger.info("Tile %d FPGA2 Error count:  %d" % (n, test_error_cnt_fpga2))
            self._logger.info("Tile %d FPGA1 RX CRC Error count:  %d" % (n, rx_crc_error_cnt_fpga1))
            self._logger.info("Tile %d FPGA2 RX CRC Error count:  %d" % (n, rx_crc_error_cnt_fpga2))

            if test_error_detected_fpga1 == 1:
                self._logger.error("Tile %d FPGA1 TEST FAILED. Errors detected.")
                errors += 1
            if test_error_detected_fpga2 == 1:
                self._logger.error("Tile %d FPGA2 TEST FAILED. Errors detected.")
                errors += 1
            if tx_pkt_cnt_fpga2 != rx_pkt_cnt_fpga1:
                self._logger.error("Tile %d FPGA1 TEST FAILED. TX packets counts does not match RX packets count." % n)
                errors += 1
            if tx_pkt_cnt_fpga1 != rx_pkt_cnt_fpga2:
                self._logger.error("Tile %d FPGA2 TEST FAILED. TX packets counts does not match RX packets count." % n)
                errors += 1
        if errors > 0:
            self._logger.error("Test FAILED!")
            self.clean_up()
            return 1
        else:
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
                        filename='test_log/test_eth40g.log',
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

    test_logger = logging.getLogger('TEST_ETH40G')

    test_inst = TestEth40g(tpm_config, test_logger)
    test_inst.execute(int(conf.duration))
