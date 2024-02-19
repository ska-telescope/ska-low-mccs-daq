# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the bandpass monitor functionality."""
from __future__ import annotations

import json
import time
from typing import Any

import numpy as np
import pytest
import tango
from pytest_bdd import given, parsers, scenarios, then, when
from ska_control_model import AdminMode
from ska_tango_testing.mock.placeholders import Anything
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from tests.functional.conftest import (
    expect_attribute,
    poll_until_consumers_stopped,
    poll_until_state_change,
)
from tests.harness import get_daq_name, get_subrack_name, get_tile_name

scenarios("./features/bandpass_monitor.feature")


@pytest.fixture(name="station_name")
def station_name_fixture(true_context: bool) -> str:
    """
    Return the name of the station under test.

    :param true_context: whether to test against an existing Tango deployment

    :return: the name of the station under test
    """
    if not true_context:
        pytest.skip(
            "This needs to be run in a true-context against a real DAQ deployment"
        )
    return "real-daq-1"


@pytest.fixture(name="plot_directory")
def plot_directory_fixture() -> str:
    """
    Return the directory that plots are stored to.

    :return: the directory that plots are stored to
    """
    return "/product/test_eb_id/low-mccs/test_scan_id/plots/"


@given(parsers.cfparse("interface {interface}"), target_fixture="interface")
def daq_interface(
    interface: str,
) -> str:
    """
    Interface to send/listen on.

    :param interface: The interface to send/listen on.

    :return: the network interface
    """
    return interface


@pytest.fixture(name="daq_config")
def daq_config_fixture(interface: str) -> dict[str, Any]:
    """
    Get the config to configure the daq with.

    :param interface: The interface to send/listen on.
    :return: the config to configure the DAQ with.
    """
    return {
        "directory": "/product/test_eb_id/ska-low-mccs/test_scan_id/",
        "nof_tiles": 1,
        "append_integrated": False,
        "receiver_interface": interface,
    }


@given("the DAQ is available", target_fixture="daq_device")
def daq_device_fixture(station_name: str) -> tango.DeviceProxy:
    """
    Return a ``tango.DeviceProxy`` to the DAQ device under test.

    :param station_name: the name of the station under test.

    :return: a ``tango.DeviceProxy`` to the DAQ device under test.
    """
    return tango.DeviceProxy(get_daq_name(station_name))


@given("the Tile is available", target_fixture="tile_device")
def tile_device_fixture(station_name: str) -> str:
    """
    Return a ``tango.DeviceProxy`` to the Tile device under test.

    :param station_name: the name of the station under test.

    :return: a ``tango.DeviceProxy`` to the Tile device under test.
    """
    return tango.DeviceProxy(get_tile_name(10, station_name))


@given("the Subrack is available", target_fixture="subrack_device")
def subrack_device_fixture(station_name: str) -> str:
    """
    Return a ``tango.DeviceProxy`` to the subrack device under test.

    :param station_name: the name of the station under test.

    :return: a ``tango.DeviceProxy`` to the subrack device under test.
    """
    return tango.DeviceProxy(get_subrack_name(1, station_name))


@given("the Tile is routed to the DAQ")
def tile_ready_to_send_to_daq(
    daq_device: tango.DeviceProxy,
    tile_device: tango.DeviceProxy,
    subrack_device: tango.DeviceProxy,
    change_event_callbacks: MockTangoEventCallbackGroup,
) -> None:
    """
    Configure the Daq device for select data type.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    :param tile_device: A 'tango.DeviceProxy' to the Tile device.
    :param subrack_device: A 'tango.DeviceProxy' to the Subrack device.
    :param change_event_callbacks: a dictionary of callables to be used as
        tango change event callbacks.
    """
    if subrack_device.state() != tango.DevState.ON:
        subrack_device.adminMode = 0
        poll_until_state_change(subrack_device, tango.DevState.ON, 5)

    if tile_device.state() != tango.DevState.ON:
        if tile_device.AdminMode != AdminMode.ONLINE:
            tile_device.subscribe_event(
                "adminMode",
                tango.EventType.CHANGE_EVENT,
                change_event_callbacks["tile_adminMode"],
            )
            tile_device.adminMode = 0
            change_event_callbacks["tile_adminMode"].assert_change_event(
                AdminMode.ONLINE, lookahead=2, consume_nonmatches=True
            )

        tile_device.on()
        poll_until_state_change(tile_device, tango.DevState.ON, 20)

    if tile_device.tileProgrammingState not in ["Initialised", "Synchronised"]:
        assert expect_attribute(
            tile_device, "tileProgrammingState", "Initialised", timeout=5.0
        )

    # Start the ADCs and SDP processing chain.
    if tile_device.tileProgrammingState != "Synchronised":
        tile_device.startacquisition("{}")
        assert expect_attribute(tile_device, "tileProgrammingState", "Synchronised")

    assert tile_device.tileProgrammingState == "Synchronised"

    daq_status = json.loads(daq_device.DaqStatus())

    tpm_lmc_config = {
        "mode": "1G",
        "destination_ip": daq_status["Receiver IP"][0],
        "destination_port": daq_status["Receiver Ports"][0],
    }
    tile_device.SetLmcDownload(json.dumps(tpm_lmc_config))


@given("no consumers are running")
def daq_device_has_no_running_consumers(
    daq_device: tango.DeviceProxy,
) -> None:
    """
    Assert that daq receiver has no running consumers.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    """
    if daq_device.state() != tango.DevState.ON:
        daq_device.adminMode = AdminMode.ONLINE
        poll_until_state_change(daq_device, tango.DevState.ON, 5)

    status = json.loads(daq_device.DaqStatus())
    if status["Running Consumers"] != []:
        daq_device.Stop()  # Stops *all* consumers.
        poll_until_consumers_stopped(daq_device)


@given("the bandpass monitor is not running")
def monitor_not_running(daq_device: tango.DeviceProxy) -> None:
    """
    Ensure that the bandpass monitor is not running.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    """
    if json.loads(daq_device.DaqStatus())["Bandpass Monitor"]:
        daq_device.StopBandpassMonitor()
        daq_monitor_stopped(daq_device)


@when(
    "the DAQ is commanded to start monitoring for bandpasses "
    "with `auto_handle_daq` set to `False`",
    target_fixture="no_auto_handle_result",
)
def daq_start_monitoring_no_auto_handle(
    daq_device: tango.DeviceProxy, plot_directory: str
) -> list:
    """
    Start monitoring for bandpasses without auto-handling starting the daq.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    :param plot_directory: the directory to plots are stored to.
    :return: result of the StartBandpassMonitor command.
    """
    argin = json.dumps({"auto_handle_daq": False, "plot_directory": plot_directory})
    return daq_device.StartBandpassMonitor(argin)


@then(
    "the DAQ rejects the command and reports that the integrated channel data consumer "
    "must be running to monitor for bandpasses"
)
def daq_reject_bandpass_need_consumer_running(
    daq_device: tango.DeviceProxy,
    no_auto_handle_result: list,
    change_event_callbacks: MockTangoEventCallbackGroup,
) -> None:
    """
    Confirm that the bandpass monitor did not start due to no consumer running.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    :param no_auto_handle_result: result of the StartBandpassMonitor command
    :param change_event_callbacks: a dictionary of callables to be used as
        tango change event callbacks.
    """
    daq_device.subscribe_event(
        "longRunningCommandResult",
        tango.EventType.CHANGE_EVENT,
        change_event_callbacks["daq_long_running_command_result"],
    )
    change_event_callbacks["daq_long_running_command_result"].assert_change_event(
        (
            no_auto_handle_result[1][0],
            '"INTEGRATED_CHANNEL_DATA consumer must be running before bandpasses '
            'can be monitored."',
        ),
        lookahead=3,
        consume_nonmatches=True,
    )


@given("the DAQ is configured")
def daq_configure(
    daq_device: tango.DeviceProxy,
    daq_config: dict[str, Any],
) -> None:
    """
    Configure the Daq device.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    :param daq_config: the config to configure the DAQ with.
    """
    # Set initial state.
    if daq_device.state() != tango.DevState.ON:
        daq_device.adminMode = AdminMode.ONLINE
        poll_until_state_change(daq_device, tango.DevState.ON, 5)

    # Configure DAQ
    daq_device.Configure(json.dumps(daq_config))


@given("the DAQ is started with the integrated channel data consumer")
def daq_integrated_channel_running(
    daq_device: tango.DeviceProxy,
    change_event_callbacks: MockTangoEventCallbackGroup,
) -> None:
    """
    Start the Daq device with integrated channel data.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    :param change_event_callbacks: a dictionary of callables to be used as
        tango change event callbacks.
    """
    daq_device.Start(json.dumps({"modes_to_start": "INTEGRATED_CHANNEL_DATA"}))

    daq_device.subscribe_event(
        "dataReceivedResult",
        tango.EventType.CHANGE_EVENT,
        change_event_callbacks["data_received_callback"],
    )
    change_event_callbacks["data_received_callback"].assert_change_event(Anything)
    time_elapsed = 0
    timeout = 10
    while time_elapsed < timeout:
        consumers = json.loads(daq_device.DaqStatus())["Running Consumers"]
        if consumers != [] and ["INTEGRATED_CHANNEL_DATA", 5] in consumers:
            break
        time.sleep(1)
        time_elapsed += 1
    assert ["INTEGRATED_CHANNEL_DATA", 5] in consumers


@given("the bandpass monitor is running")
def daq_bandpass_monitor_running(
    daq_device: tango.DeviceProxy,
    plot_directory: str,
    change_event_callbacks: MockTangoEventCallbackGroup,
) -> None:
    """
    Start the bandpass monitor.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    :param plot_directory: the directory to plots are stored to.
    :param change_event_callbacks: a dictionary of callables to be used as
        tango change event callbacks.
    """
    daq_device.subscribe_event(
        "xPolBandpass",
        tango.EventType.CHANGE_EVENT,
        change_event_callbacks["daq_xPolBandpass"],
    )
    daq_device.subscribe_event(
        "yPolBandpass",
        tango.EventType.CHANGE_EVENT,
        change_event_callbacks["daq_yPolBandpass"],
    )
    change_event_callbacks["daq_xPolBandpass"].assert_change_event(Anything)
    change_event_callbacks["daq_yPolBandpass"].assert_change_event(Anything)
    argin = json.dumps(
        {"auto_handle_daq": False, "plot_directory": plot_directory, "cadence": 0}
    )
    start_bandpass_result = daq_device.StartBandpassMonitor(argin)
    daq_device.subscribe_event(
        "longRunningCommandResult",
        tango.EventType.CHANGE_EVENT,
        change_event_callbacks["daq_long_running_command_result"],
    )
    change_event_callbacks["daq_long_running_command_result"].assert_change_event(
        (
            start_bandpass_result[1][0],
            '"Bandpass monitor active"',
        ),
        lookahead=12,
        consume_nonmatches=True,
    )
    verify_bandpass_state(daq_device, True)


@when("the DAQ is commanded to stop monitoring bandpasses")
def daq_stop_bandpass_monitor(daq_device: tango.DeviceProxy) -> None:
    """
    Stop monitoring for bandpasses.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    """
    result = daq_device.StopBandpassMonitor()
    assert result[1][0] == "Bandpass monitor stopping."


@then("the DAQ reports that it is stopping monitoring bandpasses")
def daq_monitor_stopped(
    daq_device: tango.DeviceProxy,
) -> None:
    """
    Confirm that the bandpass monitor process has stopped.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    """
    verify_bandpass_state(daq_device, False)


@when(
    "the Tile is commanded to send integrated channel data",
    target_fixture="initial_hdf5_count",
)
def tile_send_data(
    tile_device: tango.DeviceProxy,
) -> None:
    """
    Command the tile to start sending data.

    :param tile_device: A 'tango.DeviceProxy' to the Tile device.
    """
    tile_device.SendDataSamples(json.dumps({"data_type": "channel"}))


@then("the DAQ reports that it has received integrated channel data")
def daq_received_data(
    change_event_callbacks: MockTangoEventCallbackGroup,
) -> None:
    """
    Confirm Daq has received data.

    :param change_event_callbacks: a dictionary of callables to be used as
        tango change event callbacks.
    """
    change_event_callbacks["data_received_callback"].assert_change_event(
        ("integrated_channel", Anything)
    )


@then("the DAQ saves bandpass data to its relevant attributes")
def daq_bandpasses_saved(
    daq_device: tango.DeviceProxy,
    change_event_callbacks: MockTangoEventCallbackGroup,
) -> None:
    """
    Confirm the DAQ has stored bandpass data to its attributes.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    :param change_event_callbacks: a dictionary of callables to be used as
        tango change event callbacks.
    """
    change_event_callbacks["daq_xPolBandpass"].assert_change_event(Anything)
    assert np.count_nonzero(daq_device.xPolBandpass) > 0
    change_event_callbacks["daq_yPolBandpass"].assert_change_event(Anything)
    assert np.count_nonzero(daq_device.yPolBandpass) > 0


def verify_bandpass_state(daq_device: tango.DeviceProxy, state: bool) -> None:
    """
    Verify that the bandpass monitor is in the desired state.

    :param daq_device: A 'tango.DeviceProxy' to the Daq device.
    :param state: the desired state of the bandpass monitor.
    """
    time_elapsed = 0
    timeout = 10
    while time_elapsed < timeout:
        if json.loads(daq_device.DaqStatus())["Bandpass Monitor"] == state:
            break
        time.sleep(1)
        time_elapsed += 1
    assert json.loads(daq_device.DaqStatus())["Bandpass Monitor"] == state
