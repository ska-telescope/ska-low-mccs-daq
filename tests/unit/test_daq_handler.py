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
from multiprocessing.pool import ThreadPool
from typing import Any

import pytest
from ska_control_model import ResultCode, TaskStatus
from ska_low_mccs_daq_interface.client import DaqClient


class TestDaqHandler:
    """Test class for DaqHandler tests."""

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
        ("bandpass_config", "expected_result"),
        (
            (
                '{"station_config_path": "station_config.yml", "plot_directory": "/plot"}',
                (
                    ResultCode.REJECTED,
                    "Current DAQ config is invalid. The `append_integrated` option must be set to false for bandpass monitoring.",
                ),
            ),
            (
                '{"station_config_path": "station_config.yml", "plot_directory": "/plot", "auto_handle_daq": "True"}',
                (
                    ResultCode.REJECTED,
                    "Specified configuration file (station_config.yml) does not exist.",
                ),
            ),
            (
                '{"station_config_path": "/app/config/default_config.yml", "plot_directory": "/plot", "auto_handle_daq": "True"}',
                (ResultCode.FAILED, "Unable to create plotting directory at: /plot"),
            ),
            (
                "{}",
                (
                    ResultCode.REJECTED,
                    "Param `argin` must have keys for `station_config_path` and `plot_directory`",
                ),
            ),
            (
                '{"station_config_path": "blah"}',
                (
                    ResultCode.REJECTED,
                    "Param `argin` must have keys for `station_config_path` and `plot_directory`",
                ),
            ),
            (
                '{"plot_directory": "blahblah"}',
                (
                    ResultCode.REJECTED,
                    "Param `argin` must have keys for `station_config_path` and `plot_directory`",
                ),
            ),
            (
                '{"station_config_path": "nonexistent_station_config.yml", "plot_directory": "/plot", "auto_handle_daq": "True"}',
                (
                    ResultCode.REJECTED,
                    "Specified configuration file (nonexistent_station_config.yml) does not exist.",
                ),
            ),
            ('{"station_config_path": "/app/config/default_config.yml", "plot_directory": "/app/plot", "auto_handle_daq": "True"}', (ResultCode.OK, "Bandpass monitoring complete.")),
            # ('{"bandpass_config": None}', (ResultCode, "Message")),
        ),
    )
    def test_start_stop_bandpass_monitor(
        self: TestDaqHandler,
        daq_address: str,
        bandpass_config: str,
        expected_result: tuple[ResultCode, str],
    ) -> None:
        """
        Test for starting and stopping the bandpass monitor.

        :param daq_address: The address of the DAQ server.
        :param daq_config: The configuration to apply.
        :param expected_rc: The result code expected from `Configure`.
        :param expected_msg: The message expected from `Configure`.
        """
        daq_client = DaqClient(daq_address)
        assert daq_client.initialise("{}") == {
            "message": "Daq successfully initialised"
        }
        pool = ThreadPool(processes=1)
        actual_result = pool.apply_async(
            daq_client.start_bandpass_monitor, args=[bandpass_config]
        )
        # Wait for bandpass monitor
        time.sleep(3)
        if expected_result[0] == ResultCode.OK:
            assert (
                ResultCode.OK,
                "Bandpass monitor stopping.",
            ) == daq_client.stop_bandpass_monitor()
        assert actual_result.get() == expected_result
