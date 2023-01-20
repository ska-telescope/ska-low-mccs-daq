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

import functools
import logging
import threading
import time
import unittest
from typing import Any, Callable, Generator, Set, cast

import _pytest
import pytest
import tango
import uvicorn
import yaml
from ska_low_mccs_common.testing.mock import MockChangeEventCallback, MockDeviceBuilder
from ska_low_mccs_common.testing.tango_harness import (
    ClientProxyTangoHarness,
    DeploymentContextTangoHarness,
    DevicesToLoadType,
    MccsDeviceInfo,
    MockingTangoHarness,
    StartingStateTangoHarness,
    TangoHarness,
    TestContextTangoHarness,
)

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


@pytest.fixture()
def initial_mocks() -> dict[str, unittest.mock.Mock]:
    """
    Fixture that registers device proxy mocks prior to patching.

    By default no initial mocks are registered, but this fixture can be
    overridden by test modules/classes that need to register initial
    mocks.

    :return: an empty dictionary
    """
    return {}


@pytest.fixture()
def mock_factory() -> Callable[[], unittest.mock.Mock]:
    """
    Fixture that provides a mock factory for device proxy mocks.

    This default factory
    provides vanilla mocks, but this fixture can be overridden by test modules/classes
    to provide mocks with specified behaviours.

    :return: a factory for device proxy mocks
    """
    return MockDeviceBuilder()


@pytest.fixture(scope="session")
def tango_harness_factory(
    request: pytest.FixtureRequest, logger: logging.Logger
) -> Callable[
    [
        dict[str, Any],
        DevicesToLoadType,
        Callable[[], unittest.mock.Mock],
        dict[str, unittest.mock.Mock],
    ],
    TangoHarness,
]:
    """
    Return a factory for creating a test harness for testing Tango devices.

    The Tango context used depends upon the context in which the tests are being
    run, as specified by the `--testbed` option.

    If the context is "test", then this harness deploys the specified
    devices into a
    :py:class:`tango.test_context.MultiDeviceTestContext`.

    Otherwise, this harness assumes that devices are already running;
    that is, we are testing a deployed system.

    This fixture is implemented as a factory so that the actual
    `tango_harness` fixture can vary in scope: unit tests require test
    isolation, so will want to build a new harness every time. But
    functional tests assume a single harness that maintains state
    across multiple tests, so they will want to instantiate the harness
    once and then use it for multiple tests.

    :param request: A pytest object giving access to the requesting test
        context.
    :param logger: the logger to be used by this object.

    :return: a tango harness factory
    """

    class _CPTCTangoHarness(ClientProxyTangoHarness, TestContextTangoHarness):
        """
        A Tango test harness.

        With the client proxy functionality of
        :py:class:`~ska_low_mccs_common.testing.tango_harness.ClientProxyTangoHarness`
        within the lightweight test context provided by
        :py:class:`~ska_low_mccs_common.testing.tango_harness.TestContextTangoHarness`.
        """

        pass

    testbed = request.config.getoption("--testbed")

    def build_harness(
        tango_config: dict[str, Any],
        devices_to_load: DevicesToLoadType,
        mock_factory: Callable[[], unittest.mock.Mock],
        initial_mocks: dict[str, unittest.mock.Mock],
    ) -> TangoHarness:
        """
        Build the Tango test harness.

        :param tango_config: basic configuration information for a tango
            test harness
        :param devices_to_load: fixture that provides a specification of the
            devices that are to be included in the devices_info dictionary
        :param mock_factory: the factory to be used to build mocks
        :param initial_mocks: a pre-build dictionary of mocks to be used
            for particular

        :return: a tango test harness
        """
        if devices_to_load is None:
            device_info = None
        else:
            device_info = MccsDeviceInfo(**devices_to_load)

        tango_harness: TangoHarness  # type hint only
        if testbed == "test":
            tango_harness = _CPTCTangoHarness(device_info, logger, **tango_config)
        elif testbed == "local":
            tango_harness = DeploymentContextTangoHarness(
                device_info, logger, **tango_config
            )
        else:
            tango_harness = ClientProxyTangoHarness(device_info, logger)

        starting_state_harness = StartingStateTangoHarness(tango_harness)

        mocking_harness = MockingTangoHarness(
            starting_state_harness, mock_factory, initial_mocks
        )

        return mocking_harness

    return build_harness


@pytest.fixture()
def tango_config() -> dict[str, Any]:
    """
    Fixture that returns basic configuration information for a Tango test harness.

    For example whether or not to run in a separate process.

    :return: a dictionary of configuration key-value pairs
    """
    return {"process": False}


@pytest.fixture()
def tango_harness(
    tango_harness_factory: Callable[
        [
            dict[str, Any],
            DevicesToLoadType,
            Callable[[], unittest.mock.Mock],
            dict[str, unittest.mock.Mock],
        ],
        TangoHarness,
    ],
    tango_config: dict[str, str],
    devices_to_load: DevicesToLoadType,
    mock_factory: Callable[[], unittest.mock.Mock],
    initial_mocks: dict[str, unittest.mock.Mock],
) -> Generator[TangoHarness, None, None]:
    """
    Create a test harness for testing Tango devices.

    :param tango_harness_factory: a factory that provides a test harness
        for testing tango devices
    :param tango_config: basic configuration information for a tango
        test harness
    :param devices_to_load: fixture that provides a specification of the
        devices that are to be included in the devices_info dictionary
    :param mock_factory: the factory to be used to build mocks
    :param initial_mocks: a pre-build dictionary of mocks to be used
        for particular

    :yields: a tango test harness
    """
    with tango_harness_factory(
        tango_config, devices_to_load, mock_factory, initial_mocks
    ) as harness:
        yield harness


@pytest.fixture(scope="session")
def logger() -> logging.Logger:
    """
    Fixture that returns a default logger.

    :return: a logger
    """
    debug_logger = logging.getLogger()
    debug_logger.setLevel(logging.DEBUG)
    return debug_logger


@pytest.fixture()
def mock_callback_called_timeout() -> float:
    """
    Return the time to wait for a mock callback to be called when a call is expected.

    This is a high value because calls will usually arrive much much
    sooner, but we should be prepared to wait plenty of time before
    giving up and failing a test.

    :return: the time to wait for a mock callback to be called when a
        call is asserted.
    """
    return 7.5


@pytest.fixture()
def mock_callback_not_called_timeout() -> float:
    """
    Return the time to wait for a mock callback to be called when a call is unexpected.

    An assertion that a callback has not been called can only be passed
    once we have waited the full timeout period without a call being
    received. Thus, having a high value for this timeout will make such
    assertions very slow. It is better to keep this value fairly low,
    and accept the risk of an assertion passing prematurely.

    :return: the time to wait for a mock callback to be called when a
        call is unexpected.
    """
    return 0.5


@pytest.fixture()
def mock_change_event_callback_factory(
    mock_callback_called_timeout: float,
    mock_callback_not_called_timeout: float,
) -> Callable[[str], MockChangeEventCallback]:
    """
    Return a factory that returns a new mock change event callback each call.

    :param mock_callback_called_timeout: the time to wait for a mock
        callback to be called when a call is expected
    :param mock_callback_not_called_timeout: the time to wait for a mock
        callback to be called when a call is unexpected

    :return: a factory that returns a new mock change event callback
        each time it is called with the name of a device attribute.
    """
    return functools.partial(
        MockChangeEventCallback,
        called_timeout=mock_callback_called_timeout,
        not_called_timeout=mock_callback_not_called_timeout,
    )


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
