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
import random
import threading
from datetime import date
from functools import partial
from pathlib import PurePath
from time import sleep
from typing import Any, Callable, Final, Optional

import numpy as np
from ska_control_model import CommunicationStatus, PowerState, ResultCode, TaskStatus
from ska_low_mccs_daq_interface import DaqClient
from ska_ser_skuid.client import SkuidClient  # type: ignore
from ska_tango_base.base import JSONData, TaskCallbackType, check_communicating
from ska_tango_base.executor import TaskExecutor, TaskExecutorComponentManager

__all__ = ["DaqComponentManager"]
SUBSYSTEM_SLUG = "ska-low-mccs"


# pylint: disable=abstract-method,too-many-instance-attributes
class DaqComponentManager(TaskExecutorComponentManager):
    """A component manager for a DaqReceiver."""

    NOF_ANTS_PER_STATION: Final = 256

    # pylint: disable=too-many-arguments
    def __init__(
        self: DaqComponentManager,
        daq_id: int,
        receiver_interface: str,
        receiver_ip: str,
        receiver_ports: str,
        daq_address: str,
        consumers_to_start: str,
        skuid_url: str,
        logger: logging.Logger,
        communication_state_callback: Callable[[CommunicationStatus], None],
        component_state_callback: Callable[..., None],
        received_data_callback: Callable[[str, str, str], None],
        daq_initialisation_retry_frequency: int = 5,
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
        :param skuid_url: The address at which a SKUID service is running.
        :param logger: the logger to be used by this object.
        :param communication_state_callback: callback to be
            called when the status of the communications channel between
            the component manager and its component changes
        :param component_state_callback: callback to be
            called when the component state changes
        :param received_data_callback: callback to be called when data is
            received from a tile
        :param daq_initialisation_retry_frequency: Frequency at which daq
            initialisation in retried.
        """
        self._power_state_lock = threading.RLock()
        self._power_state: Optional[PowerState] = None
        self._faulty: Optional[bool] = None
        self._consumers_to_start: str = "Daqmodes.INTEGRATED_CHANNEL_DATA"
        self._receiver_started: bool = False
        self._daq_id = str(daq_id).zfill(3)
        self._configuration = {}
        if receiver_interface:
            self._configuration["receiver_interface"] = receiver_interface
        if receiver_ip:
            self._configuration["receiver_ip"] = receiver_ip
        if receiver_ports:
            self._configuration["receiver_ports"] = receiver_ports
        self._received_data_callback = received_data_callback
        self._set_consumers_to_start(consumers_to_start)
        self._daq_client = DaqClient(daq_address)
        self._skuid_url = skuid_url
        self._daq_initialisation_retry_frequency = daq_initialisation_retry_frequency
        self._stop_establishing_communication = False

        super().__init__(
            logger,
            communication_state_callback,
            component_state_callback,
            power=None,
            fault=None,
        )
        self._task_executor = TaskExecutor(max_workers=2)

    def restart_daq_if_active(self) -> None:
        """Restart daq if consumers are active."""

        def stop_daq_completion_callback(
            input_data: str,
            status: TaskStatus | None = None,
            progress: int | None = None,
            result: JSONData = None,
            exception: Exception | None = None,
        ) -> None:
            """Update stop_daq command status.

            Executes start_daq command if stop_daq succeedes.

            :param input_data: input data for start_daq command
            :param status: the status of the asynchronous task
            :param progress: the progress of the asynchronous task
            :param result: the result of the completed asynchronous task
            :param exception: any exception caught in the running task
            """
            if status == TaskStatus.COMPLETED:
                self.logger.info("StopDaq command completed. Executing StartDaq.")
                self.start_daq(input_data, self.start_daq_completion_callback)
            else:
                self.logger.error(
                    "Execution of StopDaq is not complete. Current status is: %s",
                    [status, progress, result, exception],
                )

        def generate_input_data_from_daq_status(daq_status: dict[str, Any]) -> str:
            """Generate the input data for StartDaq command using DaqStatus.

            :param daq_status: Output of executing the DaqStatus command.

            :return: A string containing the modes to start for the DaqHandler.
            """
            running_consumers: list[list[str]] = daq_status["Running Consumers"]
            return ",".join([data[0] for data in running_consumers])

        try:
            self.logger.info("Checking for Daq status..")
            daq_status: dict[str, Any] = json.loads(self.daq_status())
            self.logger.info("DaqStatus check results - %s", daq_status)
            if len(daq_status["Running Consumers"]) != 0:
                # Input data for start_daq command
                input_data = generate_input_data_from_daq_status(daq_status)
                self._stop_daq(partial(stop_daq_completion_callback, input_data))
        except ConnectionError as connection_error:
            self.logger.exception(
                "Connection error while checking the status on Daq: %s",
                connection_error,
            )
        except Exception as exception:  # pylint: disable=broad-exception-caught  # XXX
            self.logger.exception(
                "Caught an exception while trying to restart bandpass monitoring: %s",
                exception,
            )

    def start_daq_completion_callback(
        self,
        status: TaskStatus | None = None,
        progress: int | None = None,
        result: JSONData = None,
        exception: Exception | None = None,
    ) -> None:
        """Update start_daq command status.

        Executes start_bandpass_monitor once start_daq is done.

        :param status: the status of the asynchronous task
        :param progress: the progress of the asynchronous task
        :param result: the result of the completed asynchronous task
        :param exception: any exception caught in the running task
        """
        if status == TaskStatus.COMPLETED:
            self.logger.info(
                "StartDaq command completed. Starting bandpass monitoring."
            )
            daq_status: dict[str, Any] = json.loads(self.daq_status())
            self.logger.info("DaqStatus check results - %s", daq_status)
            if daq_status["Bandpass Monitor"] is True:
                bandpass_monitor_thread = threading.Thread(
                    target=self.start_bandpass_monitor,
                    name="submit_task_for_bandpass_monitoring",
                    args=[json.dumps({"plot_directory": "/tmp"})],
                )
                bandpass_monitor_thread.start()
        else:
            self.logger.warning(
                "The TaskStatus for StartDaq command is not COMPLETED. "
                "The status information is: %s",
                [status, progress, result, exception],
            )

    def start_communicating(self: DaqComponentManager) -> None:
        """Establish communication with the DaqReceiver components."""
        if self.communication_state == CommunicationStatus.ESTABLISHED:
            return
        if self.communication_state == CommunicationStatus.DISABLED:
            self._update_communication_state(
                CommunicationStatus.NOT_ESTABLISHED
            )  # noqa: E501

        self._stop_establishing_communication = False
        configuration = json.dumps(self._configuration)
        threading.Thread(
            target=self.establish_communication, args=[configuration]
        ).start()

    def establish_communication(self, configuration: str) -> None:
        """Establish communication with the DaqReceiver components.

        :param configuration: Configuration string for daq initialisation
        """
        while not self._stop_establishing_communication:
            try:
                response = self._daq_client.initialise(configuration)
                self.logger.info(response["message"])
                self._update_communication_state(CommunicationStatus.ESTABLISHED)
                self.restart_daq_if_active()
                break
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error(
                    "Caught exception in start_communicating: %s. "
                    + "Retrying in %s secs",
                    e,
                    self._daq_initialisation_retry_frequency,
                )
                sleep(self._daq_initialisation_retry_frequency)

    def stop_communicating(self: DaqComponentManager) -> None:
        """Break off communication with the DaqReceiver components."""
        if self.communication_state == CommunicationStatus.DISABLED:
            return
        self._stop_establishing_communication = True
        self._update_communication_state(CommunicationStatus.DISABLED)
        self._update_component_state(power=None, fault=None)

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
        task_callback: TaskCallbackType | None = None,
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
        task_callback: TaskCallbackType | None,
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
        # Check data directory is in correct format, if not then reconfigure.
        # This delays the start call by a lot if SKUID isn't there.
        if not self._data_directory_format_adr55_compliant():
            config = {"directory": self._construct_adr55_filepath()}
            self.configure_daq(json.dumps(config))
            self.logger.info(
                "Data directory automatically reconfigured to: %s", config["directory"]
            )
        try:
            modes_to_start = modes_to_start or self._consumers_to_start
            for response in self._daq_client.start_daq(modes_to_start):
                if task_callback:
                    if "status" in response:
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
        task_callback: TaskCallbackType | None = None,
    ) -> tuple[TaskStatus, str]:
        """
        Stop data acquisition.

        :param task_callback: Update task state, defaults to None

        :return: a task status and response message
        """
        return self.submit_task(
            self._stop_daq,
            task_callback=task_callback,
        )

    @check_communicating
    def _stop_daq(
        self: DaqComponentManager,
        task_callback: TaskCallbackType | None = None,
        task_abort_event: Optional[threading.Event] = None,
    ) -> None:
        """
        Stop data acquisition.

        Stops the DAQ receiver and all running consumers.

        :param task_callback: Update task state, defaults to None
        :param task_abort_event: Check for abort, defaults to None
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

    @check_communicating
    def daq_status(
        self: DaqComponentManager,
        task_callback: TaskCallbackType | None = None,
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

    @check_communicating
    def start_bandpass_monitor(
        self: DaqComponentManager,
        argin: str,
        task_callback: TaskCallbackType | None = None,
    ) -> tuple[TaskStatus, str]:
        """
        Start monitoring antenna bandpasses.

        The MccsDaqReceiver will begin monitoring antenna bandpasses
            and producing plots of the spectra.

        :param argin: A json string with keywords
            - plot_directory
            Directory in which to store bandpass plots.
            - monitor_rms
            Whether or not to additionally produce RMS plots.
            Default: False.
            - auto_handle_daq
            Whether DAQ should be automatically reconfigured,
            started and stopped without user action if necessary.
            This set to False means we expect DAQ to already
            be properly configured and listening for traffic
            and DAQ will not be stopped when `StopBandpassMonitor`
            is called.
            Default: False.
            - cadence
            The time in seconds over which to average bandpass data.
            Default: 0 returns snapshots.
        :param task_callback: Update task state, defaults to None

        :return: a task status and response message
        """
        return self.submit_task(
            self._start_bandpass_monitor,
            args=[argin],
            task_callback=task_callback,
        )

    def _to_db(self: DaqComponentManager, data: np.ndarray) -> np.ndarray:
        np.seterr(divide="ignore")
        log_data = 10 * np.log10(data)
        log_data[np.isneginf(log_data)] = 0.0
        np.seterr(divide="warn")
        return log_data

    def _to_shape(
        self: DaqComponentManager, a: np.ndarray, shape: tuple[int, int]
    ) -> np.ndarray:
        y_, x_ = shape
        y, x = a.shape
        y_pad = y_ - y
        x_pad = x_ - x
        return np.pad(
            a,
            (
                (y_pad // 2, y_pad // 2 + y_pad % 2),
                (x_pad // 2, x_pad // 2 + x_pad % 2),
            ),
            mode="constant",
        )

    def _get_data_from_response(
        self: DaqComponentManager,
        response: dict[str, Any],
        data_to_extract: str,
        nof_channels: int,
    ) -> np.ndarray | None:
        extracted_data = None
        try:
            extracted_data = self._to_shape(
                self._to_db(np.array(json.loads(response[data_to_extract][0]))),
                (self.NOF_ANTS_PER_STATION, nof_channels),
            )  # .reshape((self.NOF_ANTS_PER_STATION, nof_channels))
        except ValueError as e:
            self.logger.error(f"Caught mismatch in {data_to_extract} shape: {e}")
        return extracted_data

    # pylint: disable = too-many-branches
    @check_communicating
    def _start_bandpass_monitor(
        self: DaqComponentManager,
        argin: str,
        task_callback: TaskCallbackType | None = None,
        task_abort_event: Optional[threading.Event] = None,
    ) -> None:
        """
        Start monitoring antenna bandpasses.

        The MccsDaqReceiver will begin monitoring antenna bandpasses
            and producing plots of the spectra.

        :param argin: A json string with keywords
            - plot_directory
            Directory in which to store bandpass plots.
            - monitor_rms
            Whether or not to additionally produce RMS plots.
            Default: False.
            - auto_handle_daq
            Whether DAQ should be automatically reconfigured,
            started and stopped without user action if necessary.
            This set to False means we expect DAQ to already
            be properly configured and listening for traffic
            and DAQ will not be stopped when `StopBandpassMonitor`
            is called.
            Default: False.
            - cadence
            The time in seconds over which to average bandpass data.
            Default: 0 returns snapshots.
        :param task_callback: Update task state, defaults to None
        :param task_abort_event: Check for abort, defaults to None
        """
        config = self.get_configuration()
        nof_channels = int(config["nof_channels"])

        if task_callback:
            task_callback(status=TaskStatus.QUEUED)
        try:
            for response in self._daq_client.start_bandpass_monitor(argin):
                x_bandpass_plot: np.ndarray | None = None
                y_bandpass_plot: np.ndarray | None = None
                rms_plot = None
                call_callback: bool = (
                    False  # Only call the callback if we have something to say.
                )
                if task_callback is not None:
                    task_callback(
                        status=TaskStatus(response["result_code"]),
                        result=response["message"],
                    )

                if "x_bandpass_plot" in response:
                    if response["x_bandpass_plot"] != [None]:
                        # Reconstruct the numpy array.
                        x_bandpass_plot = self._get_data_from_response(
                            response, "x_bandpass_plot", nof_channels
                        )
                        if x_bandpass_plot is not None:
                            call_callback = True

                if "y_bandpass_plot" in response:
                    if response["y_bandpass_plot"] != [None]:
                        # Reconstruct the numpy array.
                        y_bandpass_plot = self._get_data_from_response(
                            response, "y_bandpass_plot", nof_channels
                        )
                        if y_bandpass_plot is not None:
                            call_callback = True

                if "rms_plot" in response:
                    if response["rms_plot"] != [None]:
                        rms_plot = self._get_data_from_response(
                            response, "rms_plot", nof_channels
                        )
                        if rms_plot is not None:
                            call_callback = True

                if call_callback:
                    if self._component_state_callback is not None:
                        self._component_state_callback(
                            x_bandpass_plot=x_bandpass_plot,
                            y_bandpass_plot=y_bandpass_plot,
                            rms_plot=rms_plot,
                        )

        except Exception as e:  # pylint: disable=broad-exception-caught  # XXX
            self.logger.error("Caught exception in bandpass monitor: %s", e)
            if task_callback:
                task_callback(
                    status=TaskStatus.FAILED,
                    result=f"Exception: {e}",
                )
            return

    @check_communicating
    def stop_bandpass_monitor(
        self: DaqComponentManager,
        task_callback: TaskCallbackType | None = None,
    ) -> tuple[ResultCode, str]:
        """
        Stop monitoring antenna bandpasses.

        The MccsDaqReceiver will cease monitoring antenna bandpasses
            and producing plots of the spectra.

        :param task_callback: Update task state, defaults to None

        :return: a ResultCode and response message
        """
        return self._daq_client.stop_bandpass_monitor()

    def _data_directory_format_adr55_compliant(
        self: DaqComponentManager,
    ) -> bool:
        """
        Check the current data directory has ADR-55 format.

        Here we just check that the static parts of the filepath are
            present where expected.
            The eb_id and scan_id are not validated.

        :return: Whether the current directory is ADR-55 compliant.
        """
        current_directory = self.get_configuration()["directory"].split("/", maxsplit=5)
        # Reconstruct ADR-55 relevant part of the fp to match against.
        current_directory_root = "/".join(current_directory[0:5])
        return PurePath(current_directory_root).match(f"/product/*/{SUBSYSTEM_SLUG}/*")

    def _construct_adr55_filepath(
        self: DaqComponentManager,
        eb_id: Optional[str] = None,
        scan_id: Optional[str] = None,
    ) -> str:
        """
        Construct an ADR-55 compliant filepath.

        An ADR-55 compliant filepath for data logging is constructed
            from the existing DAQ data directory, retrieving or creating
            UIDs as necessary.

        :param eb_id: A pre-existing eb_id if available.
        :param scan_id: A pre-existing scan_id if available.

        :return: A data storage directory compliant with ADR-55.
        """
        if eb_id is None:
            eb_id = self._get_eb_id()
        if scan_id is None:
            scan_id = self._get_scan_id()
        existing_directory = self.get_configuration()["directory"]
        # Replace any double slashes with just one in case
        # `existing_directory` begins with one.
        return (
            f"/product/{eb_id}/{SUBSYSTEM_SLUG}/{scan_id}/{existing_directory}".replace(
                "//", "/"
            )
        )

    def _get_scan_id(self: DaqComponentManager) -> str:
        """
        Get a unique scan ID from SKUID.

        :return: A unique scan ID.
        """
        if self._skuid_url:
            try:
                skuid_client = SkuidClient(self._skuid_url)
                uid = skuid_client.fetch_scan_id()
                return uid
            except Exception as e:  # pylint: disable=broad-except
                # Usually when SKUID isn't available.
                self.logger.warn(
                    "Could not retrieve scan_id from SKUID: %s. "
                    "Using a locally produced scan_id.",
                    e,
                )
        random_seq = str(random.randint(1, 999999999999999)).rjust(15, "0")
        uid = f"scan-local-{random_seq}"
        return uid

    def _get_eb_id(self: DaqComponentManager) -> str:
        """
        Get a unique execution block ID from SKUID.

        :return: A unique execution block ID.
        """
        if self._skuid_url:
            try:
                skuid_client = SkuidClient(self._skuid_url)
                uid = skuid_client.fetch_skuid("eb")
                return uid
            except Exception as e:  # pylint: disable=broad-except
                # Usually when SKUID isn't available.
                self.logger.warn(
                    "Could not retrieve eb_id from SKUID: %s. "
                    "Using a locally produced eb_id.",
                    e,
                )
        random_seq = str(random.randint(1, 999999999)).rjust(9, "0")
        today = date.today().strftime("%Y%m%d")
        uid = f"eb-local-{today}-{random_seq}"
        return uid
