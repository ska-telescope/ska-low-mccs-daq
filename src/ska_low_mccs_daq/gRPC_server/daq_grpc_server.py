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
from typing import Union

import grpc
from pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from ska_control_model import ResultCode

from ska_low_mccs_daq.gRPC_server.generated_code import daq_pb2, daq_pb2_grpc

__all__ = ["MccsDaqServer", "main"]


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


def convert_daq_modes_int(modes_to_start: list[Union[int, DaqModes]]) -> list[DaqModes]:
    """
    Convert an integer or mixed list of modes_to_start into a list of DaqModes.

    If modes_to_start is already a list of DaqModes then the same list is returned.

    :param modes_to_start: A list of either integers representing DaqModes or a
        mixed list of integers and Daqmodes.

    :returns: A list of DaqModes.
    """
    converted_modes_to_start = [DaqModes(mode) for mode in modes_to_start]
    return converted_modes_to_start


class MccsDaqServer(daq_pb2_grpc.DaqServicer):
    """An implementation of a MccsDaqServer device."""

    def __init__(self: MccsDaqServer):
        """Initialise this device."""
        self.daq_instance: DaqReceiver = None
        self._receiver_started: bool = False
        self.logger = logging.getLogger("daq-server")

    def StartDaq(
        self: MccsDaqServer,
        request: daq_pb2.startDaqRequest,
        context: grpc.ServicerContext,
    ) -> daq_pb2.commandResponse:
        """
        Start data acquisition with the current configuration.

        :param request: arguments object containing `modes_to_start`
            `modes_to_start`: The list of consumers to start.
        :param context: command metadata

        :return: a commandResponse object containing `result_code` and `message`
        """
        self.logger.info("Starting DAQ")
        modes_to_start: str = request.modes_to_start
        if not self._receiver_started:
            self.daq_instance.initialise_daq()
            self._receiver_started = True
        try:
            # Convert string representation to DaqModes
            converted_modes_to_start: list[DaqModes] = convert_daq_modes(modes_to_start)
        except ValueError as e:
            self.logger.error("Value Error! Invalid DaqMode supplied! %s", e)
        # TODO: callbacks
        callbacks = None
        # callbacks = [self._received_data_callback] * len(converted_modes_to_start)
        self.daq_instance.start_daq(converted_modes_to_start, callbacks)
        self.logger.info("Daq started.")
        return daq_pb2.commandResponse(result_code=ResultCode.OK, message="Daq started")

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
        self.logger.info("Stopping daq.")
        self.daq_instance.stop_daq()
        self._receiver_started = False
        self.logger.info("Daq stopped.")
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
        self.logger.info("Configuring daq with: %s", request.config)
        try:
            if request.config != "":
                self.daq_instance.populate_configuration(json.loads(request.config))
                self.logger.info("Daq successfully reconfigured.")
                return daq_pb2.commandResponse(
                    result_code=ResultCode.OK, message="Daq reconfigured"
                )
            # else
            self.logger.error("Daq was not reconfigured, no config data supplied.")
            return daq_pb2.commandResponse(
                result_code=ResultCode.REJECTED,
                message="ERROR: No configuration data supplied.",
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