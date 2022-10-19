# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq receiver device."""
from __future__ import annotations

import pytest
from ska_control_model import HealthState
from ska_low_mccs import MccsDaqReceiver
from ska_low_mccs_common import MccsDeviceProxy
from ska_low_mccs_common.testing.mock import MockChangeEventCallback
from ska_low_mccs_common.testing.tango_harness import DeviceToLoadType, TangoHarness


@pytest.fixture()
def device_under_test(tango_harness: TangoHarness) -> MccsDeviceProxy:
    """
    Fixture that returns the device under test.

    :param tango_harness: a test harness for Tango devices

    :return: the device under test
    """
    return tango_harness.get_device("low-mccs/daqreceiver/001")


class TestMccsDaqReceiver:
    """Test class for MccsDaqReceiver tests."""

    @pytest.fixture()
    def device_to_load(self: TestMccsDaqReceiver) -> DeviceToLoadType:
        """
        Fixture that specifies the device to be loaded for testing.

        :return: specification of the device to be loaded
        """
        return {
            "path": "charts/ska-low-mccs/data/configuration.json",
            "package": "ska_low_mccs",
            "device": "daqreceiver_001",
            "proxy": MccsDeviceProxy,
        }

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
            "path": "charts/ska-low-mccs/data/configuration.json",
            "package": "ska_low_mccs",
            "device": "daqreceiver_001",
            "proxy": MccsDeviceProxy,
            "patch": patched_daq_class,
        }
