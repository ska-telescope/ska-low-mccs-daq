from test_wrapper import TestWrapper
from config_manager import ConfigManager
import logging
import os
import pytest


class CiConfig:
    def __init__(self):
        self.test_config = f"config/test_config_te7dastardly.yml"
        self.config = "/opt/aavs-ci-runner/config/ral_ci_runner.yml"


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

    conf = CiConfig()
    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)
    test_wrapper = TestWrapper(tpm_config, test_log_file)

    def test_initialise(self):
        self.test_wrapper.initialise_station()

    @pytest.mark.parametrize("test_name", test_wrapper._tests.keys())
    def test_hw_in_loop(self, test_name):
        self.test_wrapper.load_tests(test_name)
        ret = self.test_wrapper.execute()
        assert ret == 0
