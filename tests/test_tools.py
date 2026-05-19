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

import json
import time
from typing import Any

import tango
from ska_control_model import AdminMode, ResultCode


def get_lrc_finished(
    device_proxy: tango.DeviceProxy,
    uid: str,
) -> dict[str, Any]:
    """
    Return the finished LRC entry matching the given UID.

    Asserts that an entry with the given UID exists in ``lrcfinished``.
    The returned dict can be used to make further field-level assertions.

    :param device_proxy: device proxy for use in the test.
    :param uid: the UID of the LRC to look up.
    :return: the parsed LRC finished entry.
    """
    for completed_task in device_proxy.lrcfinished:
        completed_task = json.loads(completed_task)
        if completed_task["uid"] == uid:
            return completed_task
    return {}


def assert_against_lrc_finished(
    device: tango.DeviceProxy, command_id: str, status: str, timeout: float = 10.0
) -> None:
    """
    Wait for command to finish and assert against the status.

    :param device: the tango device to monitor.
    :param command_id: The command_id to look for in the queue.
    :param status: The expected status of the command in the queue.
    :param timeout: An optional time to wait in seconds.

    :raises TimeoutError: When the command failed to enter the queue in time.
    """
    completed_task = get_lrc_finished(device, command_id)
    start_time = time.time()
    while not completed_task:
        time.sleep(0.1)
        completed_task = get_lrc_finished(device, command_id)
        if time.time() - start_time > timeout:
            raise TimeoutError(
                f"LRC '{command_id}' not found in completed after {timeout} seconds"
            )
    assert completed_task["status"] == status


def execute_lrc_to_completion(
    device_proxy: tango.DeviceProxy,
    command_name: str,
    command_arguments: Any,
) -> None:
    """
    Execute a LRC to completion.

    :param device_proxy: fixture that provides a
        :py:class:`tango.DeviceProxy` to the device under test, in a
        :py:class:`tango.test_context.DeviceTestContext`.
    :param command_name: the name of the device command under test
    :param command_arguments: argument to the command (optional)
    """
    [[task_status], [command_id]] = getattr(device_proxy, command_name)(
        command_arguments
    )

    assert task_status == ResultCode.QUEUED
    assert command_name in command_id.split("_")[-1]

    assert_against_lrc_finished(device_proxy, command_id, "COMPLETED")


def retry_communication(device_proxy: tango.Deviceproxy, timeout: int = 30) -> None:
    """
    Retry communication with the backend.

    NOTE: This is to be used for devices that do not know if the backend is available
    at the time of the call. For example the daq_handler backend gRPC server
    may not be ready when we try to start communicating.
    In this case we will retry connection.

    :param device_proxy: A 'tango.DeviceProxy' to the backend device.
    :param timeout: A max time in seconds before we give up trying
    """
    tick = 2
    if device_proxy.adminMode != AdminMode.ONLINE:
        terminate_time = time.time() + timeout
        while time.time() < terminate_time:
            try:
                device_proxy.adminMode = AdminMode.ONLINE
                break
            except tango.DevFailed:
                print(f"{device_proxy.dev_name()} failed to communicate with backend.")
                time.sleep(tick)
        assert device_proxy.adminMode == AdminMode.ONLINE
    else:
        print(f"Device {device_proxy.dev_name()} is already ONLINE nothing to do.")
