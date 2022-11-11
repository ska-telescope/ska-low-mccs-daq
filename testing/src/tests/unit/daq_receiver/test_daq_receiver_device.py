# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq receiver device."""
from __future__ import annotations

import json
from typing import Union

import pytest
from pydaq.daq_receiver_interface import DaqModes  # type: ignore
from ska_control_model import HealthState, ResultCode
from ska_low_mccs_common import MccsDeviceProxy
from ska_low_mccs_common.testing.mock import MockChangeEventCallback
from ska_low_mccs_common.testing.tango_harness import DeviceToLoadType, TangoHarness

from ska_low_mccs_daq import MccsDaqReceiver
from ska_low_mccs_daq.daq_receiver.daq_component_manager import DaqComponentManager


@pytest.fixture()
def device_to_load() -> DeviceToLoadType:
    """
    Fixture that specifies the device to be loaded for testing.

    :return: specification of the device to be loaded
    """
    return {
        "path": "charts/ska-low-mccs-daq/data/configuration.json",
        "package": "ska_low_mccs_daq",
        "device": "daqreceiver_001",
        "proxy": MccsDeviceProxy,
    }


@pytest.fixture()
def device_under_test(tango_harness: TangoHarness) -> MccsDeviceProxy:
    """
    Fixture that returns the device under test.

    :param tango_harness: a test harness for Tango devices

    :return: the device under test
    """
    return tango_harness.get_device("low-mccs-daq/daqreceiver/001")


class TestMccsDaqReceiver:
    """Test class for MccsDaqReceiver tests."""

    def test_healthState(
        self: TestMccsDaqReceiver,
        device_under_test: MccsDeviceProxy,
        device_health_state_changed_callback: MockChangeEventCallback,
    ) -> None:
        """
        Test for healthState.

        :param device_under_test: fixture that provides a
            :py:class:`tango.DeviceProxy` to the device under test, in a
            :py:class:`tango.test_context.DeviceTestContext`.
        :param device_health_state_changed_callback: a callback that we
            can use to subscribe to health state changes on the device
        """
        device_under_test.add_change_event_callback(
            "healthState",
            device_health_state_changed_callback,
        )
        device_health_state_changed_callback.assert_next_change_event(
            HealthState.UNKNOWN
        )
        assert device_under_test.healthState == HealthState.UNKNOWN


class TestPatchedDaq:
    """
    Test class for MccsDaqReceiver tests that patches the component manager.

    These are thin tests that simply test that commands invoked on the
    device are passed through to the component manager
    """

    @pytest.fixture()
    def device_to_load(
        self: TestPatchedDaq, patched_daq_class: type[MccsDaqReceiver]
    ) -> DeviceToLoadType:
        """
        Fixture that specifies the device to be loaded for testing.

        :param patched_daq_class: a subclass of MccsDaqReceiver that has
            been patched for testing
        :return: specification of the device to be loaded
        """
        return {
            "path": "charts/ska-low-mccs-daq/data/configuration.json",
            "package": "ska_low_mccs_daq",
            "device": "daqreceiver_001",
            "proxy": MccsDeviceProxy,
            "patch": patched_daq_class,
        }

    @pytest.mark.parametrize(
        "daq_modes",
        ([DaqModes.CHANNEL_DATA, DaqModes.BEAM_DATA, DaqModes.RAW_DATA], [1, 2, 0]),
    )
    def test_start_daq_device(
        self: TestPatchedDaq,
        device_under_test: MccsDeviceProxy,
        mock_component_manager: DaqComponentManager,
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
        cbs = ["raw_data_cb", "beam_data_cb"]
        argin = {
            "modes_to_start": daq_modes,
            "callbacks": cbs,
        }
        [result_code], [response] = device_under_test.Start(json.dumps(argin))

        assert result_code == ResultCode.QUEUED
        assert "Start" in response.split("_")[-1]

        args = mock_component_manager.start_daq.get_next_call()  # type: ignore[attr-defined]
        called_daq_modes = args[0][0]
        called_cbs = args[0][1]

        assert called_daq_modes == daq_modes
        assert called_cbs == cbs

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
            "DaqModes.INTEGRATED_BEAM_DATA,ANTENNA_BUFFER, BEAM_DATA, DaqModes.INTEGRATED_CHANNEL_DATA",
        ),
    )
    def test_set_consumers_device(
        self: TestPatchedDaq,
        device_under_test: MccsDeviceProxy,
        mock_component_manager: DaqComponentManager,
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

        # Get the args for the next call to set consumers and assert it's what we expect.
        args = mock_component_manager._set_consumers_to_start.get_next_call()  # type: ignore[attr-defined]
        assert consumer_list == args[0][0]
