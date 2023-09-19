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
from typing import Iterator

import pytest
from ska_tango_testing.mock import MockCallableGroup
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from ska_low_mccs_spshw.daq_receiver import DaqComponentManager
from ska_low_mccs_spshw.daq_receiver.daq_simulator import DaqSimulator
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
        timeout=5.0,
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
        # TODO: Add more event types here as the tests grow
    )


@pytest.fixture(name="skuid_url")
def skuid_url_fixture() -> str:
    """
    Return an url to use to access SKUID.

    :return: A SKUID url.
    """
    return "ska-ser-skuid-ska-ser-skuid-svc:9870"


@pytest.fixture(name="test_context")
def test_context_fixture(daq_id: int) -> Iterator[SpsTangoTestHarnessContext]:
    """
    Yield a tango harness against which to run tests of the deployment.

    :param daq_id: the ID number of the DAQ receiver.

    :yields: a test harness context.
    """
    test_harness = SpsTangoTestHarness()
    test_harness.set_daq_instance(DaqSimulator())
    test_harness.set_daq_device(daq_id, address=None)  # dynamically get DAQ address
    with test_harness as test_context:
        yield test_context


@pytest.fixture(name="daq_component_manager")
def daq_component_manager_fixture(
    test_context: SpsTangoTestHarnessContext,
    daq_id: int,
    skuid_url: str,
    logger: logging.Logger,
    callbacks: MockCallableGroup,
) -> DaqComponentManager:
    """
    Return a daq receiver component manager.

    :param test_context: the context in which the tests are running.
    :param daq_id: the ID of the daq receiver
    :param skuid_url: An address where SKUID can be contacted.
    :param logger: the logger to be used by this object.
    :param callbacks: a dictionary from which callbacks with asynchrony
        support can be accessed.

    :return: a daq component manager
    """
    return DaqComponentManager(
        daq_id,
        "eth0",
        "172.17.0.230",
        "[4660]",
        test_context.get_daq_server_address(daq_id),
        "",
        skuid_url,
        logger,
        1,
        callbacks["communication_state"],
        callbacks["component_state"],
        callbacks["received_data"],
    )
