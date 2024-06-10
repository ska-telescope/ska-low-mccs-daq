# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq basic functionality."""
from __future__ import annotations

import json
from typing import Callable, Iterator

import pytest
import tango
from pytest_bdd import given, parsers, scenarios, then, when
from ska_control_model import AdminMode, HealthState

from tests.functional.conftest import (
    poll_until_consumer_running,
    poll_until_consumers_stopped,
    poll_until_state_change,
)
from tests.harness import SpsTangoTestHarnessContext

from ..test_tools import retry_communication

scenarios("./features/daq_basic_functionality.feature")


@given(
    parsers.cfparse("this test is running against station {station_name}"),
    target_fixture="test_context",
)
def test_context_fixture(
    functional_test_context_generator: Callable,
    station_name: str,
) -> Iterator[SpsTangoTestHarnessContext]:
    """
    Yield the a context containing devices from a specific station.

    :param functional_test_context_generator: a callable to generate
        a context.
    :param station_name: the name of the station to test against.

    :yield: the DAQ receiver device
    """
    skip_if_not_real_context = False
    if station_name == "real-daq-1":
        skip_if_not_real_context = True
    yield from functional_test_context_generator(station_name, skip_if_not_real_context)


@pytest.fixture(name="daq_receiver_device")
def daq_receiver_fixture(
    test_context: SpsTangoTestHarnessContext,
) -> Iterator[tango.DeviceProxy]:
    """
    Yield the DAQ receiver device under test.

    :param test_context: the context in which the test is running.

    :yield: the DAQ receiver device
    """
    yield test_context.get_daq_device()


@given("the DAQ is available", target_fixture="daq_receiver")
def daq_receiver_is_available(
    daq_receiver_device: tango.DeviceProxy,
) -> tango.DeviceProxy:
    """
    Return the daq_receiver device.

    :param daq_receiver_device: a test harness for tango devices

    :return: A proxy to the daq_receiver device.
    """
    return daq_receiver_device


@given("the DAQ is in the DISABLE state")
def assert_daq_is_disable(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is in disable state.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    if daq_receiver.adminMode != AdminMode.OFFLINE:
        daq_receiver.adminMode = AdminMode.OFFLINE
    poll_until_state_change(daq_receiver, tango.DevState.DISABLE)


@then("the DAQ is in the DISABLE state")
def check_daq_is_disable(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Check that daq receiver is in disable state.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    poll_until_state_change(daq_receiver, tango.DevState.DISABLE)
    assert daq_receiver.state() == tango.DevState.DISABLE


@given("the DAQ is in health state UNKNOWN")
def assert_daq_is_unknown_health(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is in health mode unknown.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    if daq_receiver.healthState != HealthState.UNKNOWN:
        pytest.fail("Initial conditions not met, health state not unknown")


@then("the DAQ is in health state UNKNOWN")
def check_daq_is_unknown_health(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Check that daq receiver is in health mode unknown.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    assert daq_receiver.healthState == HealthState.UNKNOWN


@given("the DAQ is in adminMode OFFLINE")
def daq_device_is_in_admin_mode_offline(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is in admin mode OFFLINE.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    if daq_receiver.adminMode != AdminMode.OFFLINE:
        daq_receiver.adminMode = AdminMode.OFFLINE
    assert daq_receiver.adminMode == AdminMode.OFFLINE


@given("the DAQ has no consumers running")
def daq_device_has_no_running_consumers(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver has no running consumers.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    status = json.loads(daq_receiver.DaqStatus())
    if status["Running Consumers"] != []:
        daq_receiver.Stop()  # Stops *all* consumers.
        poll_until_consumers_stopped(daq_receiver)


@given("the DAQ is in adminMode ONLINE")
def daq_device_is_in_admin_mode_online(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is in admin mode ONLINE.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    retry_communication(daq_receiver)
    assert daq_receiver.adminMode == AdminMode.ONLINE


@when("I set adminMode to ONLINE")
def set_admin_mode_online(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Set this daq_receiver's adminMode to ONLINE.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    retry_communication(daq_receiver)


@when("I set adminMode to OFFLINE")
def set_admin_mode_offline(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Set this daq_receiver's adminMode to OFFLINE.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_receiver.adminMode = AdminMode.OFFLINE


@then("the DAQ is in the ON state")
def check_daq_is_on(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Check that the daq receiver is ON.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    poll_until_state_change(daq_receiver, tango.DevState.ON)
    assert daq_receiver.state() == tango.DevState.ON


@then("the DAQ is in health state OK")
def check_daq_is_healthy(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Check that the daq receiver is healthy.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    assert daq_receiver.healthState == HealthState.OK


@given("the DAQ is in the ON state")
def daq_device_is_on(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is ON.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    if daq_receiver.state() != tango.DevState.ON:
        retry_communication(daq_receiver)
        poll_until_state_change(daq_receiver, tango.DevState.ON)
    assert daq_receiver.state() == tango.DevState.ON


@given("the DAQ is in health state OK")
def daq_device_is_online_health(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is in health mode OK.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    if daq_receiver.healthState != HealthState.OK:
        pytest.fail("Initial conditions not met, health state not OK")


@when("I send the Start command with raw data")
def daq_sent_start_raw(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Send start raw command to the daq receiver.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_receiver.Start('{"modes_to_start": "DaqModes.RAW_DATA"}')


@then("the DAQ is in raw data mode")
def check_daq_config_is_raw(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Check that the daq receiver is configured to receive raw data.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    poll_until_consumer_running(daq_receiver, "RAW_DATA", no_of_iters=25)


@when("I send the Start command with channelised data")
def daq_sent_start_channelised(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Send start channelised command to the daq receiver.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_receiver.Start('{"modes_to_start": "DaqModes.CHANNEL_DATA"}')


@then("the DAQ is in channelised data mode")
def check_daq_config_is_channelised(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Check that the daq receiver is configured to receive channelised data.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    poll_until_consumer_running(daq_receiver, "CHANNEL_DATA", no_of_iters=25)
