# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the bdd test steps of the daq status reporting."""
from __future__ import annotations

import json
from typing import Callable, Iterator

import pytest
import tango
from pytest_bdd import given, parsers, scenarios, then, when
from ska_control_model import AdminMode
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from tests.functional.conftest import (
    poll_until_consumer_running,
    poll_until_consumers_stopped,
)
from tests.harness import SpsTangoTestHarnessContext

scenarios("./features/daq_status_reporting.feature")


@given(
    parsers.cfparse("this test is running against station_cluster {station_name}"),
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


@given("an MccsDaqReceiver", target_fixture="daq_receiver")
def daq_receiver_fixture(
    test_context: SpsTangoTestHarnessContext,
) -> Iterator[tango.DeviceProxy]:
    """
    Yield the DAQ receiver device under test.

    :param test_context: the context in which the test is running.

    :yield: the DAQ receiver device
    """
    yield test_context.get_daq_device()


@given(parsers.cfparse("MccsDaqReceiver AdminMode is set to '{admin_mode_value}'"))
def admin_mode_set_to_value(
    daq_receiver: tango.DeviceProxy,
    admin_mode_value: str,
    change_event_callbacks: MockTangoEventCallbackGroup,
) -> None:
    """
    Ensure device AdminMode is in the correct state.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param admin_mode_value: The value the device's AdminMode attribute should have.
    :param change_event_callbacks: A change event callback group.
    """
    daq_receiver.subscribe_event(
        "state",
        tango.EventType.CHANGE_EVENT,
        change_event_callbacks["daq_state"],
    )
    if daq_receiver.adminMode != AdminMode[admin_mode_value]:
        daq_receiver.adminMode = admin_mode_value
    assert daq_receiver.adminMode == AdminMode[admin_mode_value]

    if AdminMode[admin_mode_value] == AdminMode.ONLINE:
        change_event_callbacks.assert_change_event(
            "daq_state", tango.DevState.ON, lookahead=5
        )
    elif AdminMode[admin_mode_value] == AdminMode.OFFLINE:
        change_event_callbacks.assert_change_event(
            "daq_state", tango.DevState.DISABLE, lookahead=5
        )


@given(parsers.cfparse("the MccsDaqReceiver HealthState is '{health_state}'"))
def ensure_health_is_in_state(
    daq_receiver: tango.DeviceProxy,
    health_state: str,
    # daq_component_manager: DaqComponentManager,
) -> None:
    """
    Ensure health is in the state specified by checking and changing it if needed.

    A health state of `UNKNOWN`, `FAILED` or `OK` is supplied and this
    method     checks that the daq receiver's health is in that state.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param health_state: The health state the device should be coerced into.
    """
    # :param daq_component_manager: The component manager for the device under test.
    pytest.xfail(reason="Not implemented yet")
    # health_map = {
    #     "OK": HealthState.OK,
    #     "UNKNOWN": HealthState.UNKNOWN,
    #     "FAILED": HealthState.FAILED,
    # }
    # assert health_state in health_map.keys()
    # target_health_state = health_map[health_state]

    # # Check HealthState and massage it into the proper state if necessary.
    # current_health_state = daq_receiver.GetDaqHealth()
    # if not (current_health_state == target_health_state):
    #     # If we're here then we're in the wrong state. If that state is FAILED then
    #     # clear the fault first.
    #     if current_health_state == HealthState.FAILED:
    #         daq_receiver.StateChangedCallback(json.dumps({"fault": False}))

    #     # If we want to be in FAILED then we don't care where we came from.
    #     # Call cb with fault.
    #     if target_health_state == HealthState.FAILED:
    #         daq_receiver.StateChangedCallback(json.dumps({"fault": True}))
    #     # Similarly to get to UNKNOWN we stop comms.
    #     elif target_health_state == HealthState.UNKNOWN:
    #         daq_component_manager.stop_communicating()
    #     # To get to OK we clear fault and start comms. We've cleared the fault already
    #     # so check if comms were established.
    #     elif (
    #         target_health_state == HealthState.OK
    #         and daq_component_manager.communication_state
    #         == CommunicationStatus.DISABLED
    #     ):
    #         daq_component_manager.start_communicating()

    # assert daq_receiver.GetDaqHealth() == target_health_state


@then(parsers.cfparse("the MccsDaqReceiver HealthState is '{health_state}'"))
def check_health_is_in_state(
    daq_receiver: tango.DeviceProxy, health_state: str
) -> None:
    """
    Check health is in the state specified without seeking to modify it.

    A health state of `UNKNOWN`, `FAILED` or `OK` is supplied and this
    method     checks that the daq receiver's health is in that state.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param health_state: The health state the device is expected to be in.
    """
    daq_status = json.loads(daq_receiver.DaqStatus())
    daq_health = daq_status["Daq Health"]
    assert health_state in daq_health


@when(parsers.cfparse("'{method}' is called"))
def method_is_called(
    daq_receiver: tango.DeviceProxy,
    method: str,
    # daq_component_manager: DaqComponentManager,
) -> None:
    """
    Call a method or perform an action.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param method: The name of the method to be called.

    :raises AssertionError: if an invalid method is supplied.
    """
    # # method_map = {bdd_method: [method_object, args]}
    # # These methods are called with arguments.
    # method_map_args = {
    #     "set_fault_bit": [
    #         daq_receiver.StateChangedCallback,
    #         json.dumps({"fault": True}),
    #     ],
    #     "unset_fault_bit": [
    #         daq_receiver.StateChangedCallback,
    #         json.dumps({"fault": False}),
    #     ],
    # }
    # These methods are not called with arguments.
    method_map_nargs = {
        "stop_daq": [daq_receiver.Stop],
        "daq_status": [daq_receiver.DaqStatus],
    }
    # if method in method_map_args:
    #     method_map_args[method][0](method_map_args[method][1])
    if method in method_map_nargs:
        method_map_nargs[method][0]()
    else:
        raise AssertionError(f"{method} not found in method map!")


@given("no consumers are running")
def ensure_no_consumers_running(daq_receiver: tango.DeviceProxy) -> None:
    """
    Ensure no consumers are running by checking and changing it if needed.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    """
    status = json.loads(daq_receiver.DaqStatus())
    if status["Running Consumers"] != []:
        daq_receiver.Stop()  # Stops *all* consumers.
        poll_until_consumers_stopped(daq_receiver)


@when(parsers.cfparse("'{consumer}' is started"))
def start_consumer(daq_receiver: tango.DeviceProxy, consumer: str) -> None:
    """
    Start the consumer specified.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param consumer: The consumer to start.
    """
    daq_receiver.Start(json.dumps({"modes_to_start": consumer}))


@then(parsers.cfparse("consumer_status attribute shows '{consumer}' as running"))
def check_consumer_is_running(daq_receiver: tango.DeviceProxy, consumer: str) -> None:
    """
    Check that `consumer` is running.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param consumer: The consumer whose running status we are to confirm.
    """
    poll_until_consumer_running(daq_receiver, consumer, 25)


@pytest.fixture(name="all_available_consumers")
def all_available_consumers_fixture() -> list[str]:
    """
    All consumers list.

    :return: a list of all available consumers.
    """
    return [
        "ANTENNA_BUFFER",
        "BEAM_DATA",
        "CHANNEL_DATA",
        "CONTINUOUS_CHANNEL_DATA",
        "INTEGRATED_BEAM_DATA",
        "INTEGRATED_CHANNEL_DATA",
        "RAW_DATA",
        "STATION_BEAM_DATA",
    ]


@given("all consumers are running")
def start_all_consumers(
    daq_receiver: tango.DeviceProxy, all_available_consumers: list[str]
) -> None:
    """
    Start all available consumers.

    This starts all consumers except for CORRELATOR_DATA as it is
    unavailable.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param all_available_consumers: A list of all DaqModes/consumers.
    """
    daq_receiver.Start(
        json.dumps({"modes_to_start": ",".join(all_available_consumers)})
    )
    for consumer in all_available_consumers:
        poll_until_consumer_running(daq_receiver, consumer)


@then("consumer_status attribute shows no consumers are running")
def check_no_consumers_running(daq_receiver: tango.DeviceProxy) -> None:
    """
    Check no consumers are running without seeking to change it.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    """
    poll_until_consumers_stopped(daq_receiver)


@given(parsers.cfparse("the MccsDaqReceiver has a particular '{configuration}'"))
def daq_has_specific_config(
    daq_receiver: tango.DeviceProxy, configuration: str
) -> None:
    """
    Set the MccsDaqReceiver up with a particular configuration.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param configuration: The configuration to be applied.
    """
    pytest.xfail(reason="Not implemented yet")
    # print(configuration)
    # print(daq_receiver)  # so mypy doesnt complain
    # # Set up the daq configuration here.
    # # daq_receiver.Configure(configuration)


@then(parsers.cfparse("it returns the '{expected_status}'"))
def daq_has_specific_status(
    daq_receiver: tango.DeviceProxy, expected_status: str
) -> None:
    """
    Check the status of the MccsDaqReceiver is as expected.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param expected_status: The expected status of the MccsDaqReceiver.
    """
    pytest.xfail(reason="Not implemented yet")
    # print(expected_status)
    # print(daq_receiver)  # so mypy doesnt complain
    # # daq_state = daq_receiver.DaqStatus()
    # # Do checks on return of DaqState command here.
    # # The DaqState command is expected to return:
    # # - HealthState
    # # - Consumer list + running state.
    # # - List of ports being monitored
    # # - Interface being monitored.
    # # - Receiver uptime. (Will require keeping track in MccsDaqReceiver somewhere)
    # # - Other misc data stuff eventually (packets rec/tx, time since last pkt, rough
    # # data rates, disk space etcetc)
