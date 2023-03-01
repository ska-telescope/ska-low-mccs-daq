# -*- coding: utf-8 -*-
#
# This file is part of the SKA SAT.LMC project
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.
"""This module implements the DaqServer part of the MccsDaqReceiver device."""
from __future__ import annotations

import json
import logging
import os
from concurrent import futures
from enum import IntEnum
from typing import Any, List, Optional

import grpc
from pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from ska_control_model import ResultCode

from ska_low_mccs_daq.gRPC_server.generated_code import daq_pb2, daq_pb2_grpc

__all__ = ["MccsDaqServer", "main"]


class DaqStatus(IntEnum):
    """DAQ Status."""

    LISTENING = 0
    RECEIVING = 1
    STOPPED = 2


class DaqCallbackBuffer:
    """A DAQ callback buffer to flush to gRPC Client every poll."""

    def __init__(self: DaqCallbackBuffer, logger: logging.Logger):
        self.logger: logging.Logger = logger
        self.data_types_received: List[str] = []
        self.written_files: List[str] = []
        self.extra_info: Any = []
        self.pending_evaluation: bool = False

    def add(
        self: DaqCallbackBuffer,
        data_type: str,
        file_name: str,
        additional_info: Optional[str] = None,
    ) -> None:
        """
        Add a item to the buffer and set pending evaluation to true.

        :param data_type: The DAQ data type written
        :param file_name: The filename written
        :param additional_info: Any additional information.
        """
        self.logger.info(f"File: {file_name}, with data: {data_type} added to buffer")

        self.data_types_received.append(data_type)
        self.written_files.append(file_name)
        if additional_info is not None:
            self.extra_info.append(additional_info)

        self.pending_evaluation = True

    def clear_buffer(self: DaqCallbackBuffer) -> None:
        """Clear buffer and set evaluation status to false."""
        self.data_types_received.clear()
        self.written_files.clear()
        self.extra_info.clear()
        self.pending_evaluation = False

    def send_buffer_to_client(
        self: DaqCallbackBuffer,
    ) -> Any:
        """
        Send buffer then clear buffer.

        :yields response: the call_info response.
        """
        for i, _ in enumerate(self.written_files):
            call_info = daq_pb2.CallInfo()
            call_info.data_types_received = self.data_types_received[i]
            call_info.files_written = self.written_files[i]

            response = daq_pb2.startDaqResponse()
            response.call_info.data_types_received = call_info.data_types_received
            response.call_info.files_written = call_info.files_written

            yield response

        # after yield clear buffer
        self.clear_buffer()
        self.logger.info("Buffer sent and cleared.")


def convert_daq_modes(consumers_to_start: str) -> list[DaqModes]:
    """
    Convert a string representation of DaqModes into a list of DaqModes.

    Breaks a comma separated list into a list of words,
        strips whitespace and extracts the `enum` part and casts the string
        into a DaqMode or directly cast an int into a DaqMode.

    :param consumers_to_start: A string containing a comma separated
        list of DaqModes.

    :return: a converted list of DaqModes or an empty list if no consumers supplied.
    """
    if consumers_to_start != "":
        consumer_list = consumers_to_start.split(",")
        converted_consumer_list = []
        for consumer in consumer_list:
            try:
                # Convert string representation of a DaqMode.
                converted_consumer = DaqModes[consumer.strip().split(".")[-1]]
            except KeyError:
                # Convert string representation of an int.
                converted_consumer = DaqModes(int(consumer))
            converted_consumer_list.append(converted_consumer)
        return converted_consumer_list
    return []


class MccsDaqServer(daq_pb2_grpc.DaqServicer):
    """An implementation of a MccsDaqServer device."""

    def __init__(self: MccsDaqServer):
        """Initialise this device."""
        self.daq_instance: DaqReceiver = None
        self._receiver_started: bool = False
        self.logger = logging.getLogger("daq-server")
        self.state = DaqStatus.STOPPED
        self.request_stop = False
        self.buffer = DaqCallbackBuffer(self.logger)

    def file_dump_callback(
        self: MccsDaqServer,
        data_mode: str,
        file_name: str,
        additional_info: Optional[str] = None,
    ) -> None:
        """
        Add metadata to buffer.

        :param data_mode: The DAQ data type written
        :param file_name: The filename written
        :param additional_info: Any additional information.
        """
        if additional_info is not None:
            self.buffer.add(data_mode, file_name, additional_info)
        else:
            self.buffer.add(data_mode, file_name)

    def update_status(self: MccsDaqServer) -> None:
        """Update the status of DAQ."""
        if self.state == DaqStatus.STOPPED:
            return
        if self.buffer.pending_evaluation:
            self.state = DaqStatus.RECEIVING
        else:
            self.state = DaqStatus.LISTENING

    def StartDaq(
        self: MccsDaqServer,
        request: daq_pb2.startDaqRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.commandResponse:
        """
        Start data acquisition with the current configuration.

        A infinite streaming loop will be started until told to stop.
        This will notify the gRPC client of state changes and metadata
        of files written to disk, e.g. `data_type`.`file_name`.
        The client will be notified on a cadence set by the polling period.

        :param request: arguments object containing `modes_to_start`
            `modes_to_start`: The list of consumers to start.
            `polling_period`: The period to send the buffer to the
            gRPC client.
        :param context: command metadata

        :yields: A streamed gRPC response.
        """
        modes_to_start: str = request.modes_to_start

        if not self._receiver_started:
            self.daq_instance.initialise_daq()
            self._receiver_started = True
        try:
            # Convert string representation to DaqModes
            converted_modes_to_start: list[DaqModes] = convert_daq_modes(modes_to_start)
        except ValueError as e:
            self.logger.error("Value Error! Invalid DaqMode supplied! %s", e)
        # TODO: callbacks this will collect all necessary
        # callbacks = None

        callbacks = [self.file_dump_callback] * len(converted_modes_to_start)

        self.daq_instance.start_daq(converted_modes_to_start, callbacks)
        self.request_stop = False

        # yield listening only once to notify client that daq is listening.
        response = daq_pb2.startDaqResponse()
        response.call_state.state = daq_pb2.CallState.LISTENING
        yield response

        self.state = DaqStatus.LISTENING
        self.logger.info("Daq listening......")

        # infinite loop (until told to stop)
        # TODO: should this be in a thread?
        while self.request_stop is False:
            if self.state == DaqStatus.RECEIVING:
                self.logger.info("Sending buffer to client ......")
                # send buffer to client
                yield from self.buffer.send_buffer_to_client()

            # check callbacks
            self.update_status()

        # if we have got here we have stopped
        response = daq_pb2.startDaqResponse()
        response.call_state.state = daq_pb2.CallState.STOPPED
        yield response

    def StopDaq(
        self: MccsDaqServer,
        request: daq_pb2.stopDaqRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.commandResponse:
        """
        Stop data acquisition.

        :param request: unused
        :param context: command metadata

        :return: a commandResponse object containing `result_code` and `message`
        """
        self.logger.info("Stopping daq.....")
        self.daq_instance.stop_daq()
        self._receiver_started = False
        self.request_stop = True
        return daq_pb2.commandResponse(result_code=ResultCode.OK, message="Daq stopped")

    def InitDaq(
        self: MccsDaqServer,
        request: daq_pb2.configDaqRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.commandResponse:
        """
        Initialise a new DaqReceiver instance.

        :param request: arguments object containing `config`
            `config`: The initial daq configuration to apply.
        :param context: command metadata

        :return: a commandResponse object containing `result_code` and `message`
        """
        self.logger.info("Initialising daq.")
        self.daq_instance = DaqReceiver()
        try:
            if request.config != "":
                self.daq_instance.populate_configuration(json.loads(request.config))

            self.daq_instance.initialise_daq()
            self._receiver_started = True
        # pylint: disable=broad-except
        except Exception as e:
            self.logger.error("Caught exception in `daq_grpc_server.InitDaq`: %s", e)
            return daq_pb2.commandResponse(
                result_code=ResultCode.FAILED, message=f"Caught exception: {e}"
            )
        self.logger.info("Daq initialised.")
        return daq_pb2.commandResponse(
            result_code=ResultCode.OK, message="Daq successfully initialised"
        )

    def ConfigureDaq(
        self: MccsDaqServer,
        request: daq_pb2.configDaqRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.commandResponse:
        """
        Apply a configuration to the DaqReceiver.

        :param request: arguments object containing `config`
            `config`: The initial daq configuration to apply.
        :param context: command metadata

        :return: a commandResponse object containing `result_code` and `message`
        """
        empty_config = ["", {}]
        daq_config = json.loads(request.config)
        self.logger.info("Configuring daq with: %s", daq_config)
        try:
            if daq_config in empty_config:
                self.logger.error("Daq was not reconfigured, no config data supplied.")
                return daq_pb2.commandResponse(
                    result_code=ResultCode.REJECTED,
                    message="No configuration data supplied.",
                )
            # else
            self.daq_instance.populate_configuration(daq_config)
            self.logger.info("Daq successfully reconfigured.")
            return daq_pb2.commandResponse(
                result_code=ResultCode.OK, message="Daq reconfigured"
            )

        # pylint: disable=broad-except
        except Exception as e:
            self.logger.error(
                "Caught exception in `daq_grpc_server.ConfigureDaq`: %s", e
            )
            return daq_pb2.commandResponse(
                result_code=ResultCode.FAILED, message=f"Caught exception: {e}"
            )

    def GetConfiguration(
        self: MccsDaqServer,
        request: daq_pb2.getConfigRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.getConfigResponse:
        """
        Retrieve the current DAQ configuration.

        :param request: Empty argument object.
        :param context: command metadata

        :return: a commandResponse object containing the current `config`.
        """
        configuration = self.daq_instance.get_configuration()

        # we cannot simply call json dumps here since bytes input
        for key, item in configuration.items():
            if isinstance(item, bytes):
                configuration[key] = item.decode("utf-8")

        return daq_pb2.getConfigResponse(
            config=json.dumps(configuration),
        )

    def DaqStatus(
        self: MccsDaqServer,
        request: daq_pb2.daqStatusRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.daqStatusResponse:
        """
        Provide status information for this MccsDaqReceiver.

        This method returns status as a json string with entries for:
            - Running Consumers: [DaqMode.name: str, DaqMode.value: int]
            - Receiver Interface: "Interface Name": str
            - Receiver Ports: [Port_List]: list[int]
            - Receiver IP: "IP_Address": str

        :param request: Empty argument object.
        :param context: command metadata

        :return: A json string containing the status of this DaqReceiver.
        """
        # 2. Get consumer list, filter by `running`
        full_consumer_list = self.daq_instance._running_consumers.items()
        running_consumer_list = [
            [consumer.name, consumer.value]
            for consumer, running in full_consumer_list
            if running
        ]
        # 3. Get Receiver Interface, Ports and IP (and later `Uptime`)
        receiver_interface = self.daq_instance._config["receiver_interface"]
        receiver_ports = self.daq_instance._config["receiver_ports"]
        receiver_ip = self.daq_instance._config["receiver_ip"]
        # 4. Compose into some format and return.
        status = {
            "Running Consumers": running_consumer_list,
            "Receiver Interface": receiver_interface,
            "Receiver Ports": receiver_ports,
            "Receiver IP": [
                receiver_ip.decode() if isinstance(receiver_ip, bytes) else receiver_ip
            ],
        }
        return daq_pb2.daqStatusResponse(
            status=json.dumps(status),
        )


def main() -> None:
    """
    Entrypoint for the module.

    Create and start a gRPC server.
    """
    print("Starting daq server...", flush=True)
    port = os.getenv("DAQ_GRPC_PORT", default="50051")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    daq_pb2_grpc.add_DaqServicer_to_server(MccsDaqServer(), server)
    server.add_insecure_port("[::]:" + port)
    server.start()
    print("Server started, listening on " + port, flush=True)
    server.wait_for_termination()
    print("Stopping daq server.")


if __name__ == "__main__":
    main()
