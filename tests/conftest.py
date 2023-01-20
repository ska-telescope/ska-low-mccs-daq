# type: ignore
# pylint: skip-file
# -*- coding: utf-8 -*
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""
This module contains pytest fixtures other test setups.

These are common to all ska-low-mccs tests: unit, integration and
functional (BDD).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Set, cast

import _pytest
import pytest
import tango
import uvicorn
import yaml

from ska_low_mccs_spshw.subrack import FanMode, SubrackData
from ska_low_mccs_spshw.subrack.subrack_simulator import SubrackSimulator
from ska_low_mccs_spshw.subrack.subrack_simulator_server import configure_server


def pytest_sessionstart(session: pytest.Session) -> None:
    """
    Pytest hook; prints info about tango version.

    :param session: a pytest Session object
    """
    print(tango.utils.info())


with open("tests/testbeds.yaml", "r", encoding="utf-8") as stream:
    _testbeds: dict[str, set[str]] = yaml.safe_load(stream)


# TODO: pytest is partially typehinted but does not yet export Config
def pytest_configure(
    config: _pytest.config.Config,  # type: ignore[name-defined]
) -> None:
    """
    Register custom markers to avoid pytest warnings.

    :param config: the pytest config object
    """
    all_tags: Set[str] = cast(Set[str], set()).union(*_testbeds.values())
    for tag in all_tags:
        config.addinivalue_line("markers", f"needs_{tag}")


# TODO: pytest is partially typehinted but does not yet export Parser
def pytest_addoption(
    parser: _pytest.config.argparsing.Parser,  # type: ignore[name-defined]
) -> None:
    """
    Implement the add the `--testbed` option.

    Used to specify the context in which the test is running.
    This could be used, for example, to skip tests that
    have requirements not met by the context.

    :param parser: the command line options parser
    """
    parser.addoption(
        "--testbed",
        choices=_testbeds.keys(),
        default="test",
        help="Specify the testbed on which the tests are running.",
    )


# TODO: pytest is partially typehinted but does not yet export Config
def pytest_collection_modifyitems(
    config: _pytest.config.Config,  # type: ignore[name-defined]
    items: list[pytest.Item],
) -> None:
    """
    Modify the list of tests to be run, after pytest has collected them.

    This hook implementation skips tests that are marked as needing some
    tag that is not provided by the current test context, as specified
    by the "--testbed" option.

    For example, if we have a hardware test that requires the presence
    of a real TPM, we can tag it with "@needs_tpm". When we run in a
    "test" context (that is, with "--testbed test" option), the test
    will be skipped because the "test" context does not provide a TPM.
    But when we run in "pss" context, the test will be run because the
    "pss" context provides a TPM.

    :param config: the pytest config object
    :param items: list of tests collected by pytest
    """
    testbed = config.getoption("--testbed")
    available_tags = _testbeds.get(testbed, set())

    prefix = "needs_"
    for item in items:
        needs_tags = set(
            tag[len(prefix) :] for tag in item.keywords if tag.startswith(prefix)
        )
        unmet_tags = list(needs_tags - available_tags)
        if unmet_tags:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        f"Testbed '{testbed}' does not meet test needs: "
                        f"{unmet_tags}."
                    )
                )
            )


@pytest.fixture(scope="session")
def logger() -> logging.Logger:
    """
    Fixture that returns a default logger.

    :return: a logger
    """
    debug_logger = logging.getLogger()
    debug_logger.setLevel(logging.DEBUG)
    return debug_logger


# The following fixtures are defined here because they are needed in both
# the integration tests and the subrack unit tests


@pytest.fixture(name="subrack_simulator_config")
def subrack_simulator_config_fixture() -> dict[str, Any]:
    """
    Return attribute values with which the subrack simulator is configured.

    :return: a key-value dictionary of attribute values with which the
        subrack simulator is configured.
    """
    return {
        "tpm_present": [False, True, False, False, True, False, False, False],
        "tpm_on_off": [False, False, False, False, False, False, False, False],
        "backplane_temperatures": [39.0, 40.0],
        "board_temperatures": [40.0, 41.0],
        "board_current": 1.1,
        "power_supply_currents": [4.2, 5.8],
        "power_supply_fan_speeds": [90.0, 100.0],
        "power_supply_voltages": [12.0, 12.1],
        "subrack_fan_speeds": [4999.0, 5000.0, 5001.0, 5002.0],
        "subrack_fan_modes": [FanMode.AUTO, FanMode.AUTO, FanMode.AUTO, FanMode.AUTO],
        "tpm_currents": [0.4] * 8,
        "tpm_temperatures": [40.0] * 8,
        "tpm_voltages": [12.0] * 8,
    }


@pytest.fixture(name="subrack_simulator_attribute_values")
def subrack_simulator_attribute_values_fixture(
    subrack_simulator_config,
) -> dict[str, Any]:
    """
    Return attribute values that the subrack simulator is expected to report.

    :param subrack_simulator_config: attribute values with which the
        subrack simulator is configured.

    :return: a key-value dictionary of attribute values that the subrack
        simulator is expected to report.
    """

    def _approxify(list_of_floats):
        return [pytest.approx(element) for element in list_of_floats]

    return {
        "tpm_present": subrack_simulator_config["tpm_present"],
        "tpm_on_off": subrack_simulator_config["tpm_on_off"],
        "backplane_temperatures": _approxify(
            subrack_simulator_config["backplane_temperatures"]
        ),
        "board_temperatures": _approxify(
            subrack_simulator_config["board_temperatures"]
        ),
        "board_current": pytest.approx(subrack_simulator_config["board_current"]),
        "power_supply_currents": _approxify(
            subrack_simulator_config["power_supply_currents"]
        ),
        "power_supply_fan_speeds": _approxify(
            subrack_simulator_config["power_supply_fan_speeds"]
        ),
        "power_supply_voltages": _approxify(
            subrack_simulator_config["power_supply_voltages"]
        ),
        "power_supply_powers": [
            pytest.approx(c * v)
            for c, v in zip(
                subrack_simulator_config["power_supply_currents"],
                subrack_simulator_config["power_supply_voltages"],
            )
        ],
        "subrack_fan_speeds": subrack_simulator_config["subrack_fan_speeds"],
        "subrack_fan_speeds_percent": [
            pytest.approx(s * 100.0 / SubrackData.MAX_SUBRACK_FAN_SPEED)
            for s in subrack_simulator_config["subrack_fan_speeds"]
        ],
        "subrack_fan_modes": subrack_simulator_config["subrack_fan_modes"],
        "tpm_currents": _approxify(subrack_simulator_config["tpm_currents"]),
        "tpm_temperatures": _approxify(subrack_simulator_config["tpm_temperatures"]),
        "tpm_voltages": _approxify(subrack_simulator_config["tpm_voltages"]),
        "tpm_powers": [
            pytest.approx(c * v)
            for c, v in zip(
                subrack_simulator_config["tpm_currents"],
                subrack_simulator_config["tpm_voltages"],
            )
        ],
    }


@pytest.fixture()
def subrack_simulator(subrack_simulator_config: dict[str, Any]) -> SubrackSimulator:
    """
    Return a subrack simulator.

    This is the backend python object, not the web server interface to it.

    :param subrack_simulator_config: a keyword dictionary that specifies
        the desired configuration of the simulator backend.

    :return: a subrack simulator.
    """
    return SubrackSimulator(**subrack_simulator_config)


@pytest.fixture()
def subrack_server(subrack_simulator: SubrackSimulator) -> None:
    """
    Yield a running subrack server.

    :param subrack_simulator: the actual backend simulator to which this
        server provides an interface.

    :yields: a running subrack server.
    """

    class ThreadableServer(uvicorn.Server):
        def install_signal_handlers(self: ThreadableServer):
            pass

    import socket

    my_socket = socket.socket()
    server_config = configure_server(subrack_simulator, host="127.0.0.1", port=0)

    the_server = ThreadableServer(config=server_config)
    server_thread = threading.Thread(target=the_server.run, args=([my_socket],))
    server_thread.start()

    while not the_server.started:
        time.sleep(1e-3)
    yield my_socket.getsockname()
    the_server.should_exit = True
    server_thread.join()


@pytest.fixture()
def subrack_ip() -> str:
    """
    Return the IP address of the subrack.

    :return: the IP address of the subrack.
    """
    return "127.0.0.1"


@pytest.fixture()
def subrack_port(subrack_server: None) -> int:
    """
    Return the subrack port.

    :param subrack_server: a running subrack server.
    :return: the subrack port.
    """
    return subrack_server[1]
