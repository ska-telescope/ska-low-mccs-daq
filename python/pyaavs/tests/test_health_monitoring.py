from pyaavs import station
from config_manager import ConfigManager

from functools import reduce
import test_functions as tf
import logging
import operator

# Add to this list any monitoring points that are expected to fail
MON_POINT_SKIP = []

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
            comparison_value = value if value is not None else -20000.0 #Arbitrary negative value to represent None
            if comparison_value > expected[name]['max'] or comparison_value < expected[name]['min']:
                if expected[name].get('skip', False):
                    self._logger.warning(f"TPM{tpm_id} {name} {key.capitalize()} is {value}{unit}, outside acceptable range {expected[name]['min']}{unit} - {expected[name]['max']}{unit}. Expected Failure")
                else:
                    self._logger.error(f"TPM{tpm_id} {name} {key.capitalize()} is {value}{unit}, outside acceptable range {expected[name]['min']}{unit} - {expected[name]['max']}{unit}. Test FAILED")
                    self.errors += 1
            else:
                self._logger.info(f"TPM{tpm_id} {name} {key.capitalize()} is {value}{unit}, within acceptable range {expected[name]['min']}{unit} - {expected[name]['max']}{unit}.")
        return
        
    def get_health_by_path(self, health, path_list):
        return reduce(operator.getitem, path_list, health)

    def recursive_check_health_dict(self, expected_health, current_health, key_list, tpm_id):
        for name, value in expected_health.items():
            key_list.append(name)
            if key_list == ['temperature']:
                self.check_analog_measurements('temperature', '\N{DEGREE SIGN}C', expected_health['temperature'], current_health['temperature'], tpm_id)
                key_list.pop()
                continue
            if key_list == ['voltage']:
                self.check_analog_measurements('voltage', 'V', expected_health['voltage'], current_health['voltage'], tpm_id)
                key_list.pop()
                continue
            if key_list == ['current']:
                self.check_analog_measurements('current', 'A', expected_health['current'], current_health['current'], tpm_id)
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
                self.recursive_check_health_dict(value, current_health, key_list, tpm_id)
        if key_list:
            key_list.pop()
        return

    def test_ddr_parity_error_injection_and_detection(self, tile):
        def check_parity_error(expected_dict):
            error_dict = tile.check_ddr_parity_error_counter()
            for fpga in ['FPGA0', 'FPGA1']:
                if error_dict[fpga] != expected_dict[fpga]:
                    print(f"{fpga} DDR parity error count is {error_dict[fpga]}, expected {expected_dict[fpga]}.  Test FAILED")
                    self.errors += 1
                else:
                    print(f"{fpga} DDR parity error count is {error_dict[fpga]} as expected.")
            return
        print("Testing DDR parity error injection and detection...")
        print("Clearing DDR parity error count for both FPGAs.")
        tile.clear_station_beamformer_status()
        check_parity_error({'FPGA0': 0, 'FPGA1': 0})
        tile.inject_ddr_parity_error(fpga_id=0)
        check_parity_error({'FPGA0': 1, 'FPGA1': 0})
        tile.inject_ddr_parity_error(fpga_id=0)
        check_parity_error({'FPGA0': 2, 'FPGA1': 0})
        tile.inject_ddr_parity_error(fpga_id=1)
        tile.inject_ddr_parity_error(fpga_id=1)
        tile.inject_ddr_parity_error(fpga_id=1)
        check_parity_error({'FPGA0': 2, 'FPGA1': 3})
        print("Clearing DDR parity error count for FPGA0.")
        tile.clear_station_beamformer_status(fpga_id=0)
        check_parity_error({'FPGA0': 0, 'FPGA1': 3})
        tile.inject_ddr_parity_error()
        check_parity_error({'FPGA0': 1, 'FPGA1': 4})
        print("Clearing DDR parity error count for both FPGAs.")
        tile.clear_station_beamformer_status()
        check_parity_error({'FPGA0': 0, 'FPGA1': 0})
        return

    def execute(self, placeholder=None):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._logger.info("Executing Health Monitoring test")

        self.errors = 0
        
        for n, tile in enumerate(self._test_station.tiles):
            
            # Bitfiles sbf410 and older do not support health monitoring
            # Check for existance of moved pps register
            if not tile.tpm.has_register('fpga1.pps_manager.pps_errors'):
                self._logger.error("Health Monitoring Test not supported by FPGA firmware!")
                self._logger.error("Health Monitoring Test FAILED!")
                return 1
            
            # Bitfiles sbf415 and older do not pass PPS monitoring checks
            # check for existance of additional pps_exp_tc register
            if not tile.tpm.has_register('fpga1.pps_manager.pps_exp_tc'):
                self._logger.warning("FPGA Firmware does not support updated PPS validation. PPS checks will be skipped.")
                MON_POINT_SKIP.append('timing.pps.status')

            expected_health = tile.get_exp_health()
            if not tile.tpm.adas_enabled:
                self._logger.info("ADAs disabled. Skipping checks for ADA voltages.")

            # UUT - Clear and Get Health Status
            tile.enable_health_monitoring()
            tile.clear_health_status()
            health_dict = tile.get_health_status()

            # If an expected monitoring point is missing from health_dict an error is produced. 
            # Any extra monitoring points in health_dict, not known to expected_health are ignored.
            self.recursive_check_health_dict(expected_health, health_dict, [], n)

            # Test Station Beamformer DDR Parity Error Injection & Dectection
            self.test_ddr_parity_error_injection_and_detection(tile)

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
