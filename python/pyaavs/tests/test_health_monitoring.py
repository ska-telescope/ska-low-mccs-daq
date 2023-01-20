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

# Should these dictionaries move to Health monitoring class and
# be returned with a get_FAT_values or get_health_acceptance etc.
EXP_VOLTAGE = {
    "tpm_v1_2": {
        "5V0"         : { "min": 4.750, "max": 5.250},
        "FPGA0_CORE"  : { "min": 0.900, "max": 1.000},
        "FPGA1_CORE"  : { "min": 0.900, "max": 1.000},
        "MGT_AV"      : { "min": 0.950, "max": 1.050},
        "MGT_AVTT"    : { "min": 1.140, "max": 1.260},
        "SW_AVDD1"    : { "min": 1.560, "max": 1.730},
        "SW_AVDD2"    : { "min": 2.560, "max": 2.840},
        "SW_AVDD3"    : { "min": 3.320, "max": 3.680},
        "VCC_AUX"     : { "min": 1.710, "max": 1.890},
        "VIN"         : { "min": 11.40, "max": 12.60, "skip": True}, # TODO: add support for this measurement
        "VM_ADA0"     : { "min": 3.030, "max": 3.560},
        "VM_ADA1"     : { "min": 3.030, "max": 3.560},
        "VM_AGP0"     : { "min": 0.900, "max": 1.060},
        "VM_AGP1"     : { "min": 0.900, "max": 1.060},
        "VM_AGP2"     : { "min": 0.900, "max": 1.060},
        "VM_AGP3"     : { "min": 0.900, "max": 1.060},
        "VM_CLK0B"    : { "min": 3.030, "max": 3.560},
        "VM_DDR0_VREF": { "min": 0.620, "max": 0.730},
        "VM_DDR0_VTT" : { "min": 0.620, "max": 0.730},
        "VM_FE0"      : { "min": 3.220, "max": 3.780},
        "VM_MAN1V2"   : { "min": 1.100, "max": 1.300, "skip": True}, # Not currently turned on
        "VM_MAN2V5"   : { "min": 2.300, "max": 2.700},
        "VM_MAN3V3"   : { "min": 3.030, "max": 3.560},
        "VM_MGT0_AUX" : { "min": 1.650, "max": 1.940},
        "VM_PLL"      : { "min": 3.030, "max": 3.560},
        "VM_ADA3"     : { "min": 3.030, "max": 3.560},
        "VM_DDR1_VREF": { "min": 0.620, "max": 0.730},
        "VM_DDR1_VTT" : { "min": 0.620, "max": 0.730},
        "VM_AGP4"     : { "min": 0.900, "max": 1.060},
        "VM_AGP5"     : { "min": 0.900, "max": 1.060},
        "VM_AGP6"     : { "min": 0.900, "max": 1.060},
        "VM_AGP7"     : { "min": 0.900, "max": 1.060},
        "VM_FE1"      : { "min": 3.220, "max": 3.780},
        "VM_DDR_VDD"  : { "min": 1.240, "max": 1.460},
        "VM_SW_DVDD"  : { "min": 1.520, "max": 1.780},
        "VM_MGT1_AUX" : { "min": 1.650, "max": 1.940},
        "VM_ADA2"     : { "min": 3.030, "max": 3.560},
        "VM_SW_AMP"   : { "min": 3.220, "max": 3.780, "skip": True}, # Not currently turned on
        "VM_CLK1B"    : { "min": 3.030, "max": 3.560}
    },
    # TPM 1.6 min and max ranges are taken from factory acceptance testing
    # See https://confluence.skatelescope.org/x/nDhED
    "tpm_v1_6": {
        "VREF_2V5"    : { "min": 2.370, "max": 2.630, "skip": True}, # TODO: add support for this measurement
        "MGT_AVCC"    : { "min": 0.850, "max": 0.950},
        "MGT_AVTT"    : { "min": 1.140, "max": 1.260},
        "SW_AVDD1"    : { "min": 1.040, "max": 1.160},
        "SW_AVDD2"    : { "min": 1.850, "max": 2.050},
        "AVDD3"       : { "min": 2.370, "max": 2.600},
        "MAN_1V2"     : { "min": 1.140, "max": 1.260},
        "DDR0_VREF"   : { "min": 0.570, "max": 0.630},
        "DDR1_VREF"   : { "min": 0.570, "max": 0.630},
        "VM_DRVDD"    : { "min": 1.710, "max": 1.890},
        "VIN"         : { "min": 11.40, "max": 12.60},
        "MON_3V3"     : { "min": 3.130, "max": 3.460},
        "MON_1V8"     : { "min": 1.710, "max": 1.890},
        "MON_5V0"     : { "min": 4.690, "max": 5.190},
        "VM_ADA0"     : { "min": 0.000, "max": 0.000},
        "VM_ADA1"     : { "min": 0.000, "max": 0.000},
        "VM_AGP0"     : { "min": 0.840, "max": 0.990},
        "VM_AGP1"     : { "min": 0.840, "max": 0.990},
        "VM_AGP2"     : { "min": 0.840, "max": 0.990},
        "VM_AGP3"     : { "min": 0.840, "max": 0.990},
        "VM_CLK0B"    : { "min": 3.040, "max": 3.560},
        "VM_DDR0_VTT" : { "min": 0.550, "max": 0.650},
        "VM_FE0"      : { "min": 3.220, "max": 3.780},
        "VM_MGT0_AUX" : { "min": 1.660, "max": 1.940},
        "VM_PLL"      : { "min": 3.040, "max": 3.560},
        "VM_AGP4"     : { "min": 0.840, "max": 0.990},
        "VM_AGP5"     : { "min": 0.840, "max": 0.990},
        "VM_AGP6"     : { "min": 0.840, "max": 0.990},
        "VM_AGP7"     : { "min": 0.840, "max": 0.990},
        "VM_CLK1B"    : { "min": 3.040, "max": 3.560},
        "VM_DDR1_VDD" : { "min": 1.100, "max": 1.300},
        "VM_DDR1_VTT" : { "min": 0.550, "max": 0.650},
        "VM_DVDD"     : { "min": 1.010, "max": 1.190},
        "VM_FE1"      : { "min": 3.220, "max": 3.780},
        "VM_MGT1_AUX" : { "min": 1.660, "max": 1.940},
        "VM_SW_AMP"   : { "min": 3.220, "max": 3.780},
    }
}

EXP_CURRENT = {
    "tpm_v1_2": {
        "ACS_5V0_VI": { "min": 0.000, "max": 25.00, "skip": True}, # TODO: add support for this measurement
        "ACS_FE0_VI": { "min": 0.000, "max": 4.000, "skip": True}, # known defective
        "ACS_FE1_VI": { "min": 0.000, "max": 4.000, "skip": True}  # known defective
    },
    # TPM 1.6 min and max ranges are taken from factory acceptance testing
    # See https://confluence.skatelescope.org/x/nDhED
    "tpm_v1_6": {
        "FE0_MVA"     : { "min": 1.930, "max": 2.270},
        "FE1_MVA"     : { "min": 2.020, "max": 2.380}
    }
}

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
            tile.enable_health_monitoring()
            tile.clear_health_status()
            health_dict = tile.get_health_status()
            tpm_version = tile.tpm_version()
            skip_ADA_voltages = not tile.tpm._enable_ada
            print(f'Skip ADAs? {skip_ADA_voltages}')

            # Check Voltage and Current Measurements
            for name, value in health_dict['voltage'].items():
                if EXP_VOLTAGE[tpm_version][name].get('skip', False):
                    self._logger.info(f"Skipping checks for TPM{n} voltage {name}.")
                else:
                    if value > EXP_VOLTAGE[tpm_version][name]['max'] or value < EXP_VOLTAGE[tpm_version][name]['min']:
                        self._logger.error(f"TPM{n} Voltage {name} is {value} V, outside acceptable range {EXP_VOLTAGE[tpm_version][name]['min']} V - {EXP_VOLTAGE[tpm_version][name]['max']} V. Test FAILED")
                        errors += 1
            for name, value in health_dict['current'].items():
                if EXP_CURRENT[tpm_version][name].get('skip', False):
                    self._logger.info(f"Skipping checks for TPM{n} current {name}.")
                else:
                    if value > EXP_CURRENT[tpm_version][name]['max'] or value < EXP_CURRENT[tpm_version][name]['min']:
                        self._logger.error(f"Current {name} outside acceptable range. Test FAILED")
                        errors += 1


        if errors > 0:
            self._logger.error("Health Monitoring Test FAILED!")
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
