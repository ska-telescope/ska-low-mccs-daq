import logging

from test_wrapper import TestWrapper
from config_manager import ConfigManager
import pytest
from pyaavs import station

class CiConfig:
    def __init__(self):
        self.test_config = None
        self.config = None


class TestHw:

    test_log_file = 'test_log/test_wrapper.log'
    test_wrapper = TestWrapper(None, test_log_file)

    def set_config(self, get_param):
        conf = CiConfig()
        if get_param["test_config"] is not None:
            conf.test_config = get_param["test_config"]
        if get_param["config"] is not None:
            conf.config = get_param["config"]
        config_manager = ConfigManager(conf.test_config)
        self.test_wrapper.tpm_config = config_manager.apply_test_configuration(conf)

    def test_initialise(self, get_param):

        if not (get_param["init"] or get_param["init_only"]):
            pytest.skip("initialize argument has not been provided")

        self.set_config(get_param)
        if not self.test_wrapper.initialise_station():
            pytest.fail("Some tiles were not initialised or programmed. Not forming station")

    def test_tpm_info(self, get_param):
        self.set_config(get_param)
        station_inst = station.Station(self.test_wrapper.tpm_config)
        station_inst.connect()
        for index, tile in enumerate(station_inst.tiles):
            logging.info(f"TPM {index}")
            logging.info(str(tile))

    @pytest.mark.parametrize("test_name", test_wrapper._tests.keys())
    def test_hw_in_loop(self, get_param, test_name):
        if get_param["init_only"]:
            pytest.skip("init only argument given")

        self.set_config(get_param)
        self.test_wrapper.load_tests(test_name)
        ret = self.test_wrapper.execute()
        if ret != 0:
            pytest.fail(f"{test_name} test has failed checks")
        if self.test_wrapper.test_skipped:
            pytest.skip(f"{test_name} test has been skipped")
