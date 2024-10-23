import sys
import yaml
import logging
from pyaavs import station
from copy import copy

class ConfigManager():
    def __init__(self, test_config_file=None):
        self.default_config = {
            "daq_eth_if": None,              # DAQ Ethernet Interface
            "single_tpm_test_station_idx": 0,  # Single TPM tests will be run on the TPM identified by index within the station
            "gigabit_only": False,             # Gigabit only test
            "total_bandwidth": 400e6,          # Total Bandwidth
            "pfb_nof_channels": 512,           # nof_frequency_channels
            "antennas_per_tile": 16,           # Number of antennas per tile
        }
        self.config_dict = copy(self.default_config)
        if test_config_file is not None:
            with open(test_config_file, "r") as yml_file:
                file_contents = yaml.safe_load(yml_file) or {}
            self.config_dict.update(file_contents)

    def get_test_config_param(self, param):
        if param in self.config_dict.keys():
            return self.config_dict[param]
        else:
            logging.error("Unknown test config parameter: %s", param)
            sys.exit(-1)

    def get_test_tpm_ip(self, station_configuration):
        tpm_idx = self.get_test_config_param('single_tpm_test_station_idx')
        try:
            tpm_ip = station_configuration['tiles'][tpm_idx]
        except:
            logging.error("Error retrieving TPM IP index %d from station configuration file", tpm_idx)
            sys.exit(-1)
        return tpm_ip

    def apply_test_configuration(self, command_line_configuration):
        station.load_configuration_file(command_line_configuration.config)

        tpm_ip = self.get_test_tpm_ip(station.configuration)
        try:
            if command_line_configuration.tpm_ip != "":
                tpm_ip = command_line_configuration.tpm_ip
        except:
            pass

        tpm_port = station.configuration['network']['lmc']['tpm_cpld_port']
        try:
            if command_line_configuration.tpm_port != "":
                tpm_port = command_line_configuration.tpm_ip
        except:
            pass

        station.configuration['station']['program'] = False
        station.configuration['station']['initialise'] = False
        station.configuration['single_tpm_config'] = {'ip': tpm_ip, 'port': tpm_port}
        station.configuration['eth_if'] = self.get_test_config_param('daq_eth_if')
        station.configuration['test_config'] = self.config_dict

        return station.configuration
