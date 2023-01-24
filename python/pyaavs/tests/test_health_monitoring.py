from pyaavs import station
from config_manager import ConfigManager

from functools import reduce
import test_functions as tf
import logging
import operator

# Add to this list any monitoring points that are expected to fail
MON_POINT_SKIP = [
    'dsp.station_beamf',          # Can be removed once MCCS-1307 is complete
    'io.udp_if.drop_count.FPGA0', # Can be removed once MCCS-1308 is complete
    'io.udp_if.drop_count.FPGA1', # Can be removed once MCCS-1308 is complete
    'timing.pps.status'           # Can be removed once MCCS-1282 is complete
]

class TestHealthMonitoring():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self.errors = 0

    def clean_up(self):
        if self.errors > 0:
            self._logger.error(f"Health Monitoring Test FAILED! {self.errors} Errors")
            return 1
        self._logger.info("Health Monitoring Test PASSED!")
        return 0
        
    def get_health_by_path(health, path_list):
        return reduce(operator.getitem, path_list, health)

    def recursive_check_health_dict(expected_health, current_health, key_list):
        for name, value in expected_health.items():
            key_list.append(name)
            if not isinstance(value, dict):
                if '.'.join(key_list) in MON_POINT_SKIP:
                    print(f"Skipping checks for {'->'.join(key_list)}.")
                    key_list.pop()
                else:
                    expected_value = value
                    try: 
                        current_value = get_health_by_path(current_health, key_list)
                    except KeyError:
                        print(f"{'->'.join(key_list)} expected but not found in Health Status.  Test FAILED")
                        self.errors += 1
                        key_list.pop()
                        break
                    if current_value != expected_value:
                        print(f"{'->'.join(key_list)} is {current_value}, expected {expected_value}. Test FAILED")
                        self.errors+=1
                    else:
                        print(f"{'->'.join(key_list)} is {expected_value} as expected.")
                    key_list.pop()
            else:
                recursive_check_health_dict(value, current_health, key_list)
        if key_list:
            key_list.pop()
        return

    def execute(self, placeholder=None):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._logger.info("Executing Health Monitoring test")

        self.errors = 0

        try:
            self._test_station['fpga1.pps_manager.pps_errors']
        except:
            self._logger.error("Health Monitoring Test not supported by FPGA firmware!")
            self._logger.error("Health Monitoring Test FAILED!")
            return 1
        
        for n, tile in enumerate(self._test_station.tiles):
            EXP_TEMP, EXP_VOLTAGE, EXP_CURRENT = tile.tile_health_monitor.get_health_acceptance_values()
            expected_health = tile.tile_health_monitor.get_exp_health()
            # TODO: combine expected_health dict, EXP_TEMP, EXP_VOLTAGE & EXP_CURRENT
            tpm_version = tile.tpm_version()
            if not tile.tpm.adas_enabled:
                self._logger.info("ADAs disabled. Skipping checks for ADA voltages.")

            # UUT - Clear and Get Health Status
            tile.enable_health_monitoring()
            tile.clear_health_status()
            health_dict = tile.get_health_status()

            # Preliminary Checks
            if EXP_TEMP.keys() != health_dict['temperature'].keys():
                self._logger.error(f"Got {len(health_dict['temperature'].keys())} temperature measurements, expected {len(EXP_TEMP.keys())}. Test FAILED")
                self.errors += 1
            if EXP_VOLTAGE.keys() != health_dict['voltage'].keys():
                self._logger.error(f"Got {len(health_dict['voltage'].keys())} voltage measurements, expected {len(EXP_VOLTAGE.keys())}. Test FAILED")
                self.errors += 1
            if EXP_CURRENT.keys() != health_dict['current'].keys():
                self._logger.error(f"Got {len(health_dict['current'].keys())} current measurements, expected {len(EXP_CURRENT.keys())}. Test FAILED")
                self.errors += 1
        
            # Check Temperature Measurements
            for name, value in health_dict['temperature'].items():
                if value > EXP_TEMP[name]['max'] or value < EXP_TEMP[name]['min']:
                    self._logger.error(f"TPM{n} {name} Temperature is {value}\N{DEGREE SIGN}C, outside acceptable range {EXP_TEMP[name]['min']}\N{DEGREE SIGN}C - {EXP_TEMP[name]['max']}\N{DEGREE SIGN}C. Test FAILED")
                    self.errors += 1
                else:
                    self._logger.info(f"TPM{n} {name} Temperature is {value}\N{DEGREE SIGN}C, within acceptable range {EXP_TEMP[name]['min']}\N{DEGREE SIGN}C - {EXP_TEMP[name]['max']}\N{DEGREE SIGN}C.")

            # Check Voltage Measurements
            for name, value in health_dict['voltage'].items():
                if EXP_VOLTAGE[tpm_version][name].get('skip', False):
                    self._logger.info(f"Skipping checks for TPM{n} voltage {name}.")
                else:
                    if value > EXP_VOLTAGE[tpm_version][name]['max'] or value < EXP_VOLTAGE[tpm_version][name]['min']:
                        self._logger.error(f"TPM{n} Voltage {name} is {value}V, outside acceptable range {EXP_VOLTAGE[tpm_version][name]['min']}V - {EXP_VOLTAGE[tpm_version][name]['max']}V. Test FAILED")
                        self.errors += 1
                    else:
                        self._logger.info(f"TPM{n} Voltage {name} is {value}V, within acceptable range {EXP_VOLTAGE[tpm_version][name]['min']}V - {EXP_VOLTAGE[tpm_version][name]['max']}V.")

            # Check Current Measurements
            for name, value in health_dict['current'].items():
                if EXP_CURRENT[tpm_version][name].get('skip', False):
                    self._logger.info(f"Skipping checks for TPM{n} current {name}.")
                else:
                    if value > EXP_CURRENT[tpm_version][name]['max'] or value < EXP_CURRENT[tpm_version][name]['min']:
                        self._logger.error(f"TPM{n} Current {name} is {value}A, outside acceptable range {EXP_CURRENT[tpm_version][name]['min']}A - {EXP_CURRENT[tpm_version][name]['max']}A. Test FAILED")
                        self.errors += 1
                    else:
                        self._logger.info(f"TPM{n} Current {name} is {value}A, within acceptable range {EXP_CURRENT[tpm_version][name]['min']}A - {EXP_CURRENT[tpm_version][name]['max']}A.")

            # Check the remainder of monitoring points
            # Here all points with static expected values, not ranges are verified.
            # If an expected monitoring point is missing from health_dict an error is produced. 
            # Any extra monitoring points in health_dict, not known to expected_health are ignored.
            recursive_check_health_dict(expected_health, health_dict, [])

            return self.clean_up()

if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
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
