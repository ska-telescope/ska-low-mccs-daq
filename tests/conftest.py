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

import pytest
import tango

from tests.harness import get_bandpass_daq_name, get_lmc_daq_name


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


@pytest.fixture(name="daq_id", scope="session")
def daq_id_fixture() -> int:
    """
    Return the daq id of this daq receiver.

    :return: the daq id of this daq receiver.
    """
    return 1


@pytest.fixture(name="lmc_daq_trl")
def lmc_daq_trl_fixture() -> str:
    """
    Return a DAQ TRL for testing purposes.

    :returns: A DAQ TRL.
    """
    return get_lmc_daq_name()


@pytest.fixture(name="bandpass_daq_trl")
def bandpass_daq_trl_fixture() -> str:
    """
    Return a DAQ TRL for testing purposes.

    :returns: A DAQ TRL.
    """
    return get_bandpass_daq_name()
