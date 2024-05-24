from test_wrapper import TestWrapper
from config_manager import ConfigManager
import logging
import os
import pytest


class CiConfig:
    def __init__(self):
        self.test_config = "config/test_config.yml"
        self.config = None


class TestHw:

    test_log_file = 'test_log/test_wrapper.log'
    if not os.path.exists('test_log'):
        os.makedirs('test_log')
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename=test_log_file,
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
    test_wrapper = TestWrapper(None, test_log_file)

    def test_initialise(self, get_param):

        if not (get_param["init"] or get_param["init_only"]):
            pytest.skip("initialize argument has not been provided")

        conf = CiConfig()
        if get_param["test_config"] is not None:
            conf.test_config = get_param["test_config"]
        if get_param["config"] is not None:
            conf.config = get_param["config"]
        config_manager = ConfigManager(conf.test_config)
        self.test_wrapper.tpm_config = config_manager.apply_test_configuration(conf)
        if not self.test_wrapper.initialise_station():
            pytest.fail("Some tiles were not initialised or programmed. Not forming station")

    @pytest.mark.parametrize("test_name", test_wrapper._tests.keys())
    def test_hw_in_loop(self, get_param, test_name):
        if get_param["init_only"]:
            pytest.skip("init only argument given")

        conf = CiConfig()
        if get_param["test_config"] is not None:
            conf.test_config = get_param["test_config"]
        if get_param["config"] is not None:
            conf.config = get_param["config"]

        config_manager = ConfigManager(conf.test_config)
        self.test_wrapper.tpm_config = config_manager.apply_test_configuration(conf)
        self.test_wrapper.load_tests(test_name)
        ret = self.test_wrapper.execute()
        if ret != 0:
            pytest.fail(f"{test_name} test has failed checks")
        if self.test_wrapper.test_skipped:
            pytest.skip(f"{test_name} test has been skipped")
