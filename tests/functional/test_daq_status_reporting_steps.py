# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the bdd test steps of the daq status reporting."""
from __future__ import annotations

from typing import Iterator

import pytest
import tango
from pytest_bdd import given, parsers, scenarios, then, when

from tests.harness import SpsTangoTestHarnessContext

scenarios("./features/daq_status_reporting.feature")


@given("an MccsDaqReceiver", target_fixture="daq_receiver")
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


@given(parsers.cfparse("MccsDaqReceiver AdminMode is set to '{admin_mode_value}'"))
def admin_mode_set_to_value(
    daq_receiver: tango.DeviceProxy, admin_mode_value: str
) -> None:
    """
    Ensure device AdminMode is in the correct state.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param admin_mode_value: The value the device's AdminMode attribute should have.
    """
    pytest.xfail(reason="Not implemented yet")
    # daq_receiver.adminMode = admin_mode_value
    # assert daq_receiver.adminMode == AdminMode[admin_mode_value]


@given(parsers.cfparse("communications are '{communication_state}'"))
def comms_are_in_state(
    communication_state: str,
) -> None:
    """
    Ensure communications are in the state specified.

    A communication_state of `established` or `disabled` is supplied and
    this method checks that the daq receiver comms is in that state.

    :param communication_state: The communication state the device is expected to be in.
    """
    # :param daq_component_manager: The component manager for the device under test.
    pytest.xfail(reason="Not implemented yet")
    # comms_map = {
    #     "established": CommunicationStatus.ESTABLISHED,
    #     "disabled": CommunicationStatus.DISABLED,
    # }
    # # Check comms state of receiver. If wrong state call start/stop comms.
    # assert communication_state in comms_map.keys()
    # target_comms_state = comms_map[communication_state]

    # # Check if we're in the wrong comms state. If so call start/stop comms to get to
    # # the right state.
    # if not (daq_component_manager.communication_state == target_comms_state):
    #     if communication_state == "disabled":
    #         daq_component_manager.stop_communicating()
    #         communication_state_changed_callback.assert_last_call(
    #             CommunicationStatus.DISABLED
    #         )
    #     else:
    #         daq_component_manager.start_communicating()
    #         communication_state_changed_callback.assert_next_call(
    #             CommunicationStatus.NOT_ESTABLISHED
    #         )
    #         communication_state_changed_callback.assert_next_call(
    #             CommunicationStatus.ESTABLISHED
    #         )

    # assert daq_component_manager.communication_state == target_comms_state


@given(parsers.cfparse("the fault bit is '{fault_state}'"))
def fault_is_set_unset(daq_receiver: tango.DeviceProxy, fault_state: str) -> None:
    """
    Ensure fault bit is in the state specified.

    A fault bit state of `set` or `unset` is supplied and this method
    checks that the daq receiver fault is in that state.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param fault_state: The fault state the device should be in.
    """
    pytest.xfail(reason="Not implemented yet")
    # fault_map = {"set": True, "not_set": False}
    # # Check fault bit and set/unset as/if required.
    # assert fault_state in fault_map.keys()
    # target_fault_state = fault_map[fault_state]

    # # Check if we're in the wrong fault state. If so call callback to set fault.
    # if not (daq_receiver.GetDaqFault() == target_fault_state):
    #     argin = {"fault": target_fault_state}
    #     daq_receiver.StateChangedCallback(json.dumps(argin))
    # assert daq_receiver.GetDaqFault() == target_fault_state


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
    pytest.xfail(reason="Not implemented yet")
    # health_map = {
    #     "OK": HealthState.OK,
    #     "UNKNOWN": HealthState.UNKNOWN,
    #     "FAILED": HealthState.FAILED,
    # }
    # assert health_state in health_map.keys()
    # assert daq_receiver.GetDaqHealth() == health_map[health_state]


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
    """
    # :param daq_component_manager: The component manager for the device under test.
    # :raises AssertionError: if an invalid method is supplied.
    pytest.xfail(reason="Not implemented yet")
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
    # # These methods are not called with arguments.
    # # TODO: remove the following line
    # if method == "daq_status":
    #     return
    # method_map_nargs = {
    #     "establish_comms": [daq_component_manager.start_communicating],
    #     "unestablish_comms": [daq_component_manager.stop_communicating],
    #     "stop_daq": [daq_receiver.Stop],
    #     # "daq_status": [daq_receiver.DaqStatus]
    #     # TODO: DaqStatus command needs implementing.
    # }
    # if method in method_map_args.keys():
    #     method_map_args[method][0](method_map_args[method][1])
    # elif method in method_map_nargs.keys():
    #     method_map_nargs[method][0]()
    # else:
    #     raise AssertionError(f"{method} not found in method map!")


@given("no consumers are running")
def ensure_no_consumers_running(daq_receiver: tango.DeviceProxy) -> None:
    """
    Ensure no consumers are running by checking and changing it if needed.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    """
    pytest.xfail(reason="Not implemented yet")
    # running_consumer_list = json.loads(daq_receiver.GetRunningConsumers())
    # for (
    #     daq_mode,
    #     running,
    # ) in running_consumer_list:
    #     if running:
    #         daq_receiver.Stop()  # Stops *all* consumers.


@when(parsers.cfparse("'{consumer}' is started"))
def start_consumer(daq_receiver: tango.DeviceProxy, consumer: str) -> None:
    """
    Start the consumer specified.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param consumer: The consumer to start.
    """
    pytest.xfail(reason="Not implemented yet")
    # daq_mode = DaqModes[consumer]
    # daq_receiver.Start(json.dumps({"modes_to_start": [daq_mode]}))
    # # Race condition here waiting for consumers to start.
    # # TODO: Check the task_callback for Start and wait here until it finishes rather
    # # than sleep.
    # # time.sleep(3)


@then(parsers.cfparse("consumer_status attribute shows '{consumer}' as running"))
def check_consumer_is_running(daq_receiver: tango.DeviceProxy, consumer: str) -> None:
    """
    Check that `consumer` is running.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    :param consumer: The consumer whose running status we are to confirm.
    """
    pytest.xfail(reason="Not implemented yet")
    # daq_mode = str(DaqModes[consumer].value)  # This is a bit of a fiddle.
    # running_consumer_list = json.loads(daq_receiver.GetRunningConsumers())
    # assert running_consumer_list[daq_mode]


# @pytest.fixture(name="all_available_consumers")
# def all_available_consumers_fixture() -> list[DaqModes]:
#     """
#     All consumers list.

#     :return: a list of all available consumers.
#     """
#     return [
#         DaqModes.ANTENNA_BUFFER,
#         DaqModes.BEAM_DATA,
#         DaqModes.CHANNEL_DATA,
#         DaqModes.CONTINUOUS_CHANNEL_DATA,
#         DaqModes.INTEGRATED_BEAM_DATA,
#         DaqModes.INTEGRATED_CHANNEL_DATA,
#         DaqModes.RAW_DATA,
#         DaqModes.STATION_BEAM_DATA,
#     ]


@given("all consumers are running")
def start_all_consumers(
    daq_receiver: tango.DeviceProxy,
    # all_available_consumers: list[DaqModes]
) -> None:
    """
    Start all available consumers.

    This starts all consumers except for CORRELATOR_DATA as it is
    unavailable.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    """
    # :param all_available_consumers: A list of all DaqModes/consumers.
    pytest.xfail(reason="Not implemented yet")
    # daq_receiver.Start(json.dumps({"modes_to_start": all_available_consumers}))
    # # TODO: Have a better solution to the race condition than sleeping.
    # time.sleep(3)


@given("consumer_status attribute shows all consumers are running")
def check_all_consumers_running(
    daq_receiver: tango.DeviceProxy,
    # all_available_consumers: list[DaqModes]
) -> None:
    """
    Check that all available consumers are running.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    """
    # :param all_available_consumers: A list of all DaqModes/consumers.
    pytest.xfail(reason="Not implemented yet")
    # running_consumer_list = json.loads(daq_receiver.GetRunningConsumers())
    # for consumer in all_available_consumers:
    #     assert running_consumer_list[str(consumer.value)]


@then("consumer_status attribute shows no consumers are running")
def check_no_consumers_running(daq_receiver: tango.DeviceProxy) -> None:
    """
    Check no consumers are running without seeking to change it.

    :param daq_receiver: A proxy to the MccsDaqReceiver device under test.
    """
    pytest.xfail(reason="Not implemented yet")
    # # TODO: Stopping consumers can take a while. Replace this sleep with a test.
    # # time.sleep(5)
    # running_consumer_list = json.loads(daq_receiver.GetRunningConsumers())
    # for running in running_consumer_list.values():
    #     assert not running


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
