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
from time import sleep
from typing import Iterator

import pytest
import tango
from pytest_bdd import given, scenarios, then, when
from ska_control_model import AdminMode, HealthState

from tests.harness import SpsTangoTestHarnessContext

scenarios("./features/daq_basic_functionality.feature")


def poll_until_state_change(
    daq: tango.DeviceProxy, wanted_state: tango.DevState, no_of_iters: int = 5
) -> None:
    """
    Poll until device is in wanted state.

    :param daq: the DAQ receiver Tango device
    :param wanted_state: the state we're waiting for
    :param no_of_iters: number of times to iterate
    """
    if daq.state() == wanted_state:
        return
    for _ in range(no_of_iters):
        sleep(1)
        if daq.state() == wanted_state:
            return

    pytest.fail(
        f"device not in desired state, \
        wanted: {wanted_state}, actual: {daq.state()}"
    )


@pytest.fixture(name="daq_receiver_device", scope="module")
def daq_receiver_fixture(
    functional_test_context: SpsTangoTestHarnessContext,
    daq_id: int,
) -> Iterator[tango.DeviceProxy]:
    """
    Yield the DAQ receiver device under test.

    :param functional_test_context: the context in which the test is running.
    :param daq_id: the ID of the daq receiver

    :yield: the DAQ receiver device
    """
    yield functional_test_context.get_daq_device(daq_id)


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


@given("the DAQ is in adminMode ONLINE")
def daq_device_is_in_admin_mode_online(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is in admin mode ONLINE.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    if daq_receiver.adminMode != AdminMode.ONLINE:
        daq_receiver.adminMode = AdminMode.ONLINE
    assert daq_receiver.adminMode == AdminMode.ONLINE


@when("I set adminMode to ONLINE")
def set_admin_mode_online(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Set this daq_receiver's adminMode to ONLINE.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_receiver.adminMode = AdminMode.ONLINE


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
        daq_receiver.adminMode = AdminMode.ONLINE
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


@when("I send the Configure command with raw data")
def daq_sent_configure_raw(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Send configure raw command to the daq receiver.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_receiver.Start('{"modes_to_start": "DaqModes.RAW_DATA"}')
    sleep(0.1)


@then("the DAQ is in raw data mode")
def check_daq_config_is_raw(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Check that the daq receiver is configured to receive raw data.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_status = json.loads(daq_receiver.daqstatus())
    running_consumers = daq_status.get("Running Consumers")
    for consumer in running_consumers:
        if "RAW_DATA" in consumer:
            return
    pytest.fail(f"Raw data failed to start, actual {running_consumers}")


@when("I send the Configure command with channelised data")
def daq_sent_configure_channelised(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Send configure channelised command to the daq receiver.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_receiver.Start('{"modes_to_start": "DaqModes.CHANNEL_DATA"}')
    sleep(0.1)


@then("the DAQ is in channelised data mode")
def check_daq_config_is_channelised(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Check that the daq receiver is configured to receive channelised data.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_status = json.loads(daq_receiver.daqstatus())
    running_consumers = daq_status.get("Running Consumers")
    for consumer in running_consumers:
        if "CHANNEL_DATA" in consumer:
            return
    pytest.fail("Raw data failed to start")
