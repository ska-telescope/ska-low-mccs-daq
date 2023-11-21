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
from typing import Iterator, Type, Union

import pytest
import pytest_mock
import tango
from ska_control_model import AdminMode, HealthState, ResultCode
from ska_tango_testing.mock.placeholders import Anything
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup
from tango.server import Device, command

from ska_low_mccs_spshw import MccsDaqReceiver
from ska_low_mccs_spshw.daq_receiver.daq_simulator import (
    DaqModes,
    DaqSimulator,
    convert_daq_modes,
)
from tests.harness import SpsTangoTestHarness, SpsTangoTestHarnessContext

# TODO: [MCCS-1211] Workaround for ska-tango-testing bug.
gc.disable()


@pytest.fixture(name="device_under_test")
def device_under_test_fixture(
    test_context: SpsTangoTestHarnessContext,
) -> tango.DeviceProxy:
    """
    Fixture that returns the device under test.

    :param test_context: the context in which the tests are running.

    :return: the device under test
    """
    return test_context.get_daq_device()


class TestMccsDaqReceiver:
    """Test class for MccsDaqReceiver tests."""

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
        "modes_to_start, expected_consumers, daq_interface, daq_ports, daq_ip",
        [
            (
                "DaqModes.INTEGRATED_CHANNEL_DATA",
                [DaqModes.INTEGRATED_CHANNEL_DATA],
                "lo",
                [4567],
                "123.456.789.000",
            ),
            (
                "DaqModes.ANTENNA_BUFFER, DaqModes.RAW_DATA",
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
        modes_to_start: str,
        expected_consumers: list[DaqModes],
        daq_interface: str,
        daq_ports: list[int],
        daq_ip: str,
    ) -> None:
        """
        Test for DaqStatus.

        Here we configure DAQ with some non-default settings and then
            call DaqStatus to check that it reports the correct info.

        :param modes_to_start: A comma separated list of consumers/DaqModes to start.
        :param expected_consumers: A list of DaqModes
            representing the consumers to start.
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

        # TODO: mock skuid_client to fail fast.
        sleep(25)

        # Check status.
        status = json.loads(device_under_test.DaqStatus())
        # Check health is OK (as it must be to do this test)
        assert status["Daq Health"] == [HealthState.OK.name, HealthState.OK.value]
        # Check the consumers we specified to run are in this list.
        assert status["Running Consumers"] == [
            [consumer.name, consumer.value] for consumer in expected_consumers
        ]
        # Check it reports we're listening on the interface we chose.
        assert status["Receiver Interface"] == daq_interface
        # Check the IP is what we chose.
        assert status["Receiver IP"] == [daq_ip]

    @pytest.mark.parametrize(
        "daq_modes",
        ("DaqModes.CHANNEL_DATA, DaqModes.BEAM_DATA, DaqModes.RAW_DATA", "1, 2, 0"),
    )
    def test_start_stop_daq_device(
        self: TestMccsDaqReceiver,
        device_under_test: tango.DeviceProxy,
        daq_modes: str,
    ) -> None:
        """
        Test for Start().

        This tests that when we pass a valid string to the `Start`
        command that it is successfully parsed into the proper
        parameters so that `start_daq` can be called.

        :param device_under_test: fixture that provides a
            :py:class:`tango.DeviceProxy` to the device under test, in a
            :py:class:`tango.test_context.DeviceTestContext`.
        :param daq_modes: The DAQ consumers to start.
        """
        device_under_test.adminMode = AdminMode.ONLINE
        assert device_under_test.adminMode == AdminMode.ONLINE

        start_args = json.dumps({"modes_to_start": f"{daq_modes}"})
        [result_code], [response] = device_under_test.Start(start_args)
        assert result_code == ResultCode.QUEUED
        assert "Start" in response

        # --- TODO: Refactor this block into a test helper method that
        #  queries DaqStatus until some condition is satisfied.
        running_consumers = json.loads(device_under_test.DaqStatus()).get(
            "Running Consumers"
        )
        while running_consumers == []:
            sleep(0.2)
            running_consumers = json.loads(device_under_test.DaqStatus()).get(
                "Running Consumers"
            )
        # ---
        # Convert the expected DaqModes.
        expected_converted_daq_modes = convert_daq_modes(daq_modes)
        # Convert the running DaqModes after assembling into one string.
        running_daq_modes: str = ""
        for consumer in running_consumers:
            running_daq_modes += f"{consumer[0]},"
        running_daq_modes = running_daq_modes[0:-1]  # Strip trailing comma.
        actual_converted_daq_modes = convert_daq_modes(running_daq_modes)

        for consumer in expected_converted_daq_modes:
            # Match DaqMode.value
            assert consumer in actual_converted_daq_modes

        [result_code], [response] = device_under_test.Stop()
        assert result_code == ResultCode.OK
        assert response == "Daq stopped"


class TestPatchedDaq:
    """
    Test class for MccsDaqReceiver tests that patches the component manager.

    These are thin tests that simply test that commands invoked on the
    device are passed through to the component manager
    """

    @pytest.fixture(name="mock_component_manager")
    def mock_component_manager_fixture(
        self: TestPatchedDaq,
        mocker: pytest_mock.MockerFixture,
    ) -> unittest.mock.Mock:
        """
        Return a mock to be used as a component manager for the daq device.

        :param mocker: fixture that wraps the :py:mod:`unittest.mock`
            module

        :return: a mock to be used as a component manager for the daq
            device.
        """
        # mock_component_manager = mocker.Mock()
        mock_component_manager = unittest.mock.Mock()
        mock_component_manager.start_daq.return_value = (ResultCode.OK, "Daq started")
        mock_component_manager.stop_daq.return_value = (ResultCode.OK, "Daq stopped")
        mock_component_manager._set_consumers_to_start.return_value = (
            ResultCode.OK,
            "SetConsumers command completed OK",
        )
        mock_component_manager.start_bandpass_monitor.return_value = (
            ResultCode.OK,
            "Mock bandpass monitor started.",
        )
        mock_component_manager.stop_bandpass_monitor.return_value = (
            ResultCode.OK,
            "Mock bandpass monitor stopping.",
        )
        # configuration = {
        #     "start_daq.return_value": ,
        #     "stop_daq.return_value": ,
        #     "_set_consumers_to_start.return_value": ,
        # }
        # mock_component_manager.configure_mock(**configuration)
        return mock_component_manager

    @pytest.fixture(name="device_class_under_test")
    def device_class_under_test_fixture(
        self,
        mock_component_manager: unittest.mock.Mock,
    ) -> type[Device] | str:
        """
        Return the device class under test.

        :param mock_component_manager: a mock to be injected into the
            tango device under test, to take the place of its component
            manager.

        :returns: the device class under test
        """

        class _PatchedDaqReceiver(MccsDaqReceiver):
            """
            A daq class that has had its component manager mocked out for testing.

            Also creates a command to expose the received data callback
            """

            def create_component_manager(self) -> unittest.mock.Mock:
                """
                Return a mock component manager instead of the usual one.

                :return: a mock component manager
                """
                return mock_component_manager

            @command(dtype_in="DevVarStringArray")
            def CallReceivedDataCallback(
                self: _PatchedDaqReceiver, input_data: tuple[str, str, str]
            ) -> None:
                """
                Call to the received data callback.

                :param input_data: the input data to the callback in json form.
                """
                self._received_data_callback(*input_data)

        return _PatchedDaqReceiver

    @pytest.fixture(name="test_context")
    def test_context_fixture(
        self: TestPatchedDaq,
        device_class_under_test: Type[MccsDaqReceiver] | str,
        daq_id: int,
    ) -> Iterator[SpsTangoTestHarnessContext]:
        """
        Yield a tango harness against which to run tests of the deployment.

        :param device_class_under_test: class or name of the Tango
            device to be included in this test context.
        :param daq_id: the ID number of the DAQ receiver.

        :yields: a test harness context.
        """
        test_harness = SpsTangoTestHarness()
        test_harness.set_daq_instance(DaqSimulator())
        test_harness.set_daq_device(
            daq_id, address=None, device_class=device_class_under_test
        )  # dynamically get DAQ address
        with test_harness as test_context:
            yield test_context

    @pytest.mark.parametrize(
        "input_data, result",
        [
            (
                (
                    "burst_raw",
                    "file_name",
                    json.dumps(
                        {"channel_id": 1, "station_id": 2, "additional_info": 0}
                    ),
                ),
                {
                    "data_mode": "burst_raw",
                    "file_name": "file_name",
                    "tile": 0,
                    "metadata": {
                        "channel_id": 1,
                        "station_id": 2,
                        "additional_info": 0,
                    },
                },
            ),
            (
                (
                    "cont_channel",
                    "file_name",
                    json.dumps({"additional_info": 1}),
                ),
                {
                    "data_mode": "cont_channel",
                    "file_name": "file_name",
                    "tile": 1,
                    "metadata": {"additional_info": 1},
                },
            ),
            (
                (
                    "integrated_channel",
                    "file_name",
                    json.dumps({"additional_info": 2}),
                ),
                {
                    "data_mode": "integrated_channel",
                    "file_name": "file_name",
                    "tile": 2,
                    "metadata": {"additional_info": 2},
                },
            ),
            (
                (
                    "burst_channel",
                    "file_name",
                    json.dumps({"additional_info": 3}),
                ),
                {
                    "data_mode": "burst_channel",
                    "file_name": "file_name",
                    "tile": 3,
                    "metadata": {"additional_info": 3},
                },
            ),
            (
                (
                    "burst_beam",
                    "file_name",
                    json.dumps({"additional_info": 4}),
                ),
                {
                    "data_mode": "burst_beam",
                    "file_name": "file_name",
                    "tile": 4,
                    "metadata": {"additional_info": 4},
                },
            ),
            (
                (
                    "integrated_beam",
                    "file_name",
                    json.dumps({"additional_info": 5}),
                ),
                {
                    "data_mode": "integrated_beam",
                    "file_name": "file_name",
                    "tile": 5,
                    "metadata": {"additional_info": 5},
                },
            ),
            (
                (
                    "station",
                    "file_name",
                    json.dumps({"additional_info": 512}),
                ),
                {
                    "data_mode": "station",
                    "file_name": "file_name",
                    "amount_of_data": 512,
                    "metadata": {"additional_info": 512},
                },
            ),
            (
                (
                    "correlator",
                    "file_name",
                    json.dumps({}),
                ),
                {
                    "data_mode": "correlator",
                    "file_name": "file_name",
                    "metadata": {},
                },
            ),
            (
                (
                    "antenna_buffer",
                    "file_name",
                    json.dumps(
                        {
                            "additional_info": 8,
                            "dataset_root": None,
                            "n_antennas": 8,
                            "n_pols": 2,
                            "n_beams": 1,
                            "tile_id": 4,
                            "n_chans": 512,
                            "n_samples": 32,
                            "n_blocks": 1,
                            "written_samples": 32,
                            "timestamp": "1691063930",
                            "date_time": "2023-08-03 12:58:14.442114",
                            "data_type": "channel",
                            "n_baselines": 1,
                            "n_stokes": 1,
                            "channel_id": 2,
                            "station_id": 3,
                            "tsamp": 0,
                        }
                    ),
                ),
                {
                    "data_mode": "antenna_buffer",
                    "file_name": "file_name",
                    "tile": 8,
                    "metadata": {
                        "additional_info": 8,
                        "dataset_root": None,
                        "n_antennas": 8,
                        "n_pols": 2,
                        "n_beams": 1,
                        "tile_id": 4,
                        "n_chans": 512,
                        "n_samples": 32,
                        "n_blocks": 1,
                        "written_samples": 32,
                        "timestamp": "1691063930",
                        "date_time": "2023-08-03 12:58:14.442114",
                        "data_type": "channel",
                        "n_baselines": 1,
                        "n_stokes": 1,
                        "channel_id": 2,
                        "station_id": 3,
                        "tsamp": 0,
                    },
                },
            ),
        ],
    )
    def test_received_data_callback(
        self: TestPatchedDaq,
        device_under_test: tango.DeviceProxy,
        change_event_callbacks: MockTangoEventCallbackGroup,
        input_data: tuple[str, str, str],
        result: dict[str, Union[str, int]],
    ) -> None:
        """
        Test the received data callback.

        :param device_under_test: fixture that provides a
            :py:class:`tango.DeviceProxy` to the device under test, in a
            :py:class:`tango.test_context.DeviceTestContext`.
        :param change_event_callbacks: group of Tango change event
            callback with asynchrony support.
        :param input_data: the data to pass to the callback.
        :param result: the expected data that the change event is to be
            called with.
        """
        device_under_test.subscribe_event(
            "dataReceivedResult",
            tango.EventType.CHANGE_EVENT,
            change_event_callbacks["dataReceivedResult"],
        )
        change_event_callbacks.assert_change_event("dataReceivedResult", ("", ""))
        assert device_under_test.dataReceivedResult == ("", "")

        device_under_test.CallReceivedDataCallback(input_data)
        change_event_callbacks.assert_change_event(
            "dataReceivedResult", (input_data[0], Anything)
        )
        assert result == json.loads(device_under_test.dataReceivedResult[1])

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
            "DaqModes.INTEGRATED_BEAM_DATA,ANTENNA_BUFFER, BEAM_DATA,",
        ),
    )
    def test_set_consumers_device(
        self: TestPatchedDaq,
        device_under_test: tango.DeviceProxy,
        mock_component_manager: unittest.mock.Mock,
        consumer_list: str,
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

    def test_start_stop_bandpass_device(
        self: TestPatchedDaq,
        device_under_test: tango.DeviceProxy,
        mock_component_manager: unittest.mock.Mock,
    ) -> None:
        """
        Test for StartBandpassMonitor().

        This tests that when we pass a string to the `StartBandpassMonitor`
        command that it is successfully passed into the
        component manager

        :param device_under_test: fixture that provides a
            :py:class:`tango.DeviceProxy` to the device under test, in a
            :py:class:`tango.test_context.DeviceTestContext`.
        :param mock_component_manager: a mock component manager that has
            been patched into the device under test
        """
        device_under_test.adminMode = AdminMode.ONLINE
        assert device_under_test.adminMode == AdminMode.ONLINE

        # Call start_bandpass
        bandpass_config = '{"some_key": "some_value"}'
        _ = device_under_test.StartBandpassMonitor(bandpass_config)
        call_args = mock_component_manager.start_bandpass_monitor.call_args
        # A bit clunky but it gets padded with command IDs etc.
        assert call_args[0][0] == bandpass_config

        _ = device_under_test.StopBandpassMonitor()
        call_args = (
            mock_component_manager.stop_bandpass_monitor.assert_called_once_with()
        )
