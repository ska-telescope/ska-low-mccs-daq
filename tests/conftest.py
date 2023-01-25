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
import socket
import threading
import time
from types import TracebackType
from typing import Any, Callable, ContextManager, Literal, Optional, Type

import pytest
import tango
import uvicorn

from ska_low_mccs_spshw.subrack import FanMode, SubrackData
from ska_low_mccs_spshw.subrack.subrack_simulator import SubrackSimulator
from ska_low_mccs_spshw.subrack.subrack_simulator_server import configure_server


def pytest_sessionstart(session: pytest.Session) -> None:
    """
    Pytest hook; prints info about tango version.

    :param session: a pytest Session object
    """
    print(tango.utils.info())


@pytest.fixture(scope="session")
def logger() -> logging.Logger:
    """
    Fixture that returns a default logger.

    :return: a logger
    """
    debug_logger = logging.getLogger()
    debug_logger.setLevel(logging.DEBUG)
    return debug_logger


@pytest.fixture(name="subrack_simulator_config", scope="session")
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
        "subrack_fan_speeds_percent": [95.0, 96.0, 97.0, 98.0],
        "subrack_fan_modes": [FanMode.AUTO, FanMode.AUTO, FanMode.AUTO, FanMode.AUTO],
        "tpm_currents": [0.4] * 8,
        "tpm_temperatures": [40.0] * 8,
        "tpm_voltages": [12.0] * 8,
    }


@pytest.fixture(name="subrack_simulator_attribute_values", scope="session")
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
        "subrack_fan_speeds_percent": _approxify(
            subrack_simulator_config["subrack_fan_speeds_percent"]
        ),
        "subrack_fan_speeds": [
            pytest.approx(p * SubrackData.MAX_SUBRACK_FAN_SPEED / 100.0)
            for p in subrack_simulator_config["subrack_fan_speeds_percent"]
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


@pytest.fixture(name="subrack_device_attribute_values", scope="session")
def subrack_device_attribute_values_fixture(
    subrack_simulator_config,
) -> dict[str, Any]:
    """
    Return attribute values that the subrack device is expected to report.

    :param subrack_simulator_config: attribute values with which the
        subrack simulator is configured.

    :return: a key-value dictionary of attribute values that the subrack
        device is expected to report.
    """

    def _approxify(list_of_floats):
        return [pytest.approx(element) for element in list_of_floats]

    return {
        "tpmPresent": subrack_simulator_config["tpm_present"],
        "tpmOnOff": subrack_simulator_config["tpm_on_off"],
        "backplaneTemperatures": _approxify(
            subrack_simulator_config["backplane_temperatures"]
        ),
        "boardTemperatures": _approxify(subrack_simulator_config["board_temperatures"]),
        "boardCurrent": [pytest.approx(subrack_simulator_config["board_current"])],
        "powerSupplyCurrents": _approxify(
            subrack_simulator_config["power_supply_currents"]
        ),
        "powerSupplyFanSpeeds": _approxify(
            subrack_simulator_config["power_supply_fan_speeds"]
        ),
        "powerSupplyVoltages": _approxify(
            subrack_simulator_config["power_supply_voltages"]
        ),
        "powerSupplyPowers": [
            pytest.approx(c * v)
            for c, v in zip(
                subrack_simulator_config["power_supply_currents"],
                subrack_simulator_config["power_supply_voltages"],
            )
        ],
        "subrackFanSpeedsPercent": _approxify(
            subrack_simulator_config["subrack_fan_speeds_percent"]
        ),
        "subrackFanSpeeds": [
            pytest.approx(p * SubrackData.MAX_SUBRACK_FAN_SPEED / 100.0)
            for p in subrack_simulator_config["subrack_fan_speeds_percent"]
        ],
        "subrackFanModes": subrack_simulator_config["subrack_fan_modes"],
        "tpmCurrents": _approxify(subrack_simulator_config["tpm_currents"]),
        "tpmTemperatures": _approxify(subrack_simulator_config["tpm_temperatures"]),
        "tpmVoltages": _approxify(subrack_simulator_config["tpm_voltages"]),
        "tpmPowers": [
            pytest.approx(c * v)
            for c, v in zip(
                subrack_simulator_config["tpm_currents"],
                subrack_simulator_config["tpm_voltages"],
            )
        ],
    }


@pytest.fixture(scope="session")
def subrack_simulator_factory(
    subrack_simulator_config: dict[str, Any],
) -> Callable[[], SubrackSimulator]:
    """
    Return a subrack simulator factory.

    :param subrack_simulator_config: a keyword dictionary that specifies
        the desired configuration of the simulator backend.

    :return: a subrack simulator factory.
    """
    return functools.partial(SubrackSimulator, **subrack_simulator_config)


@pytest.fixture()
def subrack_simulator(
    subrack_simulator_factory: Callable[[], SubrackSimulator],
) -> SubrackSimulator:
    """
    Return a subrack simulator.

    :param subrack_simulator_factory: a factory that returns a backend
        simulator to which the server will provide an interface.

    :return: a subrack simulator.
    """
    return subrack_simulator_factory()


@pytest.fixture(scope="session")
def subrack_server_launcher() -> Callable[
    [SubrackSimulator], ContextManager[tuple[str, int]]
]:
    """
    Return a subrack server launcher.

    :return: a callable that, when called, launches a subrack server for
        use in testing, yields it, and tears it down afterwards.
    """

    class _ThreadableServer(uvicorn.Server):
        def install_signal_handlers(self: _ThreadableServer):
            pass

    class _SubrackServerContextManager:
        def __init__(self, subrack_simulator):
            self._socket = socket.socket()
            server_config = configure_server(
                subrack_simulator, host="127.0.0.1", port=0
            )
            self._server = _ThreadableServer(config=server_config)
            self._thread = threading.Thread(
                target=self._server.run, args=([self._socket],), daemon=True
            )

        def __enter__(self):
            self._thread.start()

            while not self._server.started:
                time.sleep(1e-3)
            _, port = self._socket.getsockname()
            return "127.0.0.1", port

        def __exit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exception: Optional[BaseException],
            trace: Optional[TracebackType],
        ) -> Literal[False]:
            """
            Exit the context.

            :param exc_type: the type of exception thrown in the with block
            :param exception: the exception thrown in the with block
            :param trace: a traceback

            :returns: whether the exception (if any) has been fully handled
                by this method and should be swallowed i.e. not re-raised
            """
            self._server.should_exit = True
            self._thread.join()
            return False

    return _SubrackServerContextManager


@pytest.fixture()
def subrack_server(
    subrack_server_launcher,
    subrack_simulator,
) -> tuple[str, int]:
    """
    Yield a running subrack server.

    :param subrack_server_launcher: a callable that, when called,
        returns a context manager that spins up a subrack server, yields
        it for use in testing, and then shuts its down afterwards.
    :param subrack_simulator: the actual backend simulator to which this
        server provides an interface.

    :yields: a running subrack server.
    """
    with subrack_server_launcher(subrack_simulator) as subrack_server:
        yield subrack_server


@pytest.fixture()
def subrack_address(subrack_server: tuple[str, int]) -> tuple[str, int]:
    """
    Yield the address (host and port) of the subrack.

    :param subrack_server: a running subrack server.

    :yields: the address of a running subrack.
    """
    # The subrack server yields the host and port,
    # which is exactly what we need here, so we just yield it.
    # This fixture might seem a little pointless, but
    # (a) it provides a better name.
    # (b) it allows us to write tests/fixtures that depend on the subrack address,
    # without that address necessarily being that of a simulator server that has been
    # launched by the test harness.
    # In functional testing, where there's a real subrack,
    # we simply override this fixture to point at that.
    yield subrack_server


@pytest.fixture(name="subrack_name", scope="session")
def subrack_name_fixture() -> str:
    """
    Return the name of the subrack Tango device.

    :return: the name of the subrack Tango device.
    """
    return "low-mccs/subrack/0001"
