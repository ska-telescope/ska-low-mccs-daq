# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq basic functionality."""
from __future__ import annotations

import pytest
import tango
from ska_control_model import AdminMode, HealthState
from pytest_bdd import given, parsers, scenarios, then, when
from ska_tango_testing.context import TangoContextProtocol
from time import sleep
import json


scenarios("./features/daq_basic_functionality.feature")

@given("the DAQ is available", target_fixture="daq_receiver")
def daq_receiver_fixture(
    tango_harness: TangoContextProtocol,
    daq_name: str,
) -> tango.DeviceProxy:
    """
    Return the daq_receiver device.

    :param tango_harness: a test harness for tango devices
    :param daq_name: name of the DAQ receiver Tango device

    :return: the daq_receiver device
    """
    return tango_harness.get_device(daq_name)

@given("the DAQ is in the OFF state")
def daq_device_is_off(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is OFF

    :param daq_receiver: The daq_receiver fixture to use.
    """
    if daq_receiver.state() is not tango.DevState.OFF:
        daq_receiver.Off()
        sleep(2)
    assert daq_receiver.state() is tango.DevState.OFF


@given("the DAQ is in health state UNKNOWN")
def daq_device_is_unknown_health(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is in health mode unknown

    :param daq_receiver: The daq_receiver fixture to use.
    """
    if daq_receiver.healthState is not HealthState.UNKNOWN:
        pytest.fail('Initial conditions not met, health state not unknown')


@given("the DAQ is in adminMode")
def daq_device_is_in_adminMode(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is in admin mode ONLINE

    :param daq_receiver: The daq_receiver fixture to use.
    """

    if daq_receiver.adminMode is not AdminMode.OFFLINE:
        daq_receiver.adminMode = AdminMode.ONLINE
    assert daq_receiver.adminMode is AdminMode.ONLINE


@when("I send the ON command")
def daq_sent_on_command(daq_receiver: tango.DeviceProxy) -> None:
    """
    Send to on command to the daq receiver

    :param daq_receiver: The daq_receiver fixture to use.
    """

    print("attempting to turn on daq")
    daq_receiver.On()
    sleep(2)


@then("the DAQ is in the ON state")
def check_daq_is_on(daq_receiver: tango.DeviceProxy) -> None:
    """
    Check that the daq receiver is on.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    assert daq_receiver.state() is tango.DevState.ON
    print("daq in on state")


@then("the DAQ is in health state OK")
def check_daq_is_healthy(daq_receiver: tango.DeviceProxy) -> None:
    """
    Check that the daq receiver is healthy.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    assert daq_receiver.healthState is AdminMode.ONLINE
    print("daq health mode is ONLINE")


@given("the DAQ is in the ON state")
def daq_device_is_on(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is ON

    :param daq_receiver: The daq_receiver fixture to use.
    """
    if daq_receiver.state() is not tango.DevState.ON:
        daq_receiver.On()
        sleep(2)
    assert daq_receiver.state() is tango.DevState.ON



@given("And the DAQ is in health state OK")
def daq_device_is_online_health(
    daq_receiver: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver is in health mode OK

    :param daq_receiver: The daq_receiver fixture to use.
    """

    if daq_receiver.healthState is not HealthState.OK:
        pytest.fail('Initial conditions not met, health state not OK')


@when("I send the OFF command")
def daq_sent_off_command(daq_receiver: tango.DeviceProxy) -> None:
    """
    Send to off command to the daq receiver

    :param daq_receiver: The daq_receiver fixture to use.
    """

    print("attempting to turn off daq")
    daq_receiver.Off()
    sleep(2)


@then("the DAQ is in the OFF state")
def check_daq_is_off(daq_receiver: tango.DeviceProxy) -> None:
    """
    Check that the daq receiver is off.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    assert daq_receiver.state() is tango.DevState.OFF
    print("daq in off state")


@when("I send the Configure command with raw data")
def daq_sent_configure_raw(daq_receiver: tango.DeviceProxy) -> None:
    """
    Send configure raw command to the daq receiver

    :param daq_receiver: The daq_receiver fixture to use.
    """

    print("configure raw sent")
    daq_receiver.Start("DaqModes.RAW_DATA")
    sleep(2)


@then("the DAQ is in raw data mode")
def check_daq_config_is_raw(daq_receiver: tango.DeviceProxy) -> None:
    """
    Check that the daq receiver is configured to receive raw data.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_status = json.loads(daq_receiver.daqstatus())
    running_commands = daq_status.get("Running Consumers")
    if "RAW_DATA" in running_commands:
        print("daq has raw data stream")
    else:
        pytest.fail('Raw data failed to start')


@when("I send the Configure command with channelised data")
def daq_sent_configure_channelised(daq_receiver: tango.DeviceProxy) -> None:
    """
    Send configure channelised command to the daq receiver

    :param daq_receiver: The daq_receiver fixture to use.
    """

    print("configure channelised sent")
    daq_receiver.Start("DaqModes.CHANNELISED_DATA")
    sleep(2)


@then("the DAQ is in channelised data mode")
def check_daq_config_is_channelised(daq_receiver: tango.DeviceProxy) -> None:
    """
    Check that the daq receiver is configured to receive channelised data.

    :param daq_receiver: The daq_receiver fixture to use.
    """
    daq_status = json.loads(daq_receiver.daqstatus())
    running_commands = daq_status.get("Running Consumers")
    if "CHANNELISED_DATA" in running_commands:
        print("daq has raw data stream")
    else:
        pytest.fail('Channelsied failed to start')


@given("the DAQ is receiving data")
def daq_is_receiving_data(daq_receiver: tango.DeviceProxy) -> None:
    """
    Assertthat the daq is receiving data and saving it to file

    :param daq_receiver: The daq_receiver fixture to use.
    """
    assert daq_receiver.dataReceivedResult()
