from pyaavs import station
from config_manager import ConfigManager
from time import sleep, strftime, localtime
import logging            
import csv

csv_header = [
    "timestamp", 
    "tile number",
    "board temperature",
    "pps period (s)",
    "pps delay (phase)", 
    "pps phase max drift (ns)"
   ]
   
class TestSynchronisation:
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self.errors = 0
        self.tiles_with_errors = []
    
    def clean_up(self):
        if self.errors > 0:
            self._logger.error(f"Synchronisation Test FAILED! {self.errors} Errors")
            return 1
        self._logger.info("Synchronisation Test PASSED!")
        return 0

    def execute(self, duration=120):
        global nof_tiles
        max_pps_delay = 0
        min_pps_delay = 100

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._logger.info("Executing Synchronisation test")
        nof_tiles = len(self._test_station.tiles) 
        self.errors = 0
        current_time = 0
        
        with open("test_log/test_synchronisation.csv", mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(csv_header)
        
        while current_time < duration:
            sleep(1)
            for n, tile in enumerate(self._test_station.tiles):
                  
                # Check PPS Phase between FPGAs
                f0_pps_delay = tile["fpga1.pps_manager.sync_phase.cnt_hf_pps"]
                f1_pps_delay = tile["fpga2.pps_manager.sync_phase.cnt_hf_pps"]
                diff = abs(f0_pps_delay - f1_pps_delay) * 1.25
                if abs(f0_pps_delay - f1_pps_delay) > 1:
                    self._logger.error(f"TPM{n} PPS phase difference between FPGAs is too large. FPGA0 Sync Phase {f0_pps_delay}, FPGA1 Sync Phase {f1_pps_delay}. Difference {diff:.2f} ns. Test Failed.")
                    self.errors += 1
                elif f0_pps_delay != f1_pps_delay:
                    self._logger.warning(f"TPM{n} PPS phase is not consistent between FPGAs. FPGA0 Sync Phase {f0_pps_delay}, FPGA1 Sync Phase {f1_pps_delay}. Difference {diff:.2f} ns")
                
                # Check Tile PPS Phase
                pps_delay = tile.get_pps_delay()
                max_pps_delay = max(max_pps_delay, pps_delay)
                min_pps_delay = min(min_pps_delay, pps_delay)
                diff = abs(max_pps_delay - min_pps_delay) * 1.25
                   
                if abs(max_pps_delay - min_pps_delay) > 4:   # More than 5 ns
                    self._logger.error(f"TPM{n} PPS phase has drifted by more than 5 ns. Max Sync Phase {max_pps_delay}, Min Sync Phase {min_pps_delay}. Difference {diff:.2f} ns. Test Failed.")
                    self.errors += 1
                                    
                # Get Temp
                temperature_dict = tile.get_health_status(group="temperatures")
                tile_temp = temperature_dict["temperatures"]["board"]
                
                for fpga in ['fpga1', 'fpga2']:
                    pps_detected = tile[f'{fpga}.pps_manager.pps_detected']
                    if not pps_detected:
                        self._logger.error(f"TPM{n} external PPS not detected. Test Failed.")
                        self.errors += 1
                    count = tile[f'{fpga}.pps_manager.pps_count']
                    exp_count = tile[f'{fpga}.pps_manager.pps_exp_tc']
                    period = (count + 1) / (exp_count + 1)
                    if period != 1:
                        self._logger.error(f"TPM{n} PPS period is {period} s. Expected 1.0 s. Test Failed.")
                        self.errors += 1
                
                with open("test_log/test_synchronisation.csv", mode="a", newline="") as file:
                    timestamp = strftime("%Y-%m-%d-%H-%M-%S", localtime())
                    writer = csv.writer(file)
                    writer.writerow([timestamp, n, tile_temp, period, pps_delay, diff])
                    
            if current_time % 10 == 9:  # Only print updates every 10 seconds
                if not self.errors:
                    self._logger.info(f"Test running with no errors detected, elapsed time {current_time + 1} seconds")
                else:
                    self._logger.info(f"Test running with {self.errors} errors detected, elapsed time {current_time + 1} seconds")
            
            current_time += 1

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
                        filename='test_log/test_synchronisation.log',
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

    test_logger = logging.getLogger('TEST_SYNCHRONISATION')

    test_inst = TestSynchronisation(tpm_config, test_logger)
    test_inst.execute()
