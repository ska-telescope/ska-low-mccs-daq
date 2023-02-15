from pyaavs import station
from config_manager import ConfigManager

from functools import reduce
import test_functions as tf
import logging
import operator

# Add to this list any monitoring points that are expected to fail
MON_POINT_SKIP = [
    'dsp.station_beamf',                  # Can be removed once MCCS-1307 is complete
    'io.udp_if.linkup_loss_count.FPGA0',  # Can be removed once MCCS-1308 is complete
    'io.udp_if.linkup_loss_count.FPGA1',  # Can be removed once MCCS-1308 is complete
    'timing.pps.status'                   # Can be removed once MCCS-1282 is complete
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

    def check_analog_measurements(self, key, unit, expected, measurement, tpm_id):
        # Preliminary Checks
        if expected.keys() != measurement.keys():
            self._logger.error(f"Got {len(measurement.keys())} {key} measurements, expected {len(expected.keys())}. Test FAILED")
            self.errors += 1
        # Check Measurements
        for name, value in measurement.items():
            if expected[name].get('skip', False):
                self._logger.info(f"Skipping checks for TPM{tpm_id} {key.capitalize()} {name}.")
            else:
                if value > expected[name]['max'] or value < expected[name]['min']:
                    self._logger.error(f"TPM{tpm_id} {name} {key.capitalize()} is {value}{unit}, outside acceptable range {expected[name]['min']}{unit} - {expected[name]['max']}{unit}. Test FAILED")
                    self.errors += 1
                else:
                    self._logger.info(f"TPM{tpm_id} {name} {key.capitalize()} is {value}{unit}, within acceptable range {expected[name]['min']}{unit} - {expected[name]['max']}{unit}.")
        return
        
    def get_health_by_path(self, health, path_list):
        return reduce(operator.getitem, path_list, health)

    def recursive_check_health_dict(self, expected_health, current_health, key_list, tpm_id, tpm_version):
        for name, value in expected_health.items():
            key_list.append(name)
            if key_list == ['temperature']:
                self.check_analog_measurements('temperature', '\N{DEGREE SIGN}C', expected_health['temperature'], current_health['temperature'], tpm_id)
                key_list.pop()
                continue
            if key_list == ['voltage']:
                self.check_analog_measurements('voltage', 'V', expected_health['voltage'][tpm_version], current_health['voltage'], tpm_id)
                key_list.pop()
                continue
            if key_list == ['current']:
                self.check_analog_measurements('current', 'A', expected_health['current'][tpm_version], current_health['current'], tpm_id)
                key_list.pop()
                continue
            if not isinstance(value, dict):
                if '.'.join(key_list) in MON_POINT_SKIP:
                    print(f"Skipping checks for {'->'.join(key_list)}.")
                    key_list.pop()
                else:
                    expected_value = value
                    try: 
                        current_value = self.get_health_by_path(current_health, key_list)
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
                self.recursive_check_health_dict(value, current_health, key_list, tpm_id, tpm_version)
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
            expected_health = tile.get_exp_health()
            tpm_version = tile.tpm_version()
            if not tile.tpm.adas_enabled:
                self._logger.info("ADAs disabled. Skipping checks for ADA voltages.")

            # UUT - Clear and Get Health Status
            tile.enable_health_monitoring()
            tile.clear_health_status()
            health_dict = tile.get_health_status()

            # If an expected monitoring point is missing from health_dict an error is produced. 
            # Any extra monitoring points in health_dict, not known to expected_health are ignored.
            self.recursive_check_health_dict(expected_health, health_dict, [], n, tpm_version)

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
