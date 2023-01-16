import sys
import yaml
import logging
from pyaavs import station

class ConfigManager():
    def __init__(self, test_config_file="config/test_config.yml"):
        self.test_config_file = test_config_file
        fo = open(self.test_config_file, "r+")
        stream = fo.read()
        self.config_dict = yaml.safe_load(stream)

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
