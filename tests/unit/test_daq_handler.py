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
import time
from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest
from pydaq.daq_receiver_interface import DaqModes
from ska_control_model import ResultCode, TaskStatus
from ska_low_mccs_daq_interface.client import DaqClient

from ska_low_mccs_daq.daq_handler import DaqHandler


class TestDaqHandler:
    """Test class for DaqHandler tests."""

    @pytest.fixture(name="file_metadata")
    def file_metadata_fixture(self: TestDaqHandler) -> dict:
        """
        Fixture to get the file metadata.

        :return: file metadata.
        """
        return {
            "dataset_root": None,
            "n_antennas": np.uint(8),
            "n_pols": np.uint(2),
            "n_beams": np.uint(1),
            "tile_id": np.uint(4),
            "n_chans": np.uint(512),
            "n_samples": np.uint(32),
            "n_blocks": np.uint(1),
            "written_samples": np.uint(32),
            "timestamp": 1691063930.0,
            "date_time": "2023-08-03 12:58:14.442114",
            "data_type": "channel",
            "n_baselines": np.uint(1),
            "n_stokes": np.uint(1),
            "channel_id": np.uint(2),
            "station_id": np.uint(3),
            "tsamp": 0,
        }

    @pytest.fixture(name="mock_daq_receiver")
    def mock_daq_receiver_fixture(self: TestDaqHandler, file_metadata: dict) -> Mock:
        """
        Fixture to get a mock DaqReceiver.

        This is useful to be able to mock the existence of files.

        :param file_metadata: sample file metadata for testing.

        :return: a mock DaqReceiver.
        """

        def get_metadata(*args: Any, **kwargs: Any) -> dict:
            return file_metadata

        persister_mock = Mock()
        persister_mock.get_metadata.side_effect = get_metadata
        persisters = {DaqModes.INTEGRATED_CHANNEL_DATA: persister_mock}
        daqrx = Mock()
        daqrx._persisters = persisters
        return daqrx

    @pytest.fixture(name="daq_handler")
    def daq_handler_fixture(
        self: TestDaqHandler, mock_daq_receiver: Mock
    ) -> DaqHandler:
        """
        Fixture to get a DaqHandler instance.

        :param mock_daq_receiver: a mock DaqReceiver.

        :return: a DaqHandler.
        """
        daq_handler = DaqHandler()
        daq_handler.daq_instance = mock_daq_receiver
        return daq_handler

    @pytest.mark.parametrize(
        ("args", "expected_status", "expected_msg"),
        (
            (
                "",
                TaskStatus.COMPLETED,
                "Daq has been started and is listening",
            ),  # noqa: E501
            pytest.param(
                "invalidInput",
                TaskStatus.FAILED,
                "Invalid DaqMode supplied",
                marks=pytest.mark.xfail(
                    reason="Error propagation is not implemented."
                ),  # noqa: E501
            ),
        ),
    )
    def test_daq_server_start_stop_daq(
        self: TestDaqHandler,
        daq_address: str,
        args: str,
        expected_status: ResultCode,
        expected_msg: str,
    ) -> None:
        """
        Test for DAQ server start and stop.

        :param daq_address: The address of the DAQ server.
        :param args: The argument with which to call `StartDaq`.
        :param expected_status: The expected task status expected
            from `StartDaq`.
        :param expected_msg: The message expected from `StartDaq`.
        """
        daq_client = DaqClient(daq_address)
        assert daq_client.initialise("{}") == {
            "message": "Daq successfully initialised"
        }

        responses = daq_client.start_daq(args)

        assert next(responses) == {
            "status": TaskStatus.IN_PROGRESS,
            "message": "Start Command issued to gRPC stub",
        }
        assert next(responses) == {
            "status": expected_status,
            "message": expected_msg,
        }

        # If we were actually sending data for the DAQ to acquire,
        # then here we could do something like
        #
        # assert next(responses) == {"types": "foo", "files": "foo.hdf5"}
        # assert next(responses) == {"types": "bah", "files": "bah.hdf5"}
        # with pytest.raises(StopIteration):
        #     _ = next(responses)

        assert daq_client.stop_daq() == (ResultCode.OK, "Daq stopped")

    @pytest.mark.parametrize(
        ("daq_config", "expected_rc", "expected_msg"),
        (
            (
                {
                    "nof_tiles": 2,
                    "nof_antennas": 32,
                    "nof_correlator_samples": 90000,
                    "nof_correlator_channels": 2,
                },
                ResultCode.OK,
                "Daq reconfigured",
            ),
            ({}, ResultCode.REJECTED, "No configuration data supplied."),
            ("", ResultCode.REJECTED, "No configuration data supplied."),
        ),
    )
    def test_daq_server_configuration(
        self: TestDaqHandler,
        daq_address: str,
        daq_config: dict[str, Any],
        expected_rc: ResultCode,
        expected_msg: str,
    ) -> None:
        """
        Test for DAQ server configuration.

        :param daq_address: The address of the DAQ server.
        :param daq_config: The configuration to apply.
        :param expected_rc: The result code expected from `Configure`.
        :param expected_msg: The message expected from `Configure`.
        """
        daq_client = DaqClient(daq_address)
        assert daq_client.initialise("{}") == {
            "message": "Daq successfully initialised"
        }

        initial_config = daq_client.get_configuration()
        if daq_config != "":
            for k, v in daq_config.items():
                if k in initial_config:
                    assert initial_config[k] != v

        assert daq_client.configure_daq(json.dumps(daq_config)) == (
            expected_rc,
            expected_msg,
        )

        config = daq_client.get_configuration()
        if daq_config != "":
            for k, v in daq_config.items():
                assert config[k] == v

    @pytest.mark.parametrize(
        (
            "bandpass_config",
            "expected_result",
            "expected_msg",
            "expected_x_bandpass_plot",
            "expected_y_bandpass_plot",
            "expected_rms_plot",
        ),
        (
            (
                '{"plot_directory": "/plot"}',
                TaskStatus.REJECTED,
                "Current DAQ config is invalid. The `append_integrated` "
                "option must be set to false for bandpass monitoring.",
                [None],
                [None],
                [None],
            ),
            (
                "{}",
                TaskStatus.REJECTED,
                "Param `argin` must have key for `plot_directory`",
                [None],
                [None],
                [None],
            ),
            (
                '{"plot_directory": "/app/plot/", "auto_handle_daq": "True"}',
                TaskStatus.IN_PROGRESS,
                "Bandpass monitor active",
                [None],
                [None],
                [None],
            ),
            # ('{"bandpass_config": None}', (ResultCode, "Message")),
        ),
    )
    def test_start_stop_bandpass_monitor(  # pylint: disable=too-many-arguments
        self: TestDaqHandler,
        daq_address: str,
        bandpass_config: str,
        expected_result: TaskStatus,
        expected_msg: str,
        expected_x_bandpass_plot: str | None,
        expected_y_bandpass_plot: str | None,
        expected_rms_plot: str | None,
    ) -> None:
        """
        Test for starting and stopping the bandpass monitor.

        :param daq_address: The address of the DAQ server.
        :param bandpass_config: The configuration string to apply.
        :param expected_result: The expected first TaskStatus
        :param expected_msg: The expected first response.
        :param expected_x_bandpass_plot: The expected first x_bandpass_plot
        :param expected_y_bandpass_plot: The expected first y_bandpass_plot
        :param expected_rms_plot: The expected first rms_plot
        """
        expected_dict = {
            "result_code": expected_result,
            "message": expected_msg,
            "x_bandpass_plot": expected_x_bandpass_plot,
            "y_bandpass_plot": expected_y_bandpass_plot,
            "rms_plot": expected_rms_plot,
        }
        daq_client = DaqClient(daq_address)
        assert daq_client.initialise("{}") == {
            "message": "Daq successfully initialised"
        }

        # Check stopping before starting.
        assert daq_client.stop_bandpass_monitor() == (
            ResultCode.REJECTED,
            "Bandpass monitor not yet started.",
        )

        actual_result = daq_client.start_bandpass_monitor(bandpass_config)

        assert next(actual_result) == {
            "result_code": TaskStatus.IN_PROGRESS,
            "message": "StartBandpassMonitor command issued to gRPC stub",
        }
        # This sleep is legitimately here so we can detect
        # incorrect/out of order responses.
        time.sleep(2)
        assert next(actual_result) == expected_dict

        # Happy path has to be stopped and has an extra response.
        # Unhappy paths won't have started and skip this block.
        if expected_result == TaskStatus.IN_PROGRESS:
            assert (
                ResultCode.OK,
                "Bandpass monitor stopping.",
            ) == daq_client.stop_bandpass_monitor()

            assert next(actual_result) == {
                "result_code": TaskStatus.COMPLETED,
                "message": "Bandpass monitoring complete.",
                "x_bandpass_plot": [None],
                "y_bandpass_plot": [None],
                "rms_plot": [None],
            }

    def test_access_file_metadata(
        self: TestDaqHandler, daq_handler: DaqHandler, file_metadata: dict
    ) -> None:
        """
        Test for accessing the metadata on newly created files.

        :param daq_handler: the DaqHandler instance to use.
        :param file_metadata: the expected returned file metadata.
        """
        daq_handler._initialised = True
        start_result = daq_handler.start("INTEGRATED_CHANNEL_DATA")

        assert next(start_result) == "LISTENING"
        daq_handler._file_dump_callback("integrated_channel", "file_name")

        file_callback_result = next(start_result)
        assert isinstance(file_callback_result, tuple)
        extra_info = file_callback_result[2]
        assert json.loads(extra_info) == file_metadata
