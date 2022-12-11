# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq receiver device."""
from __future__ import annotations

import gc
import json
import unittest.mock
from time import sleep
from typing import Generator, Union

import pytest
import tango
from pydaq.daq_receiver_interface import DaqModes
from ska_control_model import AdminMode, HealthState, ResultCode
from ska_tango_testing.context import (
    TangoContextProtocol,
    ThreadedTestTangoContextManager,
)
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from ska_low_mccs_daq import MccsDaqReceiver

# TODO: [MCCS-1211] Workaround for ska-tango-testing bug.
gc.disable()


@pytest.fixture(name="daq_name")
def daq_name_fixture(daq_id: str) -> str:
    """
    Return the name of this daq receiver.

    :param daq_id: The ID of this daq receiver.

    :return: the name of this daq receiver.
    """
    return f"low-mccs-daq/daqreceiver/{daq_id.zfill(3)}"


@pytest.fixture(name="device_under_test")
def device_under_test_fixture(
    tango_harness: TangoContextProtocol,
    daq_name: str,
) -> tango.DeviceProxy:
    """
    Fixture that returns the device under test.

    :param tango_harness: a test harness for Tango devices
    :param daq_name: name of the DAQ receiver Tango device

    :return: the device under test
    """
    return tango_harness.get_device(daq_name)


class TestMccsDaqReceiver:
    """Test class for MccsDaqReceiver tests."""

    @pytest.fixture(name="tango_harness")
    def tango_harness_fixture(  # pylint: disable=too-many-arguments
        self,
        daq_name: str,
        daq_id: str,
        receiver_interface: str,
        receiver_ip: str,
        receiver_ports: str,
    ) -> Generator[TangoContextProtocol, None, None]:
        """
        Return a tango harness against which to run tests of the deployment.

        :param daq_name: name of the DAQ receiver Tango device
        :param daq_id: id of the DAQ receiver
        :param receiver_interface: network interface on which the DAQ
            receiver receives packets
        :param receiver_ip: IP address on which the DAQ receiver receives
            packets
        :param receiver_ports: port on which the DAQ receiver receives
            packets.

        :yields: a tango context.
        """
        context_manager = ThreadedTestTangoContextManager()
        context_manager.add_device(
            daq_name,
            MccsDaqReceiver,
            DaqId=daq_id,
            ReceiverInterface=receiver_interface,
            ReceiverIp=receiver_ip,
            ReceiverPorts=receiver_ports,
            ConsumersToStart=["DaqModes.INTEGRATED_CHANNEL_DATA"],
            LoggingLevelDefault=3,
        )
        with context_manager as context:
            yield context

    def test_healthState(
        self: TestMccsDaqReceiver,
        device_under_test: tango.DeviceProxy,
        change_event_callbacks: MockTangoEventCallbackGroup,
    ) -> None:
        """
        Test for healthState.

        :param device_under_test: fixture that provides a
            :py:class:`tango.DeviceProxy` to the device under test, in a
            :py:class:`tango.test_context.DeviceTestContext`.
        :param change_event_callbacks: group of Tango change event
            callback with asynchrony support
        """
        device_under_test.subscribe_event(
            "healthState",
            tango.EventType.CHANGE_EVENT,
            change_event_callbacks["healthState"],
        )
        change_event_callbacks.assert_change_event("healthState", HealthState.UNKNOWN)
        assert device_under_test.healthState == HealthState.UNKNOWN

    @pytest.mark.parametrize(
        "modes_to_start, daq_interface, daq_ports, daq_ip",
        [
            ([DaqModes.INTEGRATED_CHANNEL_DATA], "lo", [4567], "123.456.789.000"),
            (
                [DaqModes.ANTENNA_BUFFER, DaqModes.RAW_DATA],
                "eth0",
                [9873, 4952],
                "098.765.432.111",
            ),
        ],
    )
    # pylint: disable=too-many-arguments
    def test_status(
        self: TestMccsDaqReceiver,
        device_under_test: tango.DeviceProxy,
        modes_to_start: list[DaqModes],
        daq_interface: str,
        daq_ports: list[int],
        daq_ip: str,
    ) -> None:
        """
        Test for DaqStatus.

        Here we configure DAQ with some non-default settings and then
            call DaqStatus to check that it reports the correct info.

        :param modes_to_start: A list of consumers/DaqModes to start.
        :param daq_interface: The interface for daq to listen on.
        :param daq_ports: A list of ports for daq to listen on.
        :param daq_ip: The ip address of daq.
        :param device_under_test: fixture that provides a
            :py:class:`tango.DeviceProxy` to the device under test, in a
            :py:class:`tango.test_context.DeviceTestContext`.
        """
        # Set adminMode so we can control device.
        device_under_test.adminMode = AdminMode.ONLINE

        # Configure.
        daq_config = {
            "receiver_ports": daq_ports,
            "receiver_interface": daq_interface,
            "receiver_ip": daq_ip,
        }
        device_under_test.Configure(json.dumps(daq_config))
        # Start a consumer to check with DaqStatus.
        device_under_test.Start(json.dumps({"modes_to_start": modes_to_start}))
        # We can't check immediately so wait for consumer(s) to start.

        # I'd like to pass `task_callback=MockCallback()` to `Start`.
        # However it isn't json serializable so we can't do that here.
        # Instead we resort to this...
        sleep(2)

        # Check status.
        status = json.loads(device_under_test.DaqStatus())
        # Check health is OK (as it must be to do this test)
        assert status["Daq Health"] == [HealthState.OK.name, HealthState.OK.value]
        # Check the consumers we specified to run are in this list.
        assert status["Running Consumers"] == [
            [consumer.name, consumer.value] for consumer in modes_to_start
        ]
        # Check it reports we're listening on the interface we chose.
        assert status["Receiver Interface"] == daq_interface
        # Check the IP is what we chose.
        assert status["Receiver IP"] == [daq_ip]


class TestPatchedDaq:
    """
    Test class for MccsDaqReceiver tests that patches the component manager.

    These are thin tests that simply test that commands invoked on the
    device are passed through to the component manager
    """

    @pytest.fixture(name="tango_harness")
    def tango_harness_fixture(  # pylint: disable=too-many-arguments
        self,
        mock_component_manager: unittest.mock.Mock,
        daq_name: str,
        daq_id: str,
        receiver_interface: str,
        receiver_ip: str,
        receiver_ports: str,
    ) -> Generator[TangoContextProtocol, None, None]:
        """
        Return a tango harness against which to run tests of the deployment.

        :param mock_component_manager: a mock to be injected into the
            tango device under test, to take the place of its component
            manager.
        :param daq_name: name of the DAQ receiver Tango device
        :param daq_id: id of the DAQ receiver
        :param receiver_interface: network interface on which the DAQ
            receiver receives packets
        :param receiver_ip: IP address on which the DAQ receiver receives
            packets
        :param receiver_ports: port on which the DAQ receiver receives
            packets.

        :yields: a tango context.
        """

        class _PatchedDaqReceiver(MccsDaqReceiver):
            """A daq class that has had its component manager mocked out for testing."""

            def create_component_manager(self) -> unittest.mock.Mock:
                """
                Return a mock component manager instead of the usual one.

                :return: a mock component manager
                """
                return mock_component_manager

        context_manager = ThreadedTestTangoContextManager()
        context_manager.add_device(
            daq_name,
            _PatchedDaqReceiver,
            DaqId=daq_id,
            ReceiverInterface=receiver_interface,
            ReceiverIp=receiver_ip,
            ReceiverPorts=receiver_ports,
            ConsumersToStart=["DaqModes.INTEGRATED_CHANNEL_DATA"],
            LoggingLevelDefault=3,
        )
        with context_manager as context:
            yield context

    @pytest.mark.parametrize(
        "daq_modes",
        ([DaqModes.CHANNEL_DATA, DaqModes.BEAM_DATA, DaqModes.RAW_DATA], [1, 2, 0]),
    )
    def test_start_daq_device(
        self: TestPatchedDaq,
        device_under_test: tango.DeviceProxy,
        mock_component_manager: unittest.mock.Mock,
        daq_modes: list[Union[int, DaqModes]],
    ) -> None:
        """
        Test for Start().

        This tests that when we pass a valid json string to the `Start`
        command that it is successfully parsed into the proper
        parameters so that `start_daq` can be called.

        :param device_under_test: fixture that provides a
            :py:class:`tango.DeviceProxy` to the device under test, in a
            :py:class:`tango.test_context.DeviceTestContext`.
        :param mock_component_manager: a mock component manager that has
            been patched into the device under test
        :param daq_modes: The DAQ consumers to start.
        """
        device_under_test.adminMode = AdminMode.ONLINE

        cbs = ["raw_data_cb", "beam_data_cb"]
        argin = {
            "modes_to_start": daq_modes,
            "callbacks": cbs,
        }
        [result_code], [response] = device_under_test.Start(json.dumps(argin))

        assert result_code == ResultCode.QUEUED
        assert "Start" in response.split("_")[-1]

        call_args = mock_component_manager.start_daq.call_args
        assert call_args.args[0] == daq_modes
        assert call_args.args[1] == cbs

    @pytest.mark.parametrize(
        ("consumer_list"),
        (
            "DaqModes.RAW_DATA",
            "DaqModes.CHANNEL_DATA",
            "DaqModes.BEAM_DATA",
            "DaqModes.CONTINUOUS_CHANNEL_DATA",
            "DaqModes.INTEGRATED_BEAM_DATA",
            "DaqModes.INTEGRATED_CHANNEL_DATA",
            "DaqModes.STATION_BEAM_DATA",
            "DaqModes.CORRELATOR_DATA",
            "DaqModes.ANTENNA_BUFFER",
            (
                "DaqModes.INTEGRATED_BEAM_DATA,ANTENNA_BUFFER, BEAM_DATA,"
                "DaqModes.INTEGRATED_CHANNEL_DATA"
            ),
        ),
    )
    def test_set_consumers_device(
        self: TestPatchedDaq,
        device_under_test: tango.DeviceProxy,
        mock_component_manager: unittest.mock.Mock,
        consumer_list: list[Union[int, DaqModes]],
    ) -> None:
        """
        Test for SetConsumers().

        This tests that when we pass a valid string to the `SetConsumers`
        command that it is successfully passed to the component manager.

        :param device_under_test: fixture that provides a
            :py:class:`tango.DeviceProxy` to the device under test, in a
            :py:class:`tango.test_context.DeviceTestContext`.
        :param mock_component_manager: a mock component manager that has
            been patched into the device under test
        :param consumer_list: A comma separated list of consumers to start.
        """
        [result_code], [response] = device_under_test.SetConsumers(consumer_list)
        assert result_code == ResultCode.OK
        assert response == "SetConsumers command completed OK"

        # Get the args for the next call to set consumers and assert
        # it's what we expect.
        call_args = mock_component_manager._set_consumers_to_start.call_args
        assert call_args.args[0] == consumer_list
