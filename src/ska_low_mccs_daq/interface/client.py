# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""An implementation of a client interface for a DAQ receiver."""
from __future__ import annotations

from typing import Any, Iterator

import grpc
from google.protobuf.json_format import MessageToDict
from ska_control_model import ResultCode, TaskStatus

from .generated_code import daq_pb2, daq_pb2_grpc

__all__ = ["DaqClient"]


class DaqClient:
    """A client for a DAQ gRPC server."""

    def __init__(
        self: DaqClient,
        address: str,
    ) -> None:
        """
        Initialise a new instance.

        :param address: address of the DAQ server.
            In this implementation this is a gRPC channel.
            However we deliberately leave this interface
            as taking an abstract string "address",
            in case we ever want to change the underlying implementation.
        """
        self._grpc_channel = address

    def initialise(
        self: DaqClient,
        configuration: str,
    ) -> dict[str, Any]:
        """
        Tell the DAQ server to initialise the DAQ by applying a configuration.

        :param configuration: the configuration to apply, as a JSON string.

        :return: the result of the call
        """
        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response = stub.InitDaq(daq_pb2.configDaqRequest(config=configuration))
            return MessageToDict(response)

    def get_configuration(self: DaqClient) -> dict[str, Any]:
        """
        Tell the DAQ server to return the current DAQ configuration.

        :return: the current DAQ configuration
        """
        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response = stub.GetConfiguration(daq_pb2.getConfigRequest())
        return MessageToDict(message=response, preserving_proto_field_name=True)

    def configure_daq(
        self: DaqClient,
        daq_config: str,
    ) -> tuple[ResultCode, str]:
        """
        Tell the DAQ server to apply the given DAQ configuration.

        :param daq_config: the configuration to be applied,
            in the form of a JSON string.

        :return: a (result code, message) tuple
        """
        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response = stub.ConfigureDaq(daq_pb2.configDaqRequest(config=daq_config))
        return (response.result_code, response.message)

    def get_status(self: DaqClient) -> str:
        """
        Request the status of the DAQ from the DAQ server.

        :return: the DAQ status as a JSON-encoded string
        """
        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response = stub.DaqStatus(daq_pb2.daqStatusRequest())
        return response.status

    def start_daq(self: DaqClient, modes_to_start: str) -> Iterator[dict[str, Any]]:
        """
        Tell the DAQ server to start the DAQ.

        :param modes_to_start: the DAQ modes to be started.

        :yields: updates on DAQ status.
        """
        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            responses = stub.StartDaq(
                daq_pb2.startDaqRequest(
                    modes_to_start=modes_to_start,
                )
            )
            yield {
                "status": TaskStatus.IN_PROGRESS,
                "message": "Start Command issued to gRPC stub",
            }

            for response in responses:
                response_dict: dict[str, Any] = {}  # XXX Make this a TypedDict
                if response.HasField("call_state"):
                    daq_state = response.call_state.state
                    # When we start the daq it will respond with a streaming update
                    # When it streams listening we notify the task_callback.
                    if daq_state == daq_pb2.CallState.State.LISTENING:
                        response_dict["status"] = TaskStatus.COMPLETED
                        response_dict[
                            "message"
                        ] = "Daq has been started and is listening"
                    # When stopped we need to ensure we clean up the thread.
                    # This is done with responses.cancel()
                    elif daq_state == daq_pb2.CallState.State.STOPPED:
                        # First the gRPC server hangs up the call.
                        # then the Client hangs up the call.
                        responses.cancel()
                        return

                if response.HasField("call_info"):
                    response_dict["types"] = response.call_info.data_types_received
                    response_dict["files"] = response.call_info.files_written

                yield response_dict

    def stop_daq(self: DaqClient) -> tuple[ResultCode, str]:
        """
        Tell the DAQ server to stop the DAQ.

        :return: a (result_code, message) tuple
        """
        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response = stub.StopDaq(daq_pb2.stopDaqRequest())
        return (response.result_code, response.message)
