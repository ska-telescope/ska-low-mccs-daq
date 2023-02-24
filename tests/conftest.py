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

import enum
import logging
from typing import Any

import pytest
import tango
from _pytest.python_api import ApproxBase

TPM_BAY_COUNT = 8
MAX_SUBRACK_FAN_SPEED = 8000.0


# TODO: [MCCS-1328] We don't want to import anything from ska-low-mccs-spshw here,
# but we need to know the meaning of 1 and 2 in the context of fan modes,
# so that the tests know how to drive the device. So for now we redefine it.
# The necessity of importing or redefining this is a code smell.
# We should change the SubrackDevice's interface to use string fan modes.
# e.g. subrack.SetSubrackFanMode("{'fan_id': 1, 'mode'; 'auto'}")
# which would be much more readable and self-describing.
class FanMode(enum.IntEnum):  # type: ignore[no-redef]
    """Redefinition of FanMode."""

    MANUAL = 0
    AUTO = 1


def pytest_sessionstart(session: pytest.Session) -> None:
    """
    Pytest hook; prints info about tango version.

    :param session: a pytest Session object
    """
    print(tango.utils.info())


@pytest.fixture(scope="session", name="logger")
def logger_fixture() -> logging.Logger:
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
        "subrack_fan_mode": [FanMode.AUTO, FanMode.AUTO, FanMode.AUTO, FanMode.AUTO],
        "tpm_currents": [0.4] * 8,
        # "tpm_temperatures": [40.0] * 8,  # Not implemented on SMB
        "tpm_voltages": [12.0] * 8,
    }


@pytest.fixture(name="subrack_simulator_attribute_values", scope="session")
def subrack_simulator_attribute_values_fixture(
    subrack_simulator_config: dict[str, Any],
) -> dict[str, Any]:
    """
    Return attribute values that the subrack simulator is expected to report.

    :param subrack_simulator_config: attribute values with which the
        subrack simulator is configured.

    :return: a key-value dictionary of attribute values that the subrack
        simulator is expected to report.
    """

    def _approxify(list_of_floats: list[float]) -> list[ApproxBase]:
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
            pytest.approx(p * MAX_SUBRACK_FAN_SPEED / 100.0)
            for p in subrack_simulator_config["subrack_fan_speeds_percent"]
        ],
        "subrack_fan_mode": subrack_simulator_config["subrack_fan_mode"],
        "tpm_currents": _approxify(subrack_simulator_config["tpm_currents"]),
        # Not implemented on SMB
        # "tpm_temperatures": _approxify(subrack_simulator_config["tpm_temperatures"]),
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
    subrack_simulator_config: dict[str, Any],
) -> dict[str, Any]:
    """
    Return attribute values that the subrack device is expected to report.

    :param subrack_simulator_config: attribute values with which the
        subrack simulator is configured.

    :return: a key-value dictionary of attribute values that the subrack
        device is expected to report.
    """

    def _approxify(list_of_floats: list[float]) -> list[ApproxBase]:
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
            pytest.approx(p * MAX_SUBRACK_FAN_SPEED / 100.0)
            for p in subrack_simulator_config["subrack_fan_speeds_percent"]
        ],
        "subrackFanModes": subrack_simulator_config["subrack_fan_mode"],
        "tpmCurrents": _approxify(subrack_simulator_config["tpm_currents"]),
        # Not implemented on SMB
        # "tpmTemperatures": _approxify(subrack_simulator_config["tpm_temperatures"]),
        "tpmVoltages": _approxify(subrack_simulator_config["tpm_voltages"]),
        "tpmPowers": [
            pytest.approx(c * v)
            for c, v in zip(
                subrack_simulator_config["tpm_currents"],
                subrack_simulator_config["tpm_voltages"],
            )
        ],
    }


@pytest.fixture(name="subrack_name", scope="session")
def subrack_name_fixture() -> str:
    """
    Return the name of the subrack Tango device.

    :return: the name of the subrack Tango device.
    """
    return "low-mccs/subrack/0001"


@pytest.fixture(name="tile_name", scope="session")
def tile_name_fixture() -> str:
    """
    Return the name of the subrack Tango device.

    :return: the name of the subrack Tango device.
    """
    return "low-mccs/tile/0001"
