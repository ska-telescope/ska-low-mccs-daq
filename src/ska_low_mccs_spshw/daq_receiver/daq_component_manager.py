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
import threading
from typing import Any, Callable, Optional

from ska_control_model import CommunicationStatus, PowerState, ResultCode, TaskStatus
from ska_low_mccs_daq_interface import DaqClient
from ska_tango_base.base import check_communicating
from ska_tango_base.executor import TaskExecutorComponentManager

__all__ = ["DaqComponentManager"]


# pylint: disable=abstract-method,too-many-instance-attributes
class DaqComponentManager(TaskExecutorComponentManager):
    """A component manager for a DaqReceiver."""

    # pylint: disable=too-many-arguments
    def __init__(
        self: DaqComponentManager,
        daq_id: int,
        receiver_interface: str,
        receiver_ip: str,
        receiver_ports: str,
        daq_address: str,
        consumers_to_start: str,
        logger: logging.Logger,
        max_workers: int,
        communication_state_callback: Callable[[CommunicationStatus], None],
        component_state_callback: Callable[..., None],
        received_data_callback: Callable[[str, str, str], None],
    ) -> None:
        """
        Initialise a new instance of DaqComponentManager.

        :param daq_id: The ID of this DaqReceiver.
        :param receiver_interface: The interface this DaqReceiver is to watch.
        :param receiver_ip: The IP address of this DaqReceiver.
        :param receiver_ports: The port this DaqReceiver is to watch.
        :param daq_address: the address of the DAQ receiver.
            This is dependent on the communication mechanism used.
            For gRPC, this is the channel.
        :param consumers_to_start: The default consumers to be started.
        :param logger: the logger to be used by this object.
        :param max_workers: the maximum worker threads for the slow commands
            associated with this component manager.
        :param communication_state_callback: callback to be
            called when the status of the communications channel between
            the component manager and its component changes
        :param component_state_callback: callback to be
            called when the component state changes
        :param received_data_callback: callback to be called when data is
            received from a tile
        """
        self._power_state_lock = threading.RLock()
        self._power_state: Optional[PowerState] = None
        self._faulty: Optional[bool] = None
        self._consumers_to_start: str = "Daqmodes.INTEGRATED_CHANNEL_DATA"
        self._receiver_started: bool = False
        self._daq_id = str(daq_id).zfill(3)
        self._receiver_interface = receiver_interface
        self._receiver_ip = receiver_ip
        self._receiver_ports = receiver_ports
        self._received_data_callback = received_data_callback
        self._set_consumers_to_start(consumers_to_start)
        self._daq_client = DaqClient(daq_address)

        super().__init__(
            logger,
            communication_state_callback,
            component_state_callback,
            max_workers=max_workers,
            power=None,
            fault=None,
        )

    def start_communicating(self: DaqComponentManager) -> None:
        """Establish communication with the DaqReceiver components."""
        if self.communication_state == CommunicationStatus.ESTABLISHED:
            return
        if self.communication_state == CommunicationStatus.DISABLED:
            self._update_communication_state(
                CommunicationStatus.NOT_ESTABLISHED
            )  # noqa: E501

        try:
            configuration = json.dumps(self._get_default_config())

            response = self._daq_client.initialise(configuration)
            self.logger.info(response["message"])
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error("Caught exception in start_communicating: %s", e)
            if self._component_state_callback is not None:
                self._component_state_callback(fault=True)

        self._update_communication_state(CommunicationStatus.ESTABLISHED)

    def stop_communicating(self: DaqComponentManager) -> None:
        """Break off communication with the DaqReceiver components."""
        if self.communication_state == CommunicationStatus.DISABLED:
            return
        self._update_communication_state(CommunicationStatus.DISABLED)
        self._update_component_state(power=None, fault=None)

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

    @check_communicating
    def get_configuration(self: DaqComponentManager) -> dict[str, str]:
        """
        Get the active configuration from DAQ.

        :return: The configuration in use by the DaqReceiver instance.
        """
        return self._daq_client.get_configuration()

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

    @check_communicating
    def configure_daq(
        self: DaqComponentManager,
        daq_config: str,
    ) -> tuple[ResultCode, str]:
        """
        Apply a configuration to the DaqReceiver.

        :param daq_config: A json containing configuration settings.

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        self.logger.info("Configuring DAQ receiver.")
        result_code, message = self._daq_client.configure_daq(daq_config)
        if result_code == ResultCode.OK:
            self.logger.info("DAQ receiver configuration complete.")
        else:
            self.logger.error(f"Configure failed with response: {result_code}")
        return result_code, message

    @check_communicating
    def start_daq(
        self: DaqComponentManager,
        modes_to_start: str,
        task_callback: Optional[Callable] = None,
    ) -> tuple[TaskStatus, str]:
        """
        Start data acquisition with the current configuration.

        Extracts the required consumers from configuration and starts
        them.

        :param modes_to_start: A comma separated string of daq modes.
        :param task_callback: Update task state, defaults to None

        :return: a task status and response message
        """
        return self.submit_task(
            self._start_daq,
            args=[modes_to_start],
            task_callback=task_callback,
        )

    def _start_daq(
        self: DaqComponentManager,
        modes_to_start: str,
        task_callback: Optional[Callable],
        task_abort_event: Optional[threading.Event] = None,
    ) -> None:
        """
        Start DAQ on the gRPC server, stream response.

        This will request the gRPC server to send a streamed response,
        We can then loop through the responses and respond. The reason we use
        a streamed response rather than a callback is there is no
        obvious way to register a callback mechanism in gRPC.

        :param modes_to_start: A comma separated string of daq modes.
        :param task_callback: Update task state, defaults to None
        :param task_abort_event: Check for abort, defaults to None

        :return: none
        """
        if task_callback:
            task_callback(status=TaskStatus.IN_PROGRESS)
        try:
            modes_to_start = modes_to_start or self._consumers_to_start
            for response in self._daq_client.start_daq(modes_to_start):
                if task_callback:
                    task_callback(
                        status=response["status"],
                        result=response["message"],
                    )
                if "files" in response:
                    files_written = response["files"]
                    data_types_received = response["types"]
                    metadata = response["extras"]
                    self.logger.info(
                        f"File: {files_written}, Type: {data_types_received}"
                    )
                    self._received_data_callback(
                        data_types_received,
                        files_written,
                        metadata,
                    )
        except Exception as e:  # pylint: disable=broad-exception-caught  # XXX
            if task_callback:
                task_callback(
                    status=TaskStatus.FAILED,
                    result=f"Exception: {e}",
                )
            return

    @check_communicating
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

        result_code, message = self._daq_client.stop_daq()
        if task_callback:
            if result_code == ResultCode.OK:
                task_callback(status=TaskStatus.COMPLETED)
            else:
                task_callback(status=TaskStatus.FAILED)
        return (result_code, message)

    @check_communicating
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

        status = self._daq_client.get_status()
        if task_callback:
            task_callback(status=TaskStatus.COMPLETED)
        self.logger.debug(f"Exiting daq_status with: {status}")
        return status
