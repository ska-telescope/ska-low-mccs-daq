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


class TestHealthMonitoring():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config

    def clean_up(self):
        return

    def execute(self, placeholder=None):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._logger.info("Executing Health Monitoring test")

        errors = 0

        try:
            self._test_station['fpga1.pps_manager.pps_errors']
        except:
            self._logger.error("Health Monitoring Test not supported by FPGA firmware!")
            self._logger.error("Health Monitoring Test FAILED!")
            self.clean_up()
            return 1
        
        for n, tile in enumerate(self._test_station.tiles):
            EXP_TEMP, EXP_VOLTAGE, EXP_CURRENT = tile.tile_health_monitor.get_health_acceptance_values()
            tpm_version = tile.tpm_version()
            if not tile.tpm.adas_enabled:
                self._logger.info("ADAs disabled. Skipping checks for ADA voltages.")

            # UUT - Clear and Get Health Status
            tile.enable_health_monitoring()
            tile.clear_health_status()
            health_dict = tile.get_health_status()

            # Check Temperature Measurements
            for name, value in health_dict['temperature'].items():
                if value > EXP_TEMP[name]['max'] or value < EXP_TEMP[name]['min']:
                    self._logger.error(f"TPM{n} {name} Temperature is {value}\N{DEGREE SIGN}C, outside acceptable range {EXP_TEMP[name]['min']}\N{DEGREE SIGN}C - {EXP_TEMP[name]['max']}\N{DEGREE SIGN}C. Test FAILED")
                    errors += 1
                else:
                    self._logger.info(f"TPM{n} {name} Temperature is {value}\N{DEGREE SIGN}C, within acceptable range {EXP_TEMP[name]['min']}\N{DEGREE SIGN}C - {EXP_TEMP[name]['max']}\N{DEGREE SIGN}C.")

            # Check Voltage Measurements
            for name, value in health_dict['voltage'].items():
                if EXP_VOLTAGE[tpm_version][name].get('skip', False):
                    self._logger.info(f"Skipping checks for TPM{n} voltage {name}.")
                else:
                    if value > EXP_VOLTAGE[tpm_version][name]['max'] or value < EXP_VOLTAGE[tpm_version][name]['min']:
                        self._logger.error(f"TPM{n} Voltage {name} is {value}V, outside acceptable range {EXP_VOLTAGE[tpm_version][name]['min']}V - {EXP_VOLTAGE[tpm_version][name]['max']}V. Test FAILED")
                        errors += 1
                    else:
                        self._logger.info(f"TPM{n} Voltage {name} is {value}V, within acceptable range {EXP_VOLTAGE[tpm_version][name]['min']}V - {EXP_VOLTAGE[tpm_version][name]['max']}V.")

            # Check Current Measurements
            for name, value in health_dict['current'].items():
                if EXP_CURRENT[tpm_version][name].get('skip', False):
                    self._logger.info(f"Skipping checks for TPM{n} current {name}.")
                else:
                    if value > EXP_CURRENT[tpm_version][name]['max'] or value < EXP_CURRENT[tpm_version][name]['min']:
                        self._logger.error(f"TPM{n} Current {name} is {value}A, outside acceptable range {EXP_CURRENT[tpm_version][name]['min']}A - {EXP_CURRENT[tpm_version][name]['max']}A. Test FAILED")
                        errors += 1
                    else:
                        self._logger.info(f"TPM{n} Current {name} is {value}A, within acceptable range {EXP_CURRENT[tpm_version][name]['min']}A - {EXP_CURRENT[tpm_version][name]['max']}A.")


        if errors > 0:
            self._logger.error(f"Health Monitoring Test FAILED! {errors} Errors")
            self.clean_up()
            return 1
        else:
            self._logger.info("Health Monitoring Test PASSED!")
            self.clean_up()
            return 0


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    # parser.add_option("-d", "--duration", action="store", dest="duration",
    #                   default="16", help="Test duration in seconds [default: 16, infinite: -1]")
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_health_monitoring.log',
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

    test_logger = logging.getLogger('TEST_HEALTH_MONITORING')

    test_inst = TestHealthMonitoring(tpm_config, test_logger)
    test_inst.execute()
