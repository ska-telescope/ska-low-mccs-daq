# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.
"""This module implements a gRPC DAQ server."""
from __future__ import annotations

import json
from concurrent import futures
from contextlib import contextmanager
from typing import Any, Iterator, Protocol

import grpc
from ska_control_model import ResultCode

from ..interface.generated_code import daq_pb2, daq_pb2_grpc


class DaqServerBackendProtocol(Protocol):
    """Protocol for a class that can act as a backend for this server."""

    def start(
        self: DaqServerBackendProtocol,
        modes_to_start: str,
    ) -> daq_pb2.startDaqResponse:
        """
        Start the DaqConsumers.

        The MccsDaqReceiver will begin watching the interface specified in the
        configuration and will start the configured consumers.

        :param modes_to_start: the DAQ modes to start

        :return: A streamed response containing a the call_state or call_info
            message indicating events posted by server. The message is for
            information purpose only.
        """  # noqa: DAR202

    def stop(self: DaqServerBackendProtocol) -> tuple[ResultCode, str]:
        """
        Stop the DaqReceiver.

        The DAQ receiver will cease watching the specified interface
        and will stop all running consumers.

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """  # noqa: DAR202

    def initialise(
        self: DaqServerBackendProtocol,
        config: dict[str, Any],
    ) -> tuple[ResultCode, str]:
        """
        Initialise a new DaqReceiver instance.

        :param config: the configuration to apply

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """  # noqa: DAR202

    def configure(
        self: DaqServerBackendProtocol,
        config: dict[str, Any],
    ) -> tuple[ResultCode, str]:
        """
        Configure the DaqReceiver.

        Applies the specified configuration to the DaqReceiver.

        :param config: the configuration to apply

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """  # noqa: DAR202

    def get_configuration(self: DaqServerBackendProtocol) -> dict[str, Any]:
        """
        Get the Configuration from DAQ.

        :returns: A JSON-encoded dictionary of the configuration.

        >>> dp.tango.DeviceProxy("low-mccs/daqreceiver/001")
        >>> jstr = dp.command_inout("GetConfiguration")
        >>> dict = json.loads(jstr)
        """  # noqa: DAR202

    def get_status(self: DaqServerBackendProtocol) -> dict[str, Any]:
        """
        Return station information for this DAQ instance.

        This method returns status as a dictionary with entries for;
        - Daq Health; [HealthState.name; str, HealthState.value; int]
        - Running Consumers; [DaqMode.name; str, DaqMode.value; int]
        - Receiver Interface; "Interface Name"; str
        - Receiver Ports; [Port_List]; list[int]
        - Receiver IP; "IP_Address"; str

        :returns: A status dictionary.
        """  # noqa: DAR202


class DaqServer(daq_pb2_grpc.DaqServicer):
    """An implementation of a DaqServer."""

    def __init__(self: DaqServer, backend: DaqServerBackendProtocol) -> None:
        """
        Initialise a new instance.

        :param backend: the backend DAQ instance for which this server
            provides an interface.
        """
        self._backend = backend

    def StartDaq(
        self: DaqServer, request: daq_pb2.startDaqRequest, context: grpc.ServicerContext
    ) -> Iterator[daq_pb2.startDaqResponse]:
        """
        Start the DaqConsumers.

        The MccsDaqReceiver will begin watching the interface specified in the
        configuration and will start the configured consumers.

        :param request: the gRPC request
        :param context: the gRPC servicer context

        :yield: Responsed to be streamed, containing the call_state or call_info
            message indicating events posted by server. The message is for
            information purpose only.
        """
        for update in self._backend.start(request.modes_to_start):
            response = daq_pb2.startDaqResponse()
            match update:
                case "LISTENING":
                    response.call_state.state = daq_pb2.CallState.LISTENING
                case (data_types_received, files_written):
                    response.call_info.data_types_received = data_types_received
                    response.call_info.files_written = files_written
                case "STOPPED":
                    response.call_state.state = daq_pb2.CallState.STOPPED
            yield response

    def StopDaq(
        self: DaqServer, request: daq_pb2.stopDaqRequest, context: grpc.ServicerContext
    ) -> daq_pb2.commandResponse:
        """
        Stop the DaqReceiver.

        The DAQ receiver will cease watching the specified interface
        and will stop all running consumers.

        :param request: the gRPC request
        :param context: the gRPC servicer context

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        result_code, message = self._backend.stop()
        return daq_pb2.commandResponse(result_code=result_code, message=message)

    def InitDaq(
        self: DaqServer,
        request: daq_pb2.configDaqRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.commandResponse:
        """
        Initialise a new DaqReceiver instance.

        :param request: the gRPC request
        :param context: the gRPC servicer context

        :return: a commandResponse object containing `result_code` and `message`
        """
        configuration = json.loads(request.config)
        result_code, message = self._backend.initialise(configuration)
        return daq_pb2.commandResponse(result_code=result_code, message=message)

    def ConfigureDaq(
        self: DaqServer,
        request: daq_pb2.configDaqRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.commandResponse:
        """
        Configure the DaqReceiver.

        Applies the specified configuration to the DaqReceiver.

        :param request: the gRPC request
        :param context: the gRPC servicer context

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        daq_config = json.loads(request.config)
        result_code, message = self._backend.configure(daq_config)
        return daq_pb2.commandResponse(result_code=result_code, message=message)

    def GetConfiguration(
        self: DaqServer,
        request: daq_pb2.getConfigRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.ConfigurationResponse:
        """
        Get the Configuration from DAQ.

        :param request: the gRPC request
        :param context: the gRPC servicer context

        :returns: A JSON-encoded dictionary of the configuration.

        >>> dp.tango.DeviceProxy("low-mccs/daqreceiver/001")
        >>> jstr = dp.command_inout("GetConfiguration")
        >>> dict = json.loads(jstr)
        """
        configuration = self._backend.get_configuration()

        # we make a copy as we want to modify type for gRPC communications.
        configuration_copy = configuration.copy()

        # Here we are casting to (str) type to match proto grpc configurations.
        attributes_to_cast = ["observation_metadata", "receiver_ports"]

        for attribute in attributes_to_cast:
            configuration_copy[attribute] = str(configuration_copy[attribute])

        return daq_pb2.ConfigurationResponse(**configuration_copy)

    def DaqStatus(
        self: DaqServer,
        request: daq_pb2.daqStatusRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.daqStatusResponse:
        """
        Provide status information for this MccsDaqReceiver.

        This method returns status as a json string with entries for;
        - Daq Health; [HealthState.name; str, HealthState.value; int]
        - Running Consumers; [DaqMode.name; str, DaqMode.value; int]
        - Receiver Interface; "Interface Name"; str
        - Receiver Ports; [Port_List]; list[int]
        - Receiver IP; "IP_Address"; str

        :param request: the gRPC request
        :param context: the gRPC servicer context

        :returns: A json string containing the status of this DaqReceiver.
        """
        status = self._backend.get_status()
        return daq_pb2.daqStatusResponse(
            status=json.dumps(status),
        )


def run_server_forever(backend: DaqServerBackendProtocol, port: int) -> None:
    """
    Run the DAQ server until terminated.

    :param backend: the backend for which this server provides an interface.
    :param port: the port on which to run the server.
        If set to 0, the server will be run on any available port.
        The actual port on which the server is running
        will be printed to stdout.
    """
    print("Starting daq server...", flush=True)
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    daq_servicer = DaqServer(backend)
    daq_pb2_grpc.add_DaqServicer_to_server(daq_servicer, grpc_server)
    actual_port = grpc_server.add_insecure_port(f"[::]:{port}")
    grpc_server.start()
    print(f"Server started, listening on {actual_port}", flush=True)
    grpc_server.wait_for_termination()
    print("Stopping daq server.")


@contextmanager
def server_context(
    backend: DaqServerBackendProtocol, port: int = 50051
) -> Iterator[int]:
    """
    Run the DAQ server in a context.

    The server will be launched when the context is entered,
    and shut down when the context is exited.

    :param backend: the backend for which this server provides an interface.
    :param port: the port on which to run the server.
        If set to 0, the server will be run on any available port.
        The actual port on which the server is running
        will be yielded as the context handle.

    :yield: the actual port on which the server is running.
    """
    print("Starting daq server...", flush=True)
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    daq_servicer = DaqServer(backend)
    daq_pb2_grpc.add_DaqServicer_to_server(daq_servicer, grpc_server)
    actual_port = grpc_server.add_insecure_port(f"[::]:{port}")
    grpc_server.start()
    yield actual_port
    print("Stopping daq server.")
    grpc_server.stop(grace=3)
