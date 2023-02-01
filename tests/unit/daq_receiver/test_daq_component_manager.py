# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq component manager."""
from __future__ import annotations

import json
import time
from typing import Union

import pytest
from pydaq.daq_receiver_interface import DaqModes
from ska_control_model import CommunicationStatus, ResultCode, TaskStatus
from ska_tango_testing.mock import MockCallableGroup

from ska_low_mccs_daq.daq_receiver import DaqComponentManager
from ska_low_mccs_daq.gRPC_server.daq_grpc_server import convert_daq_modes_str


class TestDaqComponentManager:
    """Tests of the Daq Receiver component manager."""

    def test_communication(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
    ) -> None:
        """
        Test the station component manager's management of communication.

        :param daq_component_manager: the station component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        """
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED

        daq_component_manager.start_communicating()

        # allow some time for device communication to start before testing
        time.sleep(0.1)
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)
        assert (
            daq_component_manager.communication_state == CommunicationStatus.ESTABLISHED
        )

        daq_component_manager.stop_communicating()
        callbacks["communication_state"].assert_call(CommunicationStatus.DISABLED)
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED

    @pytest.mark.parametrize(
        "daq_modes",
        (
            "DaqModes.RAW_DATA",
            "DaqModes.CHANNEL_DATA",
            "DaqModes.BEAM_DATA",
            "DaqModes.CONTINUOUS_CHANNEL_DATA",
            "DaqModes.INTEGRATED_BEAM_DATA",
            "DaqModes.INTEGRATED_CHANNEL_DATA",
            "DaqModes.STATION_BEAM_DATA",
            # "DaqModes.CORRELATOR_DATA",  # Not compiled with correlator currently.
            "DaqModes.ANTENNA_BUFFER",
            "DaqModes.CHANNEL_DATA, DaqModes.BEAM_DATA, DaqModes.RAW_DATA",
            "1, 2, 0",
            "DaqModes.CONTINUOUS_CHANNEL_DATA, DaqModes.ANTENNA_BUFFER, 6",
            "5, 4, DaqModes.STATION_BEAM_DATA",
        ),
    )
    def test_instantiate_daq(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
        acquisition_duration: int,
        daq_modes: list[Union[int, DaqModes]],
    ) -> None:
        """
        Test basic DAQ functionality.

        This test merely instantiates DAQ, starts a consumer,
            waits for a time and then stops the consumer.
            This also doubles as a check that we can start and stop every consumer.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        :param acquisition_duration: The duration of the data capture.
        :param daq_modes: The DAQ consumers to start.
        """
        daq_config = {
            "acquisition_duration": acquisition_duration,
            "directory": ".",
        }
        daq_component_manager.configure_daq(json.dumps(daq_config))

        daq_component_manager.start_communicating()
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)

        # Start DAQ and check our consumer is running.
        # Need exactly 1 callback per consumer started or None. Cast for Mypy.
        rc, message = daq_component_manager.start_daq(
            daq_modes,
            task_callback=callbacks["task"],
        )
        assert rc == ResultCode.OK.value
        assert message == "Daq started"

        # callbacks["task"].assert_call(status=TaskStatus.QUEUED)
        callbacks["task"].assert_call(status=TaskStatus.IN_PROGRESS)
        callbacks["task"].assert_call(status=TaskStatus.COMPLETED)

        daq_modes = convert_daq_modes_str(daq_modes)
        # for mode in daq_modes:
        # If we're using ints instead of DaqModes make the conversion so we
        # can check the consumer.
        # mode_to_check = DaqModes(mode)
        # TODO: Cannot check status of consumers until DaqStatus cmd is updated.
        # assert daq_component_manager.daq_instance.
        # _running_consumers[mode_to_check]

        # Wait for data etc
        time.sleep(acquisition_duration)

        # Stop DAQ and check our consumer is not running.
        rc, message = daq_component_manager.stop_daq(task_callback=callbacks["task"])
        assert rc == ResultCode.OK.value
        assert message == "Daq stopped"

        # callbacks["task"].assert_call(status=TaskStatus.QUEUED)
        callbacks["task"].assert_call(status=TaskStatus.IN_PROGRESS)
        callbacks["task"].assert_call(status=TaskStatus.COMPLETED)

        # for mode in daq_modes:
        # If we're using ints instead of DaqModes make the conversion so we
        # can check the consumer.
        # mode_to_check = DaqModes(mode)
        # TODO: Cannot check status of consumers until DaqStatus cmd is updated.
        # assert not daq_component_manager.daq_instance._running_consumers[
        #     mode_to_check
        # ]

    @pytest.mark.parametrize(
        ("consumer_list", "daq_modes"),
        (
            ("DaqModes.RAW_DATA", [DaqModes.RAW_DATA]),
            ("DaqModes.CHANNEL_DATA", [DaqModes.CHANNEL_DATA]),
            ("DaqModes.BEAM_DATA", [DaqModes.BEAM_DATA]),
            ("DaqModes.CONTINUOUS_CHANNEL_DATA", [DaqModes.CONTINUOUS_CHANNEL_DATA]),
            ("DaqModes.INTEGRATED_BEAM_DATA", [DaqModes.INTEGRATED_BEAM_DATA]),
            ("DaqModes.INTEGRATED_CHANNEL_DATA", [DaqModes.INTEGRATED_CHANNEL_DATA]),
            ("DaqModes.STATION_BEAM_DATA", [DaqModes.STATION_BEAM_DATA]),
            ("DaqModes.CORRELATOR_DATA", [DaqModes.CORRELATOR_DATA]),
            ("DaqModes.ANTENNA_BUFFER", [DaqModes.ANTENNA_BUFFER]),
            ("", [DaqModes.INTEGRATED_CHANNEL_DATA]),  # Default behaviour.
            (
                (
                    "DaqModes.INTEGRATED_BEAM_DATA,ANTENNA_BUFFER, BEAM_DATA,"
                    " DaqModes.INTEGRATED_CHANNEL_DATA"
                ),
                [
                    DaqModes.INTEGRATED_BEAM_DATA,
                    DaqModes.ANTENNA_BUFFER,
                    DaqModes.BEAM_DATA,
                    DaqModes.INTEGRATED_CHANNEL_DATA,
                ],
            ),
        ),
    )
    def test_set_get_consumer_list(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        consumer_list: str,
        daq_modes: list[DaqModes],
    ) -> None:
        """
        Test `_consumers_to_start` can be set and fetched correctly.

        Test that when we set consumers via the `_set_consumers_to_start` method that
        the `_consumers_to_start` attribute is set to the proper value.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param consumer_list: A comma separated list of consumers to start.
        :param daq_modes: The corresponding DaqModes we expect to be set by
            the string passed in.
        """
        assert daq_component_manager._consumers_to_start is None
        daq_component_manager._set_consumers_to_start(consumer_list)
        assert daq_component_manager._get_consumers_to_start() == daq_modes

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
