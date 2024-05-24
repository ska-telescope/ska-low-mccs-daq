import pytest


def pytest_addoption(parser):
    parser.addoption("--test_config", action="store", default=None)
    parser.addoption("--config", action="store", default=None)
    parser.addoption("--init", action="store_true")
    parser.addoption("--init_only", action="store_true")


@pytest.fixture
def get_param(request):
    config_param = {"test_config": request.config.getoption("--test_config"),
                    "config": request.config.getoption("--config"),
                    "init": request.config.getoption("--init"),
                    "init_only": request.config.getoption("--init_only")
                    }
    return config_param
