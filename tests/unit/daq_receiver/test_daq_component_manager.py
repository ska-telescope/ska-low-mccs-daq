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
import os
import shutil
import time
from pathlib import Path

import numpy as np
import pytest
from ska_control_model import CommunicationStatus, ResultCode, TaskStatus
from ska_tango_testing.mock import MockCallableGroup
from ska_tango_testing.mock.placeholders import Anything

from ska_low_mccs_daq.daq_receiver import DaqComponentManager
from ska_low_mccs_daq.daq_receiver.daq_simulator import convert_daq_modes
from ska_low_mccs_daq.pydaq.daq_receiver_interface import DaqModes

NOF_ANTENNAS_PER_TILE = 16


class TestDaqComponentManager:
    """Tests of the Daq Receiver component manager."""

    def test_communication(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
    ) -> None:
        """
        Test the daq component manager's management of communication.

        :param daq_component_manager: the daq component manager
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

    def test_admin_mode_behaviour(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
    ) -> None:
        """
        Test the daq component manager's management of communication.

        Here we test that we only connect to our DaqReceiver once
            start_communicating is called and that cycling adminMode
            (by calling stop_communicating then start_communicating)
            does not reinitialise the DaqReceiver.

        :param daq_component_manager: the daq component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        """
        # 1. Establish comms with DaqReceiver.
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED
        daq_component_manager.start_communicating()
        time.sleep(0.1)

        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)
        assert (
            daq_component_manager.communication_state == CommunicationStatus.ESTABLISHED
        )

        # 2. Configure DAQ to a non-standard config.
        non_standard_config = {
            "receiver_ports": "9876",
            "nof_tiles": 55,
            "nof_channels": 1234,
        }
        daq_component_manager.configure_daq(json.dumps(non_standard_config))

        # 3. Assert config was applied.
        daq_config_dict = daq_component_manager.get_configuration()
        assert daq_config_dict["receiver_ports"] == "[9876]"
        assert daq_config_dict["nof_tiles"] == 55
        assert daq_config_dict["nof_channels"] == 1234

        # 4. Imitate adminMode cycling by calling stop/start comms.
        daq_component_manager.stop_communicating()
        callbacks["communication_state"].assert_call(CommunicationStatus.DISABLED)
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED
        daq_component_manager.start_communicating()
        time.sleep(0.1)

        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)
        assert (
            daq_component_manager.communication_state == CommunicationStatus.ESTABLISHED
        )

        # 5. Assert that our previously set config remains valid.
        daq_config_dict = daq_component_manager.get_configuration()
        assert daq_config_dict["receiver_ports"] == "[9876]"
        assert daq_config_dict["nof_tiles"] == 55
        assert daq_config_dict["nof_channels"] == 1234

    # Not compiled with correlator currently.
    @pytest.mark.parametrize(
        ("daq_modes_str", "daq_modes_list"),
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
            (
                "DaqModes.CHANNEL_DATA, DaqModes.BEAM_DATA, DaqModes.RAW_DATA",
                [DaqModes.CHANNEL_DATA, DaqModes.BEAM_DATA, DaqModes.RAW_DATA],
            ),
            ("1, 2, 0", [DaqModes.CHANNEL_DATA, DaqModes.BEAM_DATA, DaqModes.RAW_DATA]),
            (
                "DaqModes.CONTINUOUS_CHANNEL_DATA, DaqModes.ANTENNA_BUFFER, 6",
                [
                    DaqModes.CONTINUOUS_CHANNEL_DATA,
                    DaqModes.ANTENNA_BUFFER,
                    DaqModes.STATION_BEAM_DATA,
                ],
            ),
            (
                "5, 4, DaqModes.STATION_BEAM_DATA",
                [
                    DaqModes.INTEGRATED_CHANNEL_DATA,
                    DaqModes.INTEGRATED_BEAM_DATA,
                    DaqModes.STATION_BEAM_DATA,
                ],
            ),
            (
                "RAW_DATA, 3, DaqModes.STATION_BEAM_DATA, ANTENNA_BUFFER",
                [
                    DaqModes.RAW_DATA,
                    DaqModes.CONTINUOUS_CHANNEL_DATA,
                    DaqModes.STATION_BEAM_DATA,
                    DaqModes.ANTENNA_BUFFER,
                ],
            ),
            ("", []),
        ),
    )
    def test_convert_daq_modes(
        self: TestDaqComponentManager,
        daq_modes_str: str,
        daq_modes_list: list[DaqModes],
    ) -> None:
        """
        Test DaqModes can be properly converted.

        This tests that DaqModes can be converted properly from a comma separated list
            of ints and/or DaqModes to a list of DaqModes.

        :param daq_modes_str: A comma separated list of DaqModes and/or ints.
        :param daq_modes_list: The expected output of the conversion function.
        """
        assert convert_daq_modes(daq_modes_str) == daq_modes_list

    @pytest.mark.parametrize(
        "daq_modes",
        (
            "RAW_DATA",
            "DaqModes.CHANNEL_DATA",
            "DaqModes.BEAM_DATA",
            "DaqModes.CONTINUOUS_CHANNEL_DATA",
            "DaqModes.INTEGRATED_BEAM_DATA",
            "DaqModes.INTEGRATED_CHANNEL_DATA",
            "DaqModes.STATION_BEAM_DATA",
            "DaqModes.CORRELATOR_DATA",
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
        daq_modes: str,
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
        :param daq_modes: The DAQ consumers to start.
        """
        acquisition_duration = 2

        daq_component_manager.start_communicating()
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)

        daq_config = {
            "acquisition_duration": acquisition_duration,
            "directory": ".",
        }
        daq_component_manager.configure_daq(json.dumps(daq_config))

        # Start DAQ and check our consumer is running.
        # Need exactly 1 callback per consumer started or None. Cast for Mypy.
        ts, message = daq_component_manager.start_daq(
            daq_modes,
            task_callback=callbacks["task_start_daq"],
        )
        assert ts == TaskStatus.QUEUED
        assert message == "Task queued"

        # TODO: May be more to tweak here.
        callbacks["task_start_daq"].assert_call(status=TaskStatus.QUEUED)
        callbacks["task_start_daq"].assert_call(
            status=TaskStatus.IN_PROGRESS,
        )
        callbacks["task_start_daq"].assert_call(
            status=TaskStatus.COMPLETED,
            result=(ResultCode.OK, "Daq started"),
        )

        converted_daq_modes: list[DaqModes] = convert_daq_modes(daq_modes)
        # for mode in daq_modes:
        # If we're using ints instead of DaqModes make the conversion so we
        # can check the consumer.
        # mode_to_check = DaqModes(mode)
        # status will not have health info when cpt mgr method is directly called.
        status = daq_component_manager.get_status()

        running_consumers = status["Running Consumers"]

        for i, mode_to_check in enumerate(converted_daq_modes):
            assert mode_to_check.value in running_consumers[i]

        # Wait for data etc
        time.sleep(acquisition_duration)

        # Stop DAQ and check our consumer is not running.
        daq_component_manager.stop_daq(task_callback=callbacks["task"])

        callbacks["task"].assert_call(status=TaskStatus.QUEUED)
        callbacks["task"].assert_call(status=TaskStatus.IN_PROGRESS)
        callbacks["task"].assert_call(status=TaskStatus.COMPLETED)
        # Once we issue the stop command on the DAQ this will stop the thread
        # with the streamed response. We need to wait for the start_daq thread
        # to complete.

        # for mode in daq_modes:
        # If we're using ints instead of DaqModes make the conversion so we
        # can check the consumer.
        # mode_to_check = DaqModes(mode)
        # TODO: Cannot check status of consumers until DaqStatus cmd is updated.
        # assert not daq_component_manager.daq_instance._running_consumers[
        #     mode_to_check
        # ]

    @pytest.mark.parametrize(
        "consumer_list",
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
            "",  # Default behaviour.
            "DaqModes.INTEGRATED_BEAM_DATA,ANTENNA_BUFFER, BEAM_DATA",
            "DaqModes.INTEGRATED_CHANNEL_DATA",
        ),
    )
    def test_set_get_consumer_list(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        consumer_list: str,
    ) -> None:
        """
        Test `_consumers_to_start` can be set and fetched correctly.

        Test that when we set consumers via the `_set_consumers_to_start` method that
        the `_consumers_to_start` attribute is set to the proper value.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param consumer_list: A comma separated list of consumers to start.
        """
        assert daq_component_manager._consumers_to_start == ""
        daq_component_manager._set_consumers_to_start(consumer_list)
        assert daq_component_manager._consumers_to_start == consumer_list

    def test_start_stop_bandpass_monitor(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
        nof_tiles: int,
    ) -> None:
        """
        Test for start_bandpass_monitor().

        This tests that all of the configuration errors are properly
        handled and that the happy path also works.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        :param nof_tiles: number of tiles the DAQ was configure with.
        """
        daq_component_manager.start_communicating()
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)
        daq_component_manager.start_daq(
            "INTEGRATED_CHANNEL_DATA",
            task_callback=callbacks["task"],
        )
        callbacks["task"].assert_call(status=TaskStatus.QUEUED)
        callbacks["task"].assert_call(status=TaskStatus.IN_PROGRESS)
        callbacks["task"].assert_call(
            status=TaskStatus.COMPLETED,
            result=(ResultCode.OK, "Daq started"),
        )

        # Call start_bandpass
        _ = daq_component_manager.start_bandpass_monitor(
            "", task_callback=callbacks["task"]
        )

        callbacks["task"].assert_call(status=TaskStatus.QUEUED)
        callbacks["task"].assert_call(
            status=TaskStatus.COMPLETED,
            result=(ResultCode.OK, "Bandpass monitor active"),
            lookahead=5,
        )

        src_dir = Path(__file__).parent.parent.parent / "data" / "integrated-data"
        dst_dir = src_dir.parent / "bandpass-data"
        dst_dir.mkdir(exist_ok=True)

        # Assert status shows bandpass monitor is active.
        status = daq_component_manager.get_status()
        assert status["Bandpass Monitor"]

        expected_data = np.zeros((256, 512))
        for i in range(nof_tiles * NOF_ANTENNAS_PER_TILE):
            expected_data[i][0] = 3.01  # DC signal
            expected_data[i][128] = 36  # Test generator on at 100Mhz
            expected_data[i][256] = 36  # Test generator on at 200Mhz

        for _ in range(3):
            # Pretend to receive bandpass data.
            for file in src_dir.glob("*.hdf5"):
                shutil.copy(file, dst_dir / file.name)

            assert len(os.listdir(dst_dir)) == nof_tiles
            for file in dst_dir.glob("*.hdf5"):
                daq_component_manager._file_dump_callback(
                    "integrated_channel", str(file)
                )

            for _ in range(8):
                callbacks["received_data"].assert_call(
                    Anything, "integrated_channel", Anything
                )

            call_args = callbacks["component_state"]._call_queue.get(timeout=5)
            args_dict = call_args[2]
            received_x_pol_data = args_dict["x_bandpass_plot"]
            received_y_pol_data = args_dict["y_bandpass_plot"]

            np.testing.assert_allclose(received_x_pol_data, expected_data, rtol=1e-1)
            np.testing.assert_allclose(received_y_pol_data, expected_data, rtol=1e-1)
            assert len(os.listdir(dst_dir)) == 0

        assert (
            ResultCode.OK,
            "Bandpass monitor stopping.",
        ) == daq_component_manager.stop_bandpass_monitor()
        status = daq_component_manager.get_status()
        assert not status["Bandpass Monitor"]

    @pytest.mark.parametrize(
        ("directory", "outcome"),
        (
            (".", False),
            ("/plot", False),
            ("product/blah", False),
            ("/product/blah", False),
            ("/product/eb_id/ska-low-mccs/scan_id/", True),
            ("product/eb_id/ska-low-mccs/scan_id/", False),
            ("/product/eb_id/some-other-team/scan_id/", False),
            (
                "/product/ska-low-mccs/some-other-team/scan_id/",
                False,
            ),  # Deliberately malformed
        ),
    )
    def test_check_directory_format(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
        directory: str,
        outcome: bool,
    ) -> None:
        """
        Test that we can tell a "good" filepath from a "bad" one.

        Test also that we can properly reconfigure so that the path
            is in the proper format. This is done by appending the
            current directory onto the end of the required structure.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        :param directory: The filepath to check.
        :param outcome: The expected response from
            `_data_directory_format_adr55_compliant`
        """
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED
        daq_component_manager.start_communicating()
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)

        config = {"directory": directory}
        daq_component_manager.configure_daq(json.dumps(config))

        assert outcome == daq_component_manager._data_directory_format_adr55_compliant()

        # If we're off the happy path then reconfigure.
        if not outcome:
            re_config = {"directory": daq_component_manager._construct_adr55_filepath()}
            daq_component_manager.configure_daq(json.dumps(re_config))
            time.sleep(1)
            assert daq_component_manager._data_directory_format_adr55_compliant()

    @pytest.mark.parametrize(
        ("scan_id", "eb_id"),
        (
            (None, None),
            ("scan_uid", None),
            (None, "eb_uid"),
            ("scan_uid", "eb_uid"),
        ),
    )
    def test_adr55_filepath(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
        scan_id: str,
        eb_id: str,
    ) -> None:
        """
        Test that a compliant filepath is produced as expected.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        :param scan_id: A mock scan_id to use.
        :param eb_id: A mock eb_id to use.
        """
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED
        daq_component_manager.start_communicating()
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)

        existing_directory = "some/file/path"
        daq_component_manager.configure_daq(
            json.dumps({"directory": existing_directory})
        )
        assert (
            daq_component_manager.get_configuration()["directory"] == existing_directory
        )

        adr55_filepath = daq_component_manager._construct_adr55_filepath(
            eb_id=eb_id, scan_id=scan_id
        )
        adr55_filepath_parts = adr55_filepath.split("/", maxsplit=5)
        if eb_id is not None:
            assert adr55_filepath_parts[2] == eb_id
        else:
            assert adr55_filepath_parts[2] is not None

        if scan_id is not None:
            assert adr55_filepath_parts[4] == scan_id
        else:
            assert adr55_filepath_parts[4] is not None

        assert adr55_filepath_parts[5] == existing_directory

    def test_get_eb_skuid(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
    ) -> None:
        """
        Test that we can retrieve an execution block ID from SKUID.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        """
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED
        daq_component_manager.start_communicating()
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)
        unique_ids = set()
        unique_id_count = 10

        for _ in range(unique_id_count):
            unique_ids.add(daq_component_manager._get_eb_id())

        assert len(unique_ids) == unique_id_count

    def test_get_scan_skuid(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
    ) -> None:
        """
        Test that we can retrieve a scan ID from SKUID.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        """
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED
        daq_component_manager.start_communicating()
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)
        unique_ids = set()
        unique_id_count = 10

        for _ in range(unique_id_count):
            unique_ids.add(daq_component_manager._get_scan_id())

        assert len(unique_ids) == unique_id_count

    def test_stop_data_rate_monitor(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
    ) -> None:
        """
        Test that we can stop the data rate monitor on the DAQ server.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        """
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED
        daq_component_manager.start_communicating()
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)
        assert daq_component_manager.stop_data_rate_monitor() == (
            ResultCode.OK,
            "Data rate measurement stopping.",
        )

    def test_attribute_callback(
        self: TestDaqComponentManager,
        daq_component_manager: DaqComponentManager,
        callbacks: MockCallableGroup,
    ) -> None:
        """
        Test the attribute callback.

        :param daq_component_manager: the daq receiver component manager
            under test.
        :param callbacks: a dictionary from which callbacks with
            asynchrony support can be accessed.
        """
        assert daq_component_manager.communication_state == CommunicationStatus.DISABLED
        daq_component_manager.start_communicating()
        callbacks["communication_state"].assert_call(
            CommunicationStatus.NOT_ESTABLISHED
        )
        callbacks["communication_state"].assert_call(CommunicationStatus.ESTABLISHED)
        daq_component_manager._start_daq(
            "STATION_BEAM_DATA", task_callback=callbacks["task"]
        )
        daq_component_manager._file_dump_callback(
            "station", "some/existing/file", nof_packets=49152, nof_saturations=53
        )
        callbacks["component_state"].assert_call(nof_packets=49152)
        callbacks["component_state"].assert_call(nof_saturations=53)
