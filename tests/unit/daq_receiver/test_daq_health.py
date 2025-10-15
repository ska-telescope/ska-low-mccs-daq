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
from typing import Iterator

import pytest
import tango
from ska_control_model import HealthState
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup
from tango.server import command

from ska_low_mccs_daq import MccsDaqReceiver
from tests.harness import SpsTangoTestHarness, SpsTangoTestHarnessContext
from tests.test_tools import execute_lrc_to_completion


class TestDaqHealth:
    """Test the health of the daq receiver device."""

    @pytest.fixture(name="change_event_callbacks")
    def change_event_callbacks_fixture(self) -> MockTangoEventCallbackGroup:
        """
        Return a dictionary of change event callbacks with asynchrony support.

        :return: a collections.defaultdict that returns change event
            callbacks by name.
        """
        return MockTangoEventCallbackGroup(
            "healthState",
            "track_lrc_command",
        )

    @pytest.fixture(name="test_context")
    def test_context_fixture(self) -> Iterator[SpsTangoTestHarnessContext]:
        """
        Return the device class under test.

        :yields: a test harness context.
        """

        class _PatchedDaqReceiver(MccsDaqReceiver):
            """A daq class with a method to call the component state callback."""

            @command
            def CallComponentCallback(self, argin: str) -> None:
                """
                Patched method to call component callback directly.

                :param argin: json-ified dict to call component callback with.
                """
                self._component_state_callback(**json.loads(argin))

        test_harness = SpsTangoTestHarness()
        test_harness.set_lmc_daq_device(
            1, address=None, device_class=_PatchedDaqReceiver
        )

        with test_harness as test_harness_context:
            yield test_harness_context

    def test_health_state(
        self,
        test_context: SpsTangoTestHarnessContext,
        change_event_callbacks: MockTangoEventCallbackGroup,
    ) -> None:
        """
        Test that the health state of the daq receiver device is as expected.

        :param test_context: The test context fixture.
        :param change_event_callbacks: The change event callbacks fixture.
        """
        daq_device = test_context.get_daq_device()
        daq_device.subscribe_event(
            "healthState",
            tango.EventType.CHANGE_EVENT,
            change_event_callbacks["healthState"],
        )
        change_event_callbacks["healthState"].assert_change_event(HealthState.UNKNOWN)
        assert daq_device.state() == tango.DevState.DISABLE

        daq_device.adminmode = 0
        change_event_callbacks["healthState"].assert_change_event(
            HealthState.OK, lookahead=2
        )
        assert daq_device.state() == tango.DevState.ON

        daq_device.CallComponentCallback(json.dumps({"ringbuffer_occupancy": 50}))
        change_event_callbacks["healthState"].assert_change_event(HealthState.DEGRADED)
        assert daq_device.state() == tango.DevState.ALARM

        daq_device.CallComponentCallback(json.dumps({"ringbuffer_occupancy": 100}))
        change_event_callbacks["healthState"].assert_change_event(
            HealthState.FAILED, lookahead=2
        )
        assert daq_device.state() == tango.DevState.ALARM

        daq_device.CallComponentCallback(json.dumps({"ringbuffer_occupancy": 0}))
        change_event_callbacks["healthState"].assert_change_event(HealthState.OK)
        assert daq_device.state() == tango.DevState.ON

    def test_attribute_config(
        self,
        test_context: SpsTangoTestHarnessContext,
        change_event_callbacks: MockTangoEventCallbackGroup,
    ) -> None:
        """
        Test that when alarm thresholds are changed, health state updates.

        :param test_context: The test context fixture.
        :param change_event_callbacks: The change event callbacks fixture.
        """
        daq_device = test_context.get_daq_device()
        daq_device.subscribe_event(
            "healthState",
            tango.EventType.CHANGE_EVENT,
            change_event_callbacks["healthState"],
        )
        change_event_callbacks["healthState"].assert_change_event(HealthState.UNKNOWN)
        change_event_callbacks["healthState"].assert_not_called()
        assert daq_device.state() == tango.DevState.DISABLE

        daq_device.adminmode = 0
        change_event_callbacks["healthState"].assert_change_event(
            HealthState.OK, lookahead=2, consume_nonmatches=True
        )
        change_event_callbacks["healthState"].assert_not_called()
        assert daq_device.state() == tango.DevState.ON

        try:
            attribute = daq_device.get_attribute_config("ringbufferoccupancy")
            alarm_config = attribute.alarms
            alarm_config.max_warning = "10.0"
            alarm_config.max_alarm = "20.0"
            attribute.alarms = alarm_config
            daq_device.set_attribute_config(attribute)
        except tango.DevFailed:
            pytest.xfail("Ran into PyTango monitor lock issue, to be fixed in 10.1.0")

        daq_device.CallComponentCallback(json.dumps({"ringbuffer_occupancy": 15}))
        change_event_callbacks["healthState"].assert_change_event(
            HealthState.DEGRADED, lookahead=2, consume_nonmatches=True
        )
        assert daq_device.state() == tango.DevState.ALARM

        daq_device.CallComponentCallback(json.dumps({"ringbuffer_occupancy": 25}))
        change_event_callbacks["healthState"].assert_change_event(
            HealthState.FAILED, lookahead=2, consume_nonmatches=True
        )
        assert daq_device.state() == tango.DevState.ALARM
        try:
            attribute = daq_device.get_attribute_config("ringbufferoccupancy")
            alarm_config = attribute.alarms
            alarm_config.max_warning = "75.0"
            alarm_config.max_alarm = "100.0"
            attribute.alarms = alarm_config
            daq_device.set_attribute_config(attribute)
        except tango.DevFailed:
            pytest.xfail("Ran into PyTango monitor lock issue, to be fixed in 10.1.0")

        change_event_callbacks["healthState"].assert_change_event(HealthState.OK)
        assert daq_device.state() == tango.DevState.ON

    @pytest.mark.parametrize(
        ["consumer", "attribute", "expected_value", "expected_health"],
        [
            (
                "STATION_BEAM_DATA",
                "nof_packets",
                int(384 * 262144 / 2048 * 0.5),
                HealthState.FAILED,
            ),
            (
                "STATION_BEAM_DATA",
                "nof_packets",
                int(384 * 262144 / 2048 * 0.95),
                HealthState.DEGRADED,
            ),
            (
                "INTEGRATED_CHANNEL_DATA",
                "nof_packets",
                int(2 * 512 / 32 * 16 / 8 * 0.5),
                HealthState.FAILED,
            ),
            (
                "INTEGRATED_CHANNEL_DATA",
                "nof_packets",
                int(2 * 512 / 32 * 16 / 8 * 0.95),
                HealthState.DEGRADED,
            ),
            (
                "CORRELATOR_DATA",
                "nof_packets",
                int(1835008 / 256 * 16 / 8 * 0.5),
                HealthState.FAILED,
            ),
            (
                "CORRELATOR_DATA",
                "nof_packets",
                int(1835008 / 256 * 16 / 8 * 0.95),
                HealthState.DEGRADED,
            ),
            (
                "CORRELATOR_DATA",
                "correlator_time_taken",
                1000 * 1835008 / 925925.925 * 2,
                HealthState.FAILED,
            ),
            (
                "CORRELATOR_DATA",
                "correlator_time_taken",
                1000 * 1835008 / 925925.925 * 0.8,
                HealthState.DEGRADED,
            ),
            (
                "CORRELATOR_DATA",
                "nof_samples",
                int(1835008 * 0.5),
                HealthState.FAILED,
            ),
            (
                "CORRELATOR_DATA",
                "nof_samples",
                int(1835008 * 0.95),
                HealthState.DEGRADED,
            ),
        ],
    )
    # pylint: disable=too-many-arguments
    def test_rel_attrs(
        self,
        test_context: SpsTangoTestHarnessContext,
        change_event_callbacks: MockTangoEventCallbackGroup,
        consumer: str,
        attribute: str,
        expected_value: float,
        expected_health: HealthState,
    ) -> None:
        """
        Test that when alarm thresholds are changed, health state updates.

        :param test_context: The test context fixture.
        :param change_event_callbacks: The change event callbacks fixture.
        :param consumer: The consumer to start up.
        :param attribute: The attribute to check.
        :param expected_value: The expected value of the attribute.
        :param expected_health: The expected health state.
        """
        daq_device = test_context.get_daq_device()
        daq_device.subscribe_event(
            "healthState",
            tango.EventType.CHANGE_EVENT,
            change_event_callbacks["healthState"],
        )
        change_event_callbacks["healthState"].assert_change_event(HealthState.UNKNOWN)
        change_event_callbacks["healthState"].assert_not_called()
        assert daq_device.state() == tango.DevState.DISABLE

        daq_device.adminmode = 0
        change_event_callbacks["healthState"].assert_change_event(
            HealthState.OK, lookahead=2, consume_nonmatches=True
        )
        change_event_callbacks["healthState"].assert_not_called()
        assert daq_device.state() == tango.DevState.ON

        execute_lrc_to_completion(
            change_event_callbacks,
            daq_device,
            "Start",
            json.dumps({"modes_to_start": consumer}),
        )
        daq_device.CallComponentCallback(json.dumps({attribute: expected_value}))

        change_event_callbacks["healthState"].assert_change_event(expected_health)
