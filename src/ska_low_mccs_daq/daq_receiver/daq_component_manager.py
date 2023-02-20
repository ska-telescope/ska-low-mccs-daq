# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module implements component management for DaqReceivers."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

import grpc
from typing import Iterator
# from pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from ska_control_model import CommunicationStatus, ResultCode, TaskStatus
from ska_low_mccs_common.component import MccsComponentManager, check_communicating

from concurrent.futures import ThreadPoolExecutor
from ska_low_mccs_daq.gRPC_server import daq_pb2, daq_pb2_grpc
import threading
__all__ = ["DaqComponentManager"]

# pylint: disable=abstract-method,too-many-instance-attributes
class DaqComponentManager(MccsComponentManager):
    """A component manager for a DaqReceiver."""

    # pylint: disable=too-many-arguments, too-many-locals
    def __init__(
        self: DaqComponentManager,
        daq_id: int,
        receiver_interface: str,
        receiver_ip: str,
        receiver_ports: str,
        grpc_port: str,
        grpc_host: str,
        consumers_to_start: str,
        logger: logging.Logger,
        max_workers: int,
        communication_state_changed_callback: Callable[[CommunicationStatus], None],
        component_state_changed_callback: Callable[[dict[str, Any]], None],
        received_data_callback: Callable[[str, str, int], None],
    ) -> None:
        """
        Initialise a new instance of DaqComponentManager.

        :param daq_id: The ID of this DaqReceiver.
        :param receiver_interface: The interface this DaqReceiver is to watch.
        :param receiver_ip: The IP address of this DaqReceiver.
        :param receiver_ports: The port this DaqReceiver is to watch.
        :param grpc_port: The gRPC port this DaqReceiver will communicate on.
        :param grpc_host: An optional override to force gRPC to
            use a particular host. Used in testing.
        :param consumers_to_start: The default consumers to be started.
        :param logger: the logger to be used by this object.
        :param max_workers: the maximum worker threads for the slow commands
            associated with this component manager.
        :param communication_state_changed_callback: callback to be
            called when the status of the communications channel between
            the component manager and its component changes
        :param component_state_changed_callback: callback to be
            called when the component state changes
        :param received_data_callback: callback to be called when data is
            received from a tile
        :param grpc_host: An optional override to force gRPC to
            use a particular host. Used in testing.
        """
        super().__init__(
            logger,
            max_workers,
            communication_state_changed_callback,
            component_state_changed_callback,
        )
        self._consumers_to_start: str = "Daqmodes.INTEGRATED_CHANNEL_CONSUMER"
        self._receiver_started: bool = False
        self._daq_id = str(daq_id).zfill(3)
        self._receiver_interface = receiver_interface
        self._receiver_ip = receiver_ip
        self._receiver_ports = receiver_ports
        self._received_data_callback = received_data_callback
        self._set_consumers_to_start(consumers_to_start)
        self._grpc_host = grpc_host
        self._grpc_port = grpc_port
        self._grpc_channel = f"{self._grpc_host}:{self._grpc_port}"

        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            configuration = json.dumps(self._get_default_config())
            response = stub.InitDaq(daq_pb2.configDaqRequest(config=configuration))
            if response.result_code != ResultCode.OK:
                self.logger.error(
                    "InitDaq failed with response: %i", response.result_code
                )

    def start_communicating(self: DaqComponentManager) -> None:
        """Establish communication with the DaqReceiver components."""
        super().start_communicating()
        # Do things that might need to be done.
        # e.g. Do we need to be connected to a station etc?
        # For now we'll just set comms to ESTABLISHED since there's no physical device.
        self.update_communication_state(CommunicationStatus.ESTABLISHED)

    def stop_communicating(self: DaqComponentManager) -> None:
        """Break off communication with the DaqReceiver components."""
        super().stop_communicating()

    def _get_default_config(self: DaqComponentManager) -> dict[str, Any]:
        """
        Retrieve and return a default DAQ configuration.

        :return: A DAQ configuration.
        """
        daq_config = {
            "nof_antennas": 16,
            "nof_channels": 512,
            "nof_beams": 1,
            "nof_polarisations": 2,
            "nof_tiles": 1,
            "nof_raw_samples": 32768,
            "raw_rms_threshold": -1,
            "nof_channel_samples": 1024,
            "nof_correlator_samples": 1835008,
            "nof_correlator_channels": 1,
            "continuous_period": 0,
            "nof_beam_samples": 42,
            "nof_beam_channels": 384,
            "nof_station_samples": 262144,
            "append_integrated": True,
            "sampling_time": 1.1325,
            "sampling_rate": (800e6 / 2.0) * (32.0 / 27.0) / 512.0,
            "oversampling_factor": 32.0 / 27.0,
            "receiver_ports": self._receiver_ports,
            "receiver_interface": self._receiver_interface,
            "receiver_ip": self._receiver_ip,
            "receiver_frame_size": 8500,
            "receiver_frames_per_block": 32,
            "receiver_nof_blocks": 256,
            "receiver_nof_threads": 1,
            "directory": ".",
            "logging": True,
            "write_to_disk": True,
            "station_config": None,
            "max_filesize": None,
            "acquisition_duration": -1,
            "acquisition_start_time": -1,
            "description": "",
            "observation_metadata": {},  # This is populated automatically
        }
        return daq_config

    def get_configuration(self: DaqComponentManager) -> dict[str, Any]:
        """
        Get the active configuration from DAQ.

        :return: The configuration in use by the DaqReceiver instance.
        """
        # Make gRPC call to configure.
        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response = stub.GetConfiguration(daq_pb2.getConfigRequest())
        return response.config

    def _set_consumers_to_start(
        self: DaqComponentManager, consumers_to_start: str
    ) -> tuple[ResultCode, str]:
        """
        Set default consumers to start.

        Set consumers to be started when `start_daq` is called
            without specifying a consumer.

        :param consumers_to_start: A string containing a comma separated
            list of DaqModes.

         :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        self._consumers_to_start = consumers_to_start
        return (ResultCode.OK, "SetConsumers command completed OK")

    def configure_daq(
        self: DaqComponentManager,
        daq_config: str,
    ) -> None:
        """
        Apply a configuration to the DaqReceiver.

        :param daq_config: A json containing configuration settings.
        """
        self.logger.info("Configuring DAQ receiver.")
        # Make gRPC call to configure.
        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response = stub.ConfigureDaq(daq_pb2.configDaqRequest(config=daq_config))
            if response.result_code != ResultCode.OK:
                self.logger.error(
                    "Configure failed with response: %i", response.result_code
                )
        self.logger.info("DAQ receiver configuration complete.")

    @check_communicating
    def start_daq(
        self: DaqComponentManager,
        modes_to_start: str = "",
        task_callback: Optional[Callable] = None,
    ) -> tuple[ResultCode, str]:
        """
        Start data acquisition with the current configuration.

        Extracts the required consumers from configuration and starts
        them.

        :param modes_to_start: The DAQ consumers to start.
        :param task_callback: Update task state, defaults to None

        :return: a task status and response message
        """
        return self.submit_task(
            self._start_daq, args=[modes_to_start], task_callback=task_callback
        )

    def _start_daq(
        self,
        modes_to_start: str,
        task_callback: Optional[Callable] = None,
        task_abort_event: Optional[threading.Event] = None,
    ) -> None:

        if task_callback:
            task_callback(status=TaskStatus.IN_PROGRESS)
        try:
            if modes_to_start == "":
                modes_to_start = self._consumers_to_start

            with grpc.insecure_channel(self._grpc_channel) as channel:
                stub = daq_pb2_grpc.DaqStub(channel)
                responses = stub.StartDaq(
                    daq_pb2.startDaqRequest(modes_to_start=modes_to_start)
                )
                for response in responses:
                    if response.HasField("call_state"):
                        daq_state = response.call_state.state
                        self.logger.info(f"got a response ::: {daq_pb2.CallState.State.Name(daq_state)}")

                    if response.HasField("call_info"):
                        self.logger.info(f"info")
                        data_types_received = response.call_info.data_types_received
                        self.logger.info(f"got a type ::: {data_types_received}")
                        files_written = response.call_info.files_written
                        self.logger.info(f"got a file ::: {files_written}")
                        #send all this information to the callback

                        self._received_data_callback(data_types_received, files_written)


        except Exception as e:
            self.logger.info(f"got a exception {e}")
            

    def stop_daq(
        self: DaqComponentManager,
        task_callback: Optional[Callable] = None,
    ) -> tuple[ResultCode, str]:
        """
        Stop data acquisition.

        Stops the DAQ receiver and all running consumers.

        :param task_callback: Update task state, defaults to None
        :return: a task status and response message
        """
        self.logger.debug("Entering stop_daq")
        if task_callback:
            task_callback(status=TaskStatus.IN_PROGRESS)

        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response = stub.StopDaq(daq_pb2.stopDaqRequest())

        if task_callback:
            if response.result_code == ResultCode.OK.value:
                task_callback(status=TaskStatus.COMPLETED)
            else:
                task_callback(status=TaskStatus.FAILED)
        return (response.result_code, response.message)

    def daq_status(
        self: DaqComponentManager,
        task_callback: Optional[Callable] = None,
    ) -> str:
        """
        Provide status information for this MccsDaqReceiver.

        :param task_callback: Update task state, defaults to None
        :return: a task status and response message
        """
        self.logger.debug("Entering daq_status")
        if task_callback:
            task_callback(status=TaskStatus.IN_PROGRESS)

        with grpc.insecure_channel(self._grpc_channel) as channel:
            stub = daq_pb2_grpc.DaqStub(channel)
            response = stub.DaqStatus(daq_pb2.daqStatusRequest())

        if task_callback:
            task_callback(status=TaskStatus.COMPLETED)
        return response.status
