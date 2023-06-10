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
from typing import Any

import grpc
import pytest
from google.protobuf.json_format import MessageToDict
from ska_control_model import ResultCode

from ska_low_mccs_daq.interface.generated_code import daq_pb2, daq_pb2_grpc

# TODO: [MCCS-1211] Workaround for ska-tango-testing bug.
gc.disable()


class TestMccsDaqServer:
    """Test class for MccsDaqServer tests."""

    @pytest.mark.parametrize(
        ("args", "expected_rc", "expected_msg"),
        (
            ("", ResultCode.OK, "Daq started"),
            ("invalidInput", ResultCode.FAILED, "Invalid DaqMode supplied"),
        ),
    )
    @pytest.mark.xfail
    def test_daq_server_start_stop_daq(
        self: TestMccsDaqServer,
        grpc_channel: str,
        args: str,
        expected_rc: ResultCode,
        expected_msg: str,
    ) -> None:
        """
        Test for Daq gRPC server start and stop.

        :param grpc_channel: The gRPC channel to communicate on.
        :param args: The argument with which to call `StartDaq`.
        :param expected_rc: The result code expected from `StartDaq`.
        :param expected_msg: The message expected from `StartDaq`.
        """
        with grpc.insecure_channel(grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response_init = stub.InitDaq(daq_pb2.configDaqRequest(config="{}"))
            assert response_init.result_code == ResultCode.OK
            assert response_init.message == "Daq successfully initialised"

            response_start = stub.StartDaq(daq_pb2.startDaqRequest(modes_to_start=args))
            assert response_start.result_code == expected_rc
            assert response_start.message == expected_msg

            response_stop = stub.StopDaq(daq_pb2.stopDaqRequest())
            assert response_stop.result_code == ResultCode.OK
            assert response_stop.message == "Daq stopped"

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
        self: TestMccsDaqServer,
        grpc_channel: str,
        daq_config: dict[str, Any],
        expected_rc: ResultCode,
        expected_msg: str,
    ) -> None:
        """
        Test for Daq gRPC server configuration.

        :param grpc_channel: The gRPC channel to communicate on.
        :param daq_config: The configuration to apply.
        :param expected_rc: The result code expected from `Configure`.
        :param expected_msg: The message expected from `Configure`.
        """
        with grpc.insecure_channel(grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response_init = stub.InitDaq(daq_pb2.configDaqRequest(config="{}"))
            assert response_init.result_code == ResultCode.OK
            assert response_init.message == "Daq successfully initialised"

            # Assert initial config is not the final config if we're applying a new one.
            response_initial_config = stub.GetConfiguration(daq_pb2.getConfigRequest())
            response_initial_config_dict = MessageToDict(
                message=response_initial_config, preserving_proto_field_name=True
            )

            if daq_config != "":
                for k, v in daq_config.items():
                    assert response_initial_config_dict[k] != v

            # Configure Daq (or try to)
            response_config = stub.ConfigureDaq(
                daq_pb2.configDaqRequest(config=json.dumps(daq_config))
            )
            assert response_config.result_code == expected_rc
            assert response_config.message == expected_msg

            # Check config was applied (if we applied one) by reading it back.
            response_getconfig = stub.GetConfiguration(daq_pb2.getConfigRequest())
            response_getconfig_dict = MessageToDict(
                message=response_getconfig, preserving_proto_field_name=True
            )
            if daq_config != "":
                for k, v in daq_config.items():
                    assert response_getconfig_dict[k] == v
