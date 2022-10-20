# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq component manager."""
from __future__ import annotations

import time

from pydaq.daq_receiver_interface import DaqModes, DaqReceiver  # type: ignore
from ska_control_model import CommunicationStatus, TaskStatus
from ska_low_mccs_common.testing.mock import MockCallable

from ska_low_mccs_daq.daq_receiver import DaqComponentManager


class TestDaqComponentManager:
    """Tests of the Daq Receiver component manager."""

    def test_communication(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        communication_state_changed_callback: MockCallable,
    ) -> None:
        """
        Test the station component manager's management of communication.

        :param daq_component_manager: the station component manager
            under test.
        :param communication_state_changed_callback: callback to be
            called when the status of the communications channel between
            the component manager and its component changes
        """
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED

        daq_component_manager.start_communicating()

        # allow some time for device communication to start before testing
        time.sleep(0.1)
        communication_state_changed_callback.assert_next_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        communication_state_changed_callback.assert_next_call(
            CommunicationStatus.ESTABLISHED
        )
        assert (
            daq_component_manager.communication_state == CommunicationStatus.ESTABLISHED
        )

        daq_component_manager.stop_communicating()
        communication_state_changed_callback.assert_next_call(
            CommunicationStatus.DISABLED
        )
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED

    def test_instantiate_daq(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        communication_state_changed_callback: MockCallable,
        acquisition_duration: int,
    ) -> None:
        """
        Test basic DAQ functionality.

        This test merely instantiates DAQ, starts a consumer,
            waits for a time and then stops the consumer.
            Data can also be logged if available.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param communication_state_changed_callback: callback to be
            called when the status of the communications channel between
            the component manager and its component changes
        :param acquisition_duration: The duration of the data capture.
        """
        # Check create_daq has given us a receiver.
        assert hasattr(daq_component_manager, "daq_instance")
        assert isinstance(daq_component_manager.daq_instance, DaqReceiver)
        # Override the default config.
        # The duration should be long enough to actually receive data.
        # This defaults to around 20-30 sec after delays are accounted for.
        modes_to_start = [DaqModes.INTEGRATED_CHANNEL_DATA]
        # data_received_callback isn't currently used as we don't yet have a
        # reliable way of making data available in a test context.
        # data_received_callback = MockCallable()

        daq_config = {
            "acquisition_duration": acquisition_duration,
            "directory": ".",
        }
        daq_component_manager.daq_instance.populate_configuration(daq_config)

        daq_component_manager.start_communicating()
        communication_state_changed_callback.assert_last_call(
            CommunicationStatus.ESTABLISHED
        )

        # Start DAQ and check our consumer is running.
        daq_task_callback = MockCallable()
        # station_component_manager.start_daq(modes_to_start, data_received_callback)
        rc, message = daq_component_manager.start_daq(
            modes_to_start, task_callback=daq_task_callback
        )
        assert rc == TaskStatus.QUEUED
        assert message == "Task queued"

        daq_task_callback.assert_next_call(status=TaskStatus.QUEUED)
        daq_task_callback.assert_next_call(status=TaskStatus.IN_PROGRESS)
        daq_task_callback.assert_next_call(status=TaskStatus.COMPLETED)

        for mode in modes_to_start:
            assert daq_component_manager.daq_instance._running_consumers[mode]

        # Wait for data etc
        time.sleep(daq_component_manager.daq_instance._config["acquisition_duration"])

        # Stop DAQ and check our consumer is not running.
        rc, message = daq_component_manager.stop_daq(task_callback=daq_task_callback)
        assert rc == TaskStatus.QUEUED
        assert message == "Task queued"

        daq_task_callback.assert_next_call(status=TaskStatus.QUEUED)
        daq_task_callback.assert_next_call(status=TaskStatus.IN_PROGRESS)
        daq_task_callback.assert_next_call(status=TaskStatus.COMPLETED)

        for mode in modes_to_start:
            assert not daq_component_manager.daq_instance._running_consumers[mode]

    # def test_validate_daq_config(self: TestDaqComponentManager,
    #     daq_component_manager: DaqComponentManager,) -> None:
    #     """
    #     This tests daq's configuration and validation.

    #     :param daq_component_manager: the daq receiver component manager
    #         under test.
    #     """
    #     time.sleep(2)
    #     new_daq_config = {"nof_antennas": 32,
    #                     "nof_channels": 256,
    #                     "nof_beams": 2,
    #                     "nof_tiles": 4,
    #                     "nof_raw_samples": 16384,
    #                     "nof_channel_samples": 1024,
    #                     "nof_beam_samples": 16,
    #                     "append_integrated": False,
    #                     "receiver_ports": "6244",
    #                     "receiver_interface": "eth0",
    #                     "receiver_ip": "",
    #                     "receiver_frame_size": 8500,
    #                     "receiver_frames_per_block": 32,
    #                     "receiver_nof_blocks": 256,
    #                     "directory": ".",
    #                     "acquisition_duration": -1,
    #                     "description": "",
    #                     }

    #     # This first call should return `False` as DAQ still has its default config.
    #     # The function should report that DAQ configuration was unsuccessfully applied
    #     assert not daq_component_manager._validate_daq_configuration(new_daq_config)

    #     # This second call should return `True` after reconfiguring the DaqReceiver.
    #     daq_component_manager.configure_daq(new_daq_config)
    #     assert daq_component_manager._validate_daq_configuration(new_daq_config)
