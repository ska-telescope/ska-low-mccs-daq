# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module defined a pytest harness for testing the MCCS daq_receiver module."""
from __future__ import annotations

import logging
import os
from typing import Any, Iterator

import numpy as np
import psutil  # type: ignore[import-untyped]
import pytest
from ska_tango_testing.mock import MockCallableGroup
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from ska_low_mccs_daq.daq_receiver import DaqComponentManager
from tests.harness import SpsTangoTestHarness, SpsTangoTestHarnessContext


@pytest.fixture(name="callbacks")
def callbacks_fixture() -> MockCallableGroup:
    """
    Return a dictionary of callbacks with asynchrony support.

    :return: a collections.defaultdict that returns callbacks by name.
    """
    return MockCallableGroup(
        "communication_state",
        "component_state",
        "received_data",
        "task",
        "extra_daq_mode",
        "task_start_daq",
        timeout=30.0,
    )


@pytest.fixture(name="change_event_callbacks")
def change_event_callbacks_fixture() -> MockTangoEventCallbackGroup:
    """
    Return a dictionary of change event callbacks with asynchrony support.

    :return: a collections.defaultdict that returns change event
        callbacks by name.
    """
    return MockTangoEventCallbackGroup(
        "healthState",
        "dataReceivedResult",
        "state",
        "ringbuffer_occupancy",
        "lost_pushes",
        "track_lrc_command",
        timeout=15.0,
        # TODO: Add more event types here as the tests grow
    )


@pytest.fixture(name="skuid_url")
def skuid_url_fixture() -> str:
    """
    Return an url to use to access SKUID.

    :return: A SKUID url.
    """
    return ""


@pytest.fixture(name="test_context")
def test_context_fixture(
    daq_id: int,
    mock_interface: str,
) -> Iterator[SpsTangoTestHarnessContext]:
    """
    Yield a tango harness against which to run tests of the deployment.

    :param daq_id: the ID number of the DAQ receiver.
    :param mock_interface: the mock interface to use for the DAQ handler.

    :yields: a test harness context.
    """
    test_harness = SpsTangoTestHarness()
    test_harness.set_lmc_daq_device(
        daq_id, address=None, receiver_interface=mock_interface
    )  # dynamically get DAQ address
    with test_harness as test_context:
        yield test_context


@pytest.fixture(name="mock_interface")
def mock_interface_fixture() -> str:
    """
    Fixture to get a mock interface for the DaqHandler.

    :return: a mock interface.
    """
    return "sdn1"


@pytest.fixture(name="nof_tiles")
def nof_tiles_fixture() -> int:
    """
    Fixture to get number of tiles to hand to the DaqComponentManager.

    This is set to 8 as we use a set of 8 integrated files generated at RAL
    from 8 TPMs.

    :return: number of tiles.
    """
    return 8


# pylint: disable=too-many-arguments
@pytest.fixture(name="daq_component_manager")
def daq_component_manager_fixture(
    test_context: SpsTangoTestHarnessContext,
    daq_id: int,
    skuid_url: str,
    logger: logging.Logger,
    callbacks: MockCallableGroup,
    mock_interface: str,
    nof_tiles: int,
) -> DaqComponentManager:
    """
    Return a daq receiver component manager.

    :param test_context: the context in which the tests are running.
    :param daq_id: the ID of the daq receiver
    :param skuid_url: An address where SKUID can be contacted.
    :param logger: the logger to be used by this object.
    :param callbacks: a dictionary from which callbacks with asynchrony
        support can be accessed.
    :param mock_interface: the mock interface to use for the DAQ handler.
    :param nof_tiles: number of tiles to configure the DAQ with.

    :return: a daq component manager
    """
    return DaqComponentManager(
        daq_id,
        mock_interface,
        "",
        "",
        "",
        nof_tiles,
        skuid_url,
        logger,
        "station_name_here",
        daq_id,  # station id same as daq id
        callbacks["communication_state"],
        callbacks["component_state"],
        callbacks["received_data"],
        simulation_mode=True,
    )


@pytest.fixture(name="x_pol_bandpass_test_data")
def x_pol_bandpass_test_data_fixture() -> np.ndarray:
    """
    Return test bandpass data for x polarisation.

    :return: A NumPy array of simulated x-pol bandpass data.
    """
    bandpass_dir = os.path.dirname(__file__)
    return np.loadtxt(
        os.path.join(bandpass_dir, "x_pol_bandpass.txt"), delimiter=","
    ).transpose()


@pytest.fixture(name="y_pol_bandpass_test_data")
def y_pol_bandpass_test_data_fixture() -> np.ndarray:
    """
    Return test bandpass data for y polarisation.

    :return: A NumPy array of simulated y-pol bandpass data.
    """
    bandpass_dir = os.path.dirname(__file__)
    return np.loadtxt(
        os.path.join(bandpass_dir, "y_pol_bandpass.txt"), delimiter=","
    ).transpose()


@pytest.fixture(autouse=True)
def mock_psutil_methods(
    monkeypatch: pytest.MonkeyPatch,
    mock_interface: str,
) -> None:
    """
    Fixture to mock psutil methods for network I/O.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param mock_interface: the mock interface to use.
    """
    counter = 0

    def mock_net_io_counters(
        *args: Any, **kwargs: Any
    ) -> dict[str, psutil._ntuples.snetio]:
        nonlocal counter
        counter += 1024**3  # 1 Gb/s in bytes per second
        return {
            mock_interface: psutil._ntuples.snetio(
                bytes_sent=counter,
                bytes_recv=counter,
                packets_sent=0,
                packets_recv=0,
                errin=0,
                errout=0,
                dropin=0,
                dropout=0,
            ),
            "eth0": psutil._ntuples.snetio(
                bytes_sent=0,
                bytes_recv=0,
                packets_sent=0,
                packets_recv=0,
                errin=0,
                errout=0,
                dropin=0,
                dropout=0,
            ),
        }

    monkeypatch.setattr(psutil, "net_io_counters", mock_net_io_counters)
