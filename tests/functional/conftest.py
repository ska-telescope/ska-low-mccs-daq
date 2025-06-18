# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains pytest-specific test harness for SPSHW functional tests."""
from __future__ import annotations

import json
import os
import queue
import time
from time import sleep
from typing import Any, Callable, Iterator

import _pytest
import pytest
import tango
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from tests.harness import SpsTangoTestHarness, SpsTangoTestHarnessContext


# TODO: https://github.com/pytest-dev/pytest-forked/issues/67
# We're stuck on pytest 6.2 until this gets fixed, and this version of
# pytest is not fully typehinted
def pytest_addoption(
    parser: _pytest.config.argparsing.Parser,  # type: ignore[name-defined]
) -> None:
    """
    Add a command line option to pytest.

    This is a pytest hook, here implemented to add the `--true-context`
    option, used to indicate that a true Tango subsystem is available,
    so there is no need for the test harness to spin up a Tango test
    context.

    :param parser: the command line options parser
    """
    parser.addoption(
        "--true-context",
        action="store_true",
        default=False,
        help=(
            "Tell pytest that you have a true Tango context and don't "
            "need to spin up a Tango test context"
        ),
    )
    parser.addoption(
        "--hw-deployment",
        action="store_true",
        default=False,
        help=(
            "Tell pytest that you have a true Tango context against HW and can "
            "run HW only tests"
        ),
    )


@pytest.fixture(name="exported_daqs")
def exported_daq_fixture(true_context: bool) -> list[tango.DeviceProxy]:
    """
    Return the trls of the daq under test.

    :param true_context: whether to test against an existing Tango deployment

    :return: A list containing the ``tango.DeviceProxy`` of the exported daqs.
        Or Empty list if no devices exported.
    """
    if true_context:
        return [
            tango.DeviceProxy(trl)
            for trl in tango.Database().get_device_exported("low-mccs/daqreceiver/*")
        ]
    return []


@pytest.fixture(name="functional_test_context_generator", scope="module")
def functional_test_context_generator_fixture(
    true_context: bool,
    daq_id: int,
) -> Callable:
    """
    Return a callable to generate a context containing the device/s under test.

    :param true_context: whether to test against an existing Tango
        deployment
    :param daq_id: the ID of the daq receiver

    :return: a callable to generate context containing the devices under test
    """

    def _generate(station_label: str) -> Iterator[SpsTangoTestHarnessContext]:
        harness = SpsTangoTestHarness(station_label)

        if not true_context:
            harness.set_lmc_daq_device(
                daq_id,
                address=None,  # dynamically get address of DAQ instance
            )

        with harness as context:
            yield context

    return _generate


@pytest.fixture(name="true_context", scope="session")
def true_context_fixture(request: pytest.FixtureRequest) -> bool:
    """
    Return whether to test against an existing Tango deployment.

    If True, then Tango is already deployed, and the tests will be run
    against that deployment.

    If False, then Tango is not deployed, so the test harness will stand
    up a test context and run the tests against that.

    :param request: A pytest object giving access to the requesting test
        context.

    :return: whether to test against an existing Tango deployment
    """
    if request.config.getoption("--true-context"):
        return True
    if os.getenv("TRUE_TANGO_CONTEXT", None):
        return True
    return False


@pytest.fixture(name="hw_context", scope="session")
def hw_context_fixture(request: pytest.FixtureRequest) -> bool:
    """
    Return whether to test against an real HW only.

    :param request: A pytest object giving access to the requesting test
        context.

    :return: whether to to test against an real HW only.
    """
    return request.config.getoption("--hw-deployment")


@pytest.fixture(name="station_label", scope="module")
def station_label_fixture() -> str | None:
    """
    Return the name of the station under test.

    :return: the name of the station under test.
    """
    return os.environ.get("STATION_LABEL")


@pytest.fixture(name="functional_test_context", scope="module")
def functional_test_context_fixture(
    true_context: bool,
    station_label: str | None,
    daq_id: int,
) -> Iterator[SpsTangoTestHarnessContext]:
    """
    Yield a Tango context containing the device/s under test.

    :param true_context: whether to test against an existing Tango
        deployment
    :param station_label: name of the station under test.
    :param daq_id: the ID of the daq receiver

    :yields: a Tango context containing the devices under test
    """
    harness = SpsTangoTestHarness(station_label)

    if not true_context:
        harness.set_lmc_daq_device(
            daq_id,
            address=None,  # dynamically get address of DAQ instance
        )

    with harness as context:
        yield context


@pytest.fixture(name="change_event_callbacks", scope="module")
def change_event_callbacks_fixture() -> MockTangoEventCallbackGroup:
    """
    Return a dictionary of callables to be used as Tango change event callbacks.

    :return: a dictionary of callables to be used as tango change event
        callbacks.
    """
    return MockTangoEventCallbackGroup(
        "daq_state",
        "daq_long_running_command_status",
        "daq_long_running_command_result",
        "daq_xPolBandpass",
        "daq_yPolBandpass",
        "data_received_callback",
        "device_state",
        "device_adminmode",
        timeout=30.0,
    )


@pytest.fixture(name="acquisition_duration", scope="session")
def acquisition_duration_fixture() -> int:
    """
    Return the duration of data capture in seconds.

    :return: Duration of data capture.
    """
    return 2


# pylint: disable=inconsistent-return-statements
def poll_until_consumer_running(
    daq: tango.DeviceProxy, wanted_consumer: str, no_of_iters: int = 10
) -> None:
    """
    Poll until a specific consumer is running.

    This function recursively calls itself up to `no_of_iters` times.

    :param daq: the DAQ receiver Tango device
    :param wanted_consumer: the consumer we're waiting for
    :param no_of_iters: number of times to iterate
    """
    status = json.loads(daq.DaqStatus())
    for consumer in status["Running Consumers"]:
        if wanted_consumer in consumer:
            return

    if no_of_iters == 1:
        pytest.fail(f"Wanted consumer: {wanted_consumer} not started.")

    sleep(2)  # Waiting for SKUID to timeout...
    return poll_until_consumer_running(daq, wanted_consumer, no_of_iters - 1)


def poll_until_consumers_running(
    daq: tango.DeviceProxy, wanted_consumer_list: list[str], no_of_iters: int = 5
) -> None:
    """
    Poll until a list of consumers are running.

    :param daq: the DAQ receiver Tango device
    :param wanted_consumer_list: the consumers we're waiting for
    :param no_of_iters: number of times to iterate
    """
    for consumer in wanted_consumer_list:
        poll_until_consumer_running(daq, consumer, no_of_iters)


# pylint: disable=inconsistent-return-statements
def poll_until_consumers_stopped(daq: tango.DeviceProxy, no_of_iters: int = 5) -> None:
    """
    Poll until device is in wanted state.

    This function recursively calls itself up to `no_of_iters` times.

    :param daq: the DAQ receiver Tango device
    :param no_of_iters: number of times to iterate
    """
    status = json.loads(daq.DaqStatus())
    if status["Running Consumers"] == []:
        return

    if no_of_iters == 1:
        msg = f'Consumers not stopped: {status["Running Consumers"]}.\n'
        msg += f"CommandResult: {daq.longRunningCommandResult}\n"
        msg += f"CommandQueue: {daq.longRunningCommandsInQueue}\n"
        pytest.fail(msg)

    sleep(2)
    return poll_until_consumers_stopped(daq, no_of_iters - 1)


def poll_until_command_result(
    device: tango.DeviceProxy, cmd_id: str, expected_result: str, no_of_iters: int = 5
) -> None:
    """
    Poll until command has reached state.

    This function recursively calls itself up to `no_of_iters` times.

    :param device: the TANGO device
    :param expected_result: the command state we're waiting for
    :param cmd_id: The command ID we're interested in.
    :param no_of_iters: number of times to iterate
    """
    lrc_result = None
    lrc_status = device.longRunningCommandStatus
    try:
        # Extract the result of the cmd_id.
        lrc_result = lrc_status[lrc_status.index(cmd_id) + 1]
    except ValueError as e:
        lrc_result = e
        # pass
    if lrc_result == expected_result:
        return
    if no_of_iters == 1:
        pytest.fail(
            f"Command {cmd_id} did not reach desired state: "
            f"{device.longRunningCommandStatus}\n"
            f"Result: {lrc_result}"
        )
    if lrc_result != expected_result:
        time.sleep(1)
        poll_until_command_result(device, cmd_id, expected_result, no_of_iters - 1)


# pylint: disable=inconsistent-return-statements
def poll_until_state_change(
    device: tango.DeviceProxy, wanted_state: tango.DevState, no_of_iters: int = 5
) -> None:
    """
    Poll until device is in wanted state.

    This function recursively calls itself up to `no_of_iters` times.

    :param device: the TANGO device
    :param wanted_state: the state we're waiting for
    :param no_of_iters: number of times to iterate
    """
    if device.state() == wanted_state:
        return

    if no_of_iters == 1:
        pytest.fail(
            f"device not in desired state, \
        wanted: {wanted_state}, actual: {device.state()}"
        )

    sleep(2)
    return poll_until_state_change(device, wanted_state, no_of_iters - 1)


def expect_attribute(
    tango_device: tango.DeviceProxy,
    attr: str,
    value: Any,
    *,
    timeout: float = 60.0,
) -> bool:
    """
    Wait for Tango attribute to have a certain value using a subscription.

    Sets up a subscription to a Tango device attribute,
    waits for the attribute to have the provided value within a given time,
    then removes the subscription.

    :param tango_device: a DeviceProxy to a Tango device
    :param attr: the name of the attribute to be monitored
    :param value: the attribute value we're waiting for
    :param timeout: the maximum time to wait, in seconds
    :return: True if the attribute has the expected value within the given timeout
    """
    print(f"Expecting {tango_device.dev_name()}/{attr} == {value!r} within {timeout}s")
    _queue: queue.SimpleQueue[tango.EventData] = queue.SimpleQueue()
    subscription_id = tango_device.subscribe_event(
        attr,
        tango.EventType.CHANGE_EVENT,
        _queue.put,
    )
    deadline = time.time() + timeout
    try:
        while True:
            event = _queue.get(timeout=deadline - time.time())
            print(f"Got {tango_device.dev_name()}/{attr} == {event.attr_value.value!r}")
            if event.attr_value.value == value:
                return True
    finally:
        tango_device.unsubscribe_event(subscription_id)


def verify_bandpass_state(daq_device: tango.DeviceProxy, state: bool) -> None:
    """
    Verify that the bandpass monitor is in the desired state.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    :param state: the desired state of the bandpass monitor.
    """
    time_elapsed = 0
    timeout = 10
    while time_elapsed < timeout:
        daq_status = json.loads(daq_device.DaqStatus())
        if daq_status["Bandpass Monitor"] == state:
            break
        time.sleep(1)
        time_elapsed += 1
    assert daq_status["Bandpass Monitor"] == state
