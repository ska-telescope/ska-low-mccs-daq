# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module implements component management for DaqReceivers."""
from __future__ import annotations

import datetime
import json
import logging
import os
import queue
import random
import re
import threading
from collections import deque
from datetime import date
from pathlib import PurePath
from time import perf_counter, sleep
from typing import Any, Callable, Final, Iterator, Optional, cast

import h5py
import kubernetes  # type: ignore
import numpy as np
import psutil  # type: ignore
from ska_control_model import CommunicationStatus, PowerState, ResultCode, TaskStatus
from ska_ser_skuid.client import SkuidClient  # type: ignore
from ska_tango_base.base import TaskCallbackType, check_communicating
from ska_tango_base.executor import TaskExecutor, TaskExecutorComponentManager

from ..pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from .daq_simulator import DaqSimulator

__all__ = ["DaqComponentManager"]
SUBSYSTEM_SLUG = "ska-low-mccs"

X_POL_INDEX = 0
Y_POL_INDEX = 1


def convert_daq_modes(consumers_to_start: str) -> list[DaqModes]:
    """
    Convert a string representation of DaqModes into a list of DaqModes.

    Breaks a comma separated list into a list of words,
        strips whitespace and extracts the `enum` part and casts the string
        into a DaqMode or directly cast an int into a DaqMode.

    :param consumers_to_start: A string containing a comma separated
        list of DaqModes.

    :return: a converted list of DaqModes or an empty list
        if no consumers supplied.
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


# pylint: disable=abstract-method,too-many-instance-attributes
class DaqComponentManager(TaskExecutorComponentManager):
    """A component manager for a DaqReceiver."""

    NOF_ANTS_PER_STATION: Final = 256

    TIME_FORMAT_STRING = "%d/%m/%y %H:%M:%S"

    CONFIG_DEFAULTS: dict[str, Any] = {
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
        "receiver_frame_size": 8500,
        "receiver_frames_per_block": 32,
        "receiver_nof_blocks": 256,
        "receiver_nof_threads": 1,
        "directory": ".",
        "logging": True,
        "write_to_disk": True,
        "station_config": None,
        "station_id": 0,
        "max_filesize": None,
        "acquisition_duration": -1,
        "acquisition_start_time": -1,
        "description": "",
        "observation_metadata": {},  # This is populated automatically
    }

    # pylint: disable=too-many-arguments
    def __init__(
        self: DaqComponentManager,
        daq_id: int,
        receiver_interface: str,
        receiver_ip: str,
        receiver_ports: str,
        consumers_to_start: str,
        nof_tiles: int,
        skuid_url: str,
        logger: logging.Logger,
        communication_state_callback: Callable[[CommunicationStatus], None],
        component_state_callback: Callable[..., None],
        received_data_callback: Callable[[str, str, str], None],
        dedicated_bandpass_daq: bool = False,
        simulation_mode: bool = False,
    ) -> None:
        """
        Initialise a new instance of DaqComponentManager.

        :param daq_id: The ID of this DaqReceiver.
        :param receiver_interface: The interface this DaqReceiver is to watch.
        :param receiver_ip: The IP address of this DaqReceiver.
        :param receiver_ports: The port this DaqReceiver is to watch.
        :param consumers_to_start: The default consumers to be started.
        :param nof_tiles: The number of tiles this DAQ will receive data from.
        :param skuid_url: The address at which a SKUID service is running.
        :param logger: the logger to be used by this object.
        :param communication_state_callback: callback to be
            called when the status of the communications channel between
            the component manager and its component changes
        :param component_state_callback: callback to be
            called when the component state changes
        :param received_data_callback: callback to be called when data is
            received from a tile
        :param dedicated_bandpass_daq: Flag indicating whether this DaqReceiver
            is dedicated exclusively to monitoring bandpasses. If true then
            this DaqReceiver will attempt to automatically monitor bandpasses.
        :param simulation_mode: whether or not to use a simulated backend.
        """
        self._external_ip_override = None
        if dedicated_bandpass_daq:
            self._external_ip_override = self.get_external_ip(logger)
        self._power_state_lock = threading.RLock()
        self._started_event = threading.Event()
        self._power_state: Optional[PowerState] = None
        self._faulty: Optional[bool] = None
        self._consumers_to_start: str = "Daqmodes.INTEGRATED_CHANNEL_DATA"
        self._receiver_started: bool = False
        self._daq_id = str(daq_id).zfill(3)
        self._dedicated_bandpass_daq = dedicated_bandpass_daq
        self._configuration: dict[str, Any] = {"nof_tiles": nof_tiles}
        if receiver_interface:
            self._configuration["receiver_interface"] = receiver_interface
        if receiver_ip:
            self._configuration["receiver_ip"] = receiver_ip
        if receiver_ports:
            self._configuration["receiver_ports"] = receiver_ports
        self._configuration |= self.CONFIG_DEFAULTS
        self._received_data_callback = received_data_callback
        self._set_consumers_to_start(consumers_to_start)
        self._daq_client: DaqReceiver | DaqSimulator
        self._simulation_mode = simulation_mode
        if simulation_mode:
            self._daq_client = DaqSimulator(**self._configuration)
        else:
            self._daq_client = DaqReceiver()
        logger.info(f"DAQ backend in simulation mode: {simulation_mode}")
        self._skuid_url = skuid_url
        self._measure_data_rate: bool = False
        self._data_rate: float | None = None

        self._monitoring_bandpass = False
        self.client_queue: queue.SimpleQueue[tuple[str, str, str] | None] | None = None
        self._y_bandpass_plots: deque[str] = deque(maxlen=1)
        self._x_bandpass_plots: deque[str] = deque(maxlen=1)

        self._data_mode_mapping: dict[str, DaqModes] = {
            "burst_raw": DaqModes.RAW_DATA,
            "cont_channel": DaqModes.CONTINUOUS_CHANNEL_DATA,
            "integrated_channel": DaqModes.INTEGRATED_CHANNEL_DATA,
            "burst_channel": DaqModes.CHANNEL_DATA,
            "burst_beam": DaqModes.BEAM_DATA,
            "integrated_beam": DaqModes.INTEGRATED_BEAM_DATA,
            "correlator": DaqModes.CORRELATOR_DATA,
            "station": DaqModes.STATION_BEAM_DATA,
            "antenna_buffer": DaqModes.ANTENNA_BUFFER,
        }

        super().__init__(
            logger,
            communication_state_callback,
            component_state_callback,
            power=None,
            fault=None,
        )
        # We've bumped this to 3 workers to allow for the bandpass monitoring.
        self._task_executor = TaskExecutor(max_workers=3)

    def get_external_ip(self, logger: logging.Logger) -> str:
        """
        Get the IP of the serivice which exposes this device.

        This is exceptionally ugly code, however we are not allowed initcontainers
        in ska-tango-util. Anyhow this should be deleted once SP-5187 is finished,
        then we don't need to use the 1G, so we don't need to attach a loadbalancer
        to the bandpass DAQ so we don't need to grab the IP of that loadbalancer here.

        :param logger: passing in the logger as we haven't yet run super().__init__().

        :return: the ip of the loadbalancer service.
        """
        kubernetes.config.load_incluster_config()
        core_v1_api = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient())
        server_hostname = os.getenv("TANGO_SERVER_PUBLISH_HOSTNAME")
        device_hostname = os.getenv("HOSTNAME")
        if not server_hostname or not device_hostname:
            logger.error("Couldn't get external IP automatically.")
            return ""
        namespace = server_hostname.split(".")[1]
        name = device_hostname.rsplit("-", 1)[0]
        svc = core_v1_api.read_namespaced_service(name=name, namespace=namespace)
        ip = svc.status.load_balancer.ingress[0].ip
        logger.info(f"Got external IP: {ip}")
        return ip

    def start_communicating(self: DaqComponentManager) -> None:
        """Establish communication with the DaqReceiver components."""
        if self.communication_state == CommunicationStatus.ESTABLISHED:
            return
        if self.communication_state == CommunicationStatus.DISABLED:
            self._update_communication_state(CommunicationStatus.NOT_ESTABLISHED)
        self.initialise(self._configuration)
        self._update_communication_state(CommunicationStatus.ESTABLISHED)
        if self._dedicated_bandpass_daq:
            self._get_bandpass_running()

    def initialise(
        self: DaqComponentManager, config: dict[str, Any]
    ) -> tuple[ResultCode, str]:  # noqa: E501
        """
        Initialise a new DaqReceiver instance.

        :param config: the configuration to apply

        :return: a resultcode, message tuple
        """
        merged_config = self._config | config
        self.logger.info("initialise() issued with: %s", merged_config)

        if self._initialised is False:
            self.logger.debug("Creating DaqReceiver instance.")
            if self._simulation_mode:
                self._daq_client = DaqSimulator()
            else:
                self._daq_client = DaqReceiver()
            try:
                self.logger.info(
                    "Configuring before initialising with: %s", self._config
                )
                self._daq_client.populate_configuration(merged_config)
                self._config = merged_config
                self.logger.info("Initialising daq.")
                self._daq_client.initialise_daq()
                self._receiver_started = True
                self._initialised = True
            # pylint: disable=broad-except
            except Exception as e:
                self.logger.error(
                    "Caught exception in `DaqHandler.initialise`: %s", e
                )  # noqa: E501
                return ResultCode.FAILED, f"Caught exception: {e}"
            self.logger.info("Daq initialised.")
            return ResultCode.OK, "Daq successfully initialised"

        # else
        self.logger.info("Daq already initialised")
        return ResultCode.REJECTED, "Daq already initialised"

    def _get_bandpass_running(self: DaqComponentManager) -> None:
        """
        Get the bandpass monitor running if it isn't already.

        This method is called when the monitoring thread detects that either
        the consumer has stopped or the bandpass monitor itself has stopped.
        It starts the INTEGRATED DATA consumer and starts the bandpass monitor with
        `auto_handle_daq=True`.
        This device-side handles starting the correct consumer, the daq-server side
        handles any reconfiguration.
        """

        def _wait_for_status(status: str, value: str) -> None:
            """
            Wait for Daq to achieve a certain status.

            Intended as a helper to wait for a consumer or bandpass monitor to start.
            Linear increase to retry time.

            :param status: The Daq status category to check.
            :param value: The expected value of the status.
            """
            daq_status = str(self.get_status()[status])
            retry_count = 0
            while value not in daq_status:
                retry_count += 1
                sleep(retry_count)
                daq_status = str(self.get_status()[status])
                if retry_count > 5:
                    self.logger.error(
                        f"Failed to find {value} in DaqStatus[{status}]: {daq_status=}."
                    )
                    return
            self.logger.debug(f"Found {value} in DaqStatus[{status}]: {daq_status=}.")

        if not self._is_integrated_channel_consumer_running():
            # start consumer
            self.logger.info(
                "Auto starting INTEGRATED DATA consumer for bandpass monitoring."
            )
            self.start_daq(modes_to_start="INTEGRATED_CHANNEL_DATA")
            _wait_for_status(
                status="Running Consumers", value=str(["INTEGRATED_CHANNEL_DATA", 5])
            )

        if not self._is_bandpass_monitor_running():
            bandpass_args = json.dumps(
                {
                    "plot_directory": self.get_configuration()["directory"],
                    "auto_handle_daq": True,
                }
            )
            self.logger.info(
                "Auto starting bandpass monitor with args: %s.", bandpass_args
            )
            self.start_bandpass_monitor(bandpass_args)
            _wait_for_status(status="Bandpass Monitor", value="True")

    def _is_integrated_channel_consumer_running(
        self: DaqComponentManager, status: dict[str, Any] | None = None
    ) -> bool:
        """
        Check if the INTEGRATED_CHANNEL_DATA consumer is running.

        :param status: An optional status dictionary to check.

        :return: True if the consumer is running, False otherwise.
        """
        if status is not None:
            return bool(
                str(["INTEGRATED_CHANNEL_DATA", 5])
                in str(status.get("Running Consumers"))
            )
        return bool(
            str(["INTEGRATED_CHANNEL_DATA", 5])
            in str(self.get_status().get("Running Consumers"))
        )

    def _is_bandpass_monitor_running(
        self: DaqComponentManager, status: dict[str, Any] | None = None
    ) -> bool:
        """
        Check if the bandpass monitor is running.

        :param status: An optional status dictionary to check.

        :return: True if the bandpass monitor is running, False otherwise.
        """
        if status is not None:
            return bool(status.get("Bandpass Monitor"))
        return bool(self.get_status().get("Bandpass Monitor"))

    def stop_communicating(self: DaqComponentManager) -> None:
        """Break off communication with the DaqReceiver components."""
        if self.communication_state == CommunicationStatus.DISABLED:
            return
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
        config: str,
    ) -> tuple[ResultCode, str]:
        """
        Apply a configuration to the DaqReceiver.

        :param config: A json containing configuration settings.

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        daq_config = json.loads(config)
        self.logger.info("Configuring daq with: %s", daq_config)
        try:
            if not daq_config:
                self.logger.error(
                    "Daq was not reconfigured, no config data supplied."
                )  # noqa: E501
                return ResultCode.REJECTED, "No configuration data supplied."

            if "directory" in daq_config:
                if not os.path.exists(daq_config["directory"]):
                    # Note: The daq-handler does not have permission
                    # to create a root directory
                    # This will be set up by container infrastructure.
                    self.logger.info(
                        f'directory {daq_config["directory"]} does not exist, Creating.'
                    )
                    os.makedirs(daq_config["directory"])
                    self.logger.info(f'directory {daq_config["directory"]} created!')
            merged_config = self._config | daq_config
            self._daq_client.populate_configuration(merged_config)
            self._config = merged_config
            self.logger.info("Daq successfully reconfigured.")
            return ResultCode.OK, "Daq reconfigured"

        # pylint: disable=broad-except
        except Exception as e:
            self.logger.error(f"Caught exception in DaqHandler.configure: {e}")
            return ResultCode.FAILED, f"Caught exception: {e}"

    # Callback called for every data mode.
    def _file_dump_callback(  # noqa: C901
        self: DaqComponentManager,
        data_mode: str,
        file_name: str,
        additional_info: Optional[str] = None,
    ) -> None:
        """
        Call a callback for specific data mode.

        Callbacks for all or specific data modes should be called here.

        :param data_mode: The DAQ data type written
        :param file_name: The filename written
        :param additional_info: Any additional information/metadata.
        """
        # Callbacks to call for all data modes.
        daq_mode = self._data_mode_mapping[data_mode]
        if daq_mode not in {DaqModes.STATION_BEAM_DATA, DaqModes.CORRELATOR_DATA}:
            metadata = self._daq_client._persisters[daq_mode].get_metadata(
                tile_id=additional_info
            )
        else:
            metadata = self._daq_client._persisters[daq_mode].get_metadata()
        if additional_info is not None and metadata is not None:
            metadata["additional_info"] = additional_info

        if self._monitoring_bandpass:
            self.generate_bandpass_plots(file_name)

        self._received_data_callback(
            file_name,
            data_mode,
            json.dumps(metadata),
        )

        # Call additional callbacks per data mode if needed.
        if data_mode == "read_raw_data":
            pass

        if data_mode == "read_beam_data":
            pass

        if data_mode == "integrated_beam":
            pass

        if data_mode == "station_beam":
            pass

        if data_mode == "read_channel_data":
            pass

        if data_mode == "continuous_channel":
            pass

        if data_mode == "integrated_channel":
            pass

        if data_mode == "correlator":
            pass

    def start_daq(
        self: DaqComponentManager,
        modes_to_start: str,
    ) -> tuple[ResultCode, str]:
        """
        Start data acquisition with the current configuration.

        A infinite streaming loop will be started until told to stop.
        This will notify the client of state changes and metadata
        of files written to disk, e.g. `data_type`.`file_name`.

        :param modes_to_start: string listing the modes to start.

        :returns: a result code and message.

        :raises ValueError: if an invalid DaqMode is supplied
        """
        # Check data directory is in correct format, if not then reconfigure.
        # This delays the start call by a lot if SKUID isn't there.
        if not self._data_directory_format_adr55_compliant():
            config = {"directory": self._construct_adr55_filepath()}
            self.configure_daq(json.dumps(config))
            self.logger.info(
                "Data directory automatically reconfigured to: %s", config["directory"]
            )
        try:
            # Convert string representation to DaqModes
            converted_modes_to_start: list[DaqModes] = convert_daq_modes(
                modes_to_start
            )  # noqa: E501
        except ValueError as e:
            self.logger.error("Value Error! Invalid DaqMode supplied! %s", e)
            raise

        self.client_queue = queue.SimpleQueue()
        callbacks = [self._file_dump_callback] * len(converted_modes_to_start)
        self._daq_client.start_daq(converted_modes_to_start, callbacks)
        self.logger.info("Daq listening......")

        return (ResultCode.OK, f"DAQ started for {modes_to_start}")

    @check_communicating
    def stop_daq(
        self: DaqComponentManager,
        task_callback: TaskCallbackType | None = None,
    ) -> tuple[ResultCode, str]:
        """
        Stop data acquisition.

        :param task_callback: Update task state, defaults to None

        :return: a task status and response message
        """
        self.logger.info("Stopping daq.....")
        self._daq_client.stop_daq()
        self._receiver_started = False
        if self.client_queue:
            self.client_queue.put(None)
        return ResultCode.OK, "Daq stopped"

    @check_communicating
    def get_status(self: DaqComponentManager) -> dict[str, Any]:
        """
        Provide status information for this MccsDaqReceiver.

        This method returns status as a json string with entries for:
            - Running Consumers: [DaqMode.name: str, DaqMode.value: int]
            - Receiver Interface: "Interface Name": str
            - Receiver Ports: [Port_List]: list[int]
            - Receiver IP: "IP_Address": str
            - Bandpass Monitor: "Monitoring Status": bool

        :return: A json string containing the status of this DaqReceiver.
        """
        # 2. Get consumer list, filter by `running`
        full_consumer_list = self._daq_client._running_consumers.items()
        running_consumer_list = [
            [consumer.name, consumer.value]
            for consumer, running in full_consumer_list
            if running
        ]
        # 3. Get Receiver Interface, Ports and IP (and later `Uptime`)
        receiver_interface = self._daq_client._config["receiver_interface"]
        receiver_ports = self._daq_client._config["receiver_ports"]
        receiver_ip = (
            self._external_ip_override or self._daq_client._config["receiver_ip"]
        )
        # 4. Compose into some format and return.
        return {
            "Running Consumers": running_consumer_list,
            "Receiver Interface": receiver_interface,
            "Receiver Ports": receiver_ports,
            "Receiver IP": [
                (
                    receiver_ip.decode()
                    if isinstance(receiver_ip, bytes)
                    else receiver_ip
                )  # noqa: E501
            ],
            "Bandpass Monitor": self._monitoring_bandpass,
        }

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
        data: str,
        nof_channels: int,
    ) -> np.ndarray | None:
        extracted_data = None
        try:
            extracted_data = self._to_shape(
                self._to_db(np.array(json.loads(data))),
                (self.NOF_ANTS_PER_STATION, nof_channels),
            )  # .reshape((self.NOF_ANTS_PER_STATION, nof_channels))
        except ValueError as e:
            self.logger.error(f"Caught mismatch in {data} shape: {e}")
        return extracted_data

    @check_communicating
    def _start_bandpass_monitor(  # noqa: C901
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

        try:
            for response in self.monitor_bandpasses(argin):
                x_bandpass_plot: np.ndarray | None = None
                y_bandpass_plot: np.ndarray | None = None
                rms_plot = None
                call_callback: bool = (
                    False  # Only call the callback if we have something to say.
                )
                if task_callback is not None:
                    task_callback(
                        result=response[1],
                    )

                if response[2] is not None:
                    # Reconstruct the numpy array.
                    x_bandpass_plot = self._get_data_from_response(
                        response[2], nof_channels
                    )
                    if x_bandpass_plot is not None:
                        call_callback = True

                if response[3] is not None:
                    # Reconstruct the numpy array.
                    y_bandpass_plot = self._get_data_from_response(
                        response[3], nof_channels
                    )
                    if y_bandpass_plot is not None:
                        call_callback = True

                if response[4] is not None:
                    rms_plot = self._get_data_from_response(response[4], nof_channels)
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

    def monitor_bandpasses(  # noqa: C901
        self: DaqComponentManager,
        argin: str,
    ) -> Iterator[tuple[TaskStatus, str, str | None, str | None, str | None]]:
        """
        Begin monitoring antenna bandpasses.

        :param argin: A dict of arguments to pass to `start_bandpass_monitor` command.

            * plot_directory: Plotting directory.
                Mandatory.

            * monitor_rms: Flag to enable or disable RMS monitoring.
                Optional. Default False.
                [DEPRECATED - To be removed.]

            * auto_handle_daq: Flag to indicate whether the DaqReceiver should
                be automatically reconfigured, started and stopped during this
                process if necessary.
                Optional. Default False.
                [DEPRECATED - To be removed.]

            * cadence: Number of seconds over which to average data.
                Optional. Default 0 (returns snapshots).

        :yields: Taskstatus, Message, bandpass/rms plot(s).
        :returns: TaskStatus, Message, None, None, None
        """
        if self._monitoring_bandpass and self._plot_transmission:
            yield (
                TaskStatus.REJECTED,
                "Bandpass monitor is already active.",
                None,
                None,
                None,
            )
            return
        self._stop_bandpass = False
        params: dict[str, Any] = json.loads(argin)
        try:
            plot_directory: str = params["plot_directory"]
        except KeyError:
            self.logger.error("Param `argin` must have key for `plot_directory`")
            yield (
                TaskStatus.REJECTED,
                "Param `argin` must have key for `plot_directory`",
                None,
                None,
                None,
            )
            return
        # monitor_rms: bool = cast(bool, params.get("monitor_rms", False))
        cadence = cast(int, params.get("cadence", 0))
        auto_handle_daq = params.get("auto_handle_daq", False)
        # Convert to bool if we have a string.
        if not isinstance(auto_handle_daq, bool):
            # pylint: disable = simplifiable-if-statement
            if auto_handle_daq == "True":
                auto_handle_daq = True
            else:
                auto_handle_daq = False

        # Check DAQ is in the correct state for monitoring bandpasses.
        # If not, throw an error if we chose not to auto_handle_daq
        # otherwise configure appropriately.
        current_config = self.get_configuration()
        if current_config["append_integrated"]:
            if not auto_handle_daq:
                self.logger.error(
                    "Current DAQ config is invalid. "
                    "The `append_integrated` option must be set to false "
                    "for bandpass monitoring."
                )
                yield (
                    TaskStatus.REJECTED,
                    "Current DAQ config is invalid. "
                    "The `append_integrated` option must be set to false "
                    "for bandpass monitoring.",
                    None,
                    None,
                    None,
                )
                return
            self._daq_client.configure({"append_integrated": False})

        # Check correct consumer is running.
        running_consumers = self.get_status().get("Running Consumers", "")

        if ["INTEGRATED_CHANNEL_DATA", 5] not in running_consumers:
            if not auto_handle_daq:
                self.logger.error(
                    "INTEGRATED_CHANNEL_DATA consumer must be running "
                    "before bandpasses can be monitored."
                    "Running consumers: %s",
                    running_consumers,
                )
                yield (
                    TaskStatus.REJECTED,
                    "INTEGRATED_CHANNEL_DATA consumer must be running "
                    "before bandpasses can be monitored.",
                    None,
                    None,
                    None,
                )
                return
            # Auto start DAQ.
            # TODO: Need to be able to start consumers incrementally for this.
            # result = self.start(modes_to_start="INTEGRATED_CHANNEL_DATA")
            # while "INTEGRATED_CHANNEL_DATA" not in running_consumers:
            self.logger.error(
                "Unable to create plotting directory at %s", plot_directory
            )
            yield (
                TaskStatus.FAILED,
                f"Unable to create plotting directory at: {plot_directory}",
                None,
                None,
                None,
            )
            return

        data_directory = self._daq_client._config["directory"]
        self.logger.info("Using data dir %s", data_directory)

        # # Start rms thread
        # if monitor_rms:
        #     self.logger.debug("Starting RMS plotting thread.")
        #     rms = Process(
        #         target=self.generate_rms_plots,
        #         name=f"rms-plotter({self})",
        #         args=(station_name, os.path.join(plot_directory, station_name)),
        #     )
        #     rms.start()

        if not self._monitoring_bandpass:
            # Start plotting thread
            self.logger.debug("Starting bandpass plotting thread")
            bandpass_plotting_thread = threading.Thread(
                target=self.generate_bandpass_plots,
                args=(
                    os.path.join(plot_directory, self._station_name),
                    self._station_name,
                    cadence,
                ),
            )
            bandpass_plotting_thread.start()
        # Wait for stop, monitoring disk space in the meantime
        max_dir_size = 1000 * 1024 * 1024

        self.logger.info("Bandpass monitor active, entering wait loop.")
        self.logger.info(
            "Params: plot_directory: %s, auto_handle_daq: %s, cadence: %i",
            plot_directory,
            auto_handle_daq,
            cadence,
        )
        self._monitoring_bandpass = True

        yield (
            TaskStatus.IN_PROGRESS,
            "Bandpass monitor active",
            None,
            None,
            None,
        )

        try:
            while not self._stop_bandpass:
                self._plot_transmission = True
                try:
                    dir_size = sum(
                        os.path.getsize(f)
                        for f in os.listdir(data_directory)
                        if os.path.isfile(f)
                    )
                except FileNotFoundError as e:
                    self.logger.warning("Could not find file: %s", e)
                if dir_size > max_dir_size:
                    self.logger.error(
                        "Consuming too much disk space! Stopping bandpass monitor! "
                        "%i/%i",
                        dir_size,
                        max_dir_size,
                    )
                    self._stop_bandpass = True
                    break

                try:
                    x_bandpass_plot = self._x_bandpass_plots.pop()
                except IndexError:
                    x_bandpass_plot = None
                except Exception as e:  # pylint: disable = broad-exception-caught
                    self.logger.error(
                        "Unexpected exception retrieving x_bandpass_plot: %s",
                        e,
                    )

                try:
                    y_bandpass_plot = self._y_bandpass_plots.pop()
                except IndexError:
                    y_bandpass_plot = None
                except Exception as e:  # pylint: disable = broad-exception-caught
                    self.logger.error(
                        "Unexpected exception retrieving y_bandpass_plot: %s",
                        e,
                    )

                try:
                    rms_plot = self._rms_plots.pop()
                except IndexError:
                    rms_plot = None
                except Exception as e:  # pylint: disable = broad-exception-caught
                    self.logger.error("Unexpected exception retrieving rms_plot: %s", e)

                if all(
                    plot is None
                    for plot in [x_bandpass_plot, y_bandpass_plot, rms_plot]
                ):
                    # If we don't have any plots, don't uselessly spam [None]s.
                    pass
                else:
                    self.logger.debug("Transmitting bandpass data.")
                    yield (
                        TaskStatus.IN_PROGRESS,
                        "plot sent",
                        x_bandpass_plot,
                        y_bandpass_plot,
                        rms_plot,
                    )
                    self.logger.debug("Bandpass data transmitted.")
                sleep(1)  # Plots will never be sent more often than once per second.

            # Stop and clean up
            self.logger.info("Waiting for threads and processes to terminate.")
            # TODO: Need to be able to stop consumers incrementally for this.
            # if auto_handle_daq:
            #     self.stop()
            bandpass_plotting_thread.join()
            # if monitor_rms:
            #     rms.join()
            self._monitoring_bandpass = False
            self._plot_transmission = False

            self.logger.info("Bandpass monitoring complete.")
            yield (
                TaskStatus.COMPLETED,
                "Bandpass monitoring complete.",
                None,
                None,
                None,
            )
        finally:
            self._plot_transmission = False
            self.logger.info(
                "Bandpass monitoring thread terminated. The Bandpass plots "
                "will continue to generate but will not be transmitted."
            )
        # Create plotting directory structure
        if not self.create_plotting_directory(plot_directory, self._station_name):
            self.logger.error(
                "Unable to create plotting directory at %s", plot_directory
            )
            yield (
                TaskStatus.FAILED,
                f"Unable to create plotting directory at: {plot_directory}",
                None,
                None,
                None,
            )
            return

        data_directory = self._daq_client._config["directory"]
        self.logger.info("Using data dir %s", data_directory)

        # # Start rms thread
        # if monitor_rms:
        #     self.logger.debug("Starting RMS plotting thread.")
        #     rms = Process(
        #         target=self.generate_rms_plots,
        #         name=f"rms-plotter({self})",
        #         args=(station_name, os.path.join(plot_directory, station_name)),
        #     )
        #     rms.start()

        if not self._monitoring_bandpass:
            # Start plotting thread
            self.logger.debug("Starting bandpass plotting thread")
            bandpass_plotting_thread = threading.Thread(
                target=self.generate_bandpass_plots,
                args=(
                    os.path.join(plot_directory, self._station_name),
                    self._station_name,
                    cadence,
                ),
            )
            bandpass_plotting_thread.start()
        # Wait for stop, monitoring disk space in the meantime
        max_dir_size = 1000 * 1024 * 1024

        self.logger.info("Bandpass monitor active, entering wait loop.")
        self.logger.info(
            "Params: plot_directory: %s, auto_handle_daq: %s, cadence: %i",
            plot_directory,
            auto_handle_daq,
            cadence,
        )
        self._monitoring_bandpass = True

        yield (
            TaskStatus.IN_PROGRESS,
            "Bandpass monitor active",
            None,
            None,
            None,
        )

        try:
            while not self._stop_bandpass:
                self._plot_transmission = True
                try:
                    dir_size = sum(
                        os.path.getsize(f)
                        for f in os.listdir(data_directory)
                        if os.path.isfile(f)
                    )
                except FileNotFoundError as e:
                    self.logger.warning("Could not find file: %s", e)
                if dir_size > max_dir_size:
                    self.logger.error(
                        "Consuming too much disk space! Stopping bandpass monitor! "
                        "%i/%i",
                        dir_size,
                        max_dir_size,
                    )
                    self._stop_bandpass = True
                    break

                try:
                    x_bandpass_plot = self._x_bandpass_plots.pop()
                except IndexError:
                    x_bandpass_plot = None
                except Exception as e:  # pylint: disable = broad-exception-caught
                    self.logger.error(
                        "Unexpected exception retrieving x_bandpass_plot: %s",
                        e,
                    )

                try:
                    y_bandpass_plot = self._y_bandpass_plots.pop()
                except IndexError:
                    y_bandpass_plot = None
                except Exception as e:  # pylint: disable = broad-exception-caught
                    self.logger.error(
                        "Unexpected exception retrieving y_bandpass_plot: %s",
                        e,
                    )

                try:
                    rms_plot = self._rms_plots.pop()
                except IndexError:
                    rms_plot = None
                except Exception as e:  # pylint: disable = broad-exception-caught
                    self.logger.error("Unexpected exception retrieving rms_plot: %s", e)

                if all(
                    plot is None
                    for plot in [x_bandpass_plot, y_bandpass_plot, rms_plot]
                ):
                    # If we don't have any plots, don't uselessly spam [None]s.
                    pass
                else:
                    self.logger.debug("Transmitting bandpass data.")
                    yield (
                        TaskStatus.IN_PROGRESS,
                        "plot sent",
                        x_bandpass_plot,
                        y_bandpass_plot,
                        rms_plot,
                    )
                    self.logger.debug("Bandpass data transmitted.")
                sleep(1)  # Plots will never be sent more often than once per second.

            # Stop and clean up
            self.logger.info("Waiting for threads and processes to terminate.")
            # TODO: Need to be able to stop consumers incrementally for this.
            # if auto_handle_daq:
            #     self.stop()
            bandpass_plotting_thread.join()
            # if monitor_rms:
            #     rms.join()
            self._monitoring_bandpass = False
            self._plot_transmission = False

            self.logger.info("Bandpass monitoring complete.")
            yield (
                TaskStatus.COMPLETED,
                "Bandpass monitoring complete.",
                None,
                None,
                None,
            )
        finally:
            self._plot_transmission = False
            self.logger.info(
                "Bandpass monitoring thread terminated. The Bandpass plots "
                "will continue to generate but will not be transmitted."
            )

    # pylint: disable = too-many-locals
    def generate_bandpass_plots(  # noqa: C901
        self: DaqComponentManager, filepath: str
    ) -> None:
        """
        Generate antenna bandpass plots.

        :param filepath: the location of the data file for bandpass plots.
        """
        config = self.get_configuration()
        nof_channels = int(config["nof_channels"])
        nof_antennas_per_tile = int(config["nof_antennas"])
        nof_pols = int(config["nof_polarisations"])
        nof_tiles = int(config["nof_tiles"])

        x_pol_data: np.ndarray | None = None
        x_pol_data_count: int = 0
        y_pol_data: np.ndarray | None = None
        y_pol_data_count: int = 0
        # The shape is reversed as DAQ reads the data this way around.
        full_station_data: np.ndarray = np.zeros(shape=(512, 256, 2), dtype=int)
        files_received_per_tile: list[int] = [0] * nof_tiles
        interval_start = None

        _filename_expression = re.compile(
            r"channel_integ_(?P<tile>\d+)_(?P<timestamp>\d+_\d+)_0.hdf5"
        )

        self.logger.debug("Processing %s", filepath)

        # Extract Tile number
        filename = os.path.basename(os.path.abspath(filepath))
        parts = _filename_expression.match(filename)

        if parts is not None:
            tile_number = int(parts.groupdict()["tile"])
        if tile_number is not None:
            try:
                files_received_per_tile[tile_number] += 1
            except IndexError as e:
                self.logger.error(
                    f"Caught exception: {e}. "
                    f"Tile {tile_number} out of bounds! "
                    f"Max tile number: {len(files_received_per_tile)}"
                )

        # Open newly create HDF5 file
        with h5py.File(filepath, "r") as f:
            # Data is in channels/antennas/pols order
            try:
                data: np.ndarray = f["chan_"]["data"][:]
            # pylint: disable=broad-exception-caught
            except Exception as e:
                self.logger.error("Exception: %s", e)
                return
            try:
                data = data.reshape((nof_channels, nof_antennas_per_tile, nof_pols))
            except ValueError as ve:
                self.logger.error("ValueError caught reshaping data, skipping: %s", ve)
                return

        # Append Tile data to full station set.
        # full_station_data is made of blocks of data per TPM in TPM order.
        # Each block of TPM data is in port order.
        start_index = nof_antennas_per_tile * tile_number
        full_station_data[
            :, start_index : start_index + nof_antennas_per_tile, :
        ] = data

        present = datetime.datetime.now()
        if interval_start is None:
            interval_start = present

        # TODO: This block is currently useless. Get averaging back in.
        # Loop over polarisations (separate plots)
        for pol in range(nof_pols):
            # Assign first data point or maintain sum of all data.
            # Divide by _pol_data_count to calculate the moving average on-demand.
            if pol == X_POL_INDEX:
                if x_pol_data is None:
                    x_pol_data_count = 1
                    x_pol_data = full_station_data[:, :, pol]
                else:
                    x_pol_data_count += 1
                    x_pol_data = x_pol_data + full_station_data[:, :, pol]
            elif pol == Y_POL_INDEX:
                if y_pol_data is None:
                    y_pol_data_count = 1
                    y_pol_data = full_station_data[:, :, pol]
                else:
                    y_pol_data_count += 1
                    y_pol_data = y_pol_data + full_station_data[:, :, pol]

        # Delete read file.
        os.unlink(filepath)
        # to the queue to be sent to the Tango device,
        # Assert that we've received the same number (1+) of files per tile.
        if all(files_received_per_tile) and (len(set(files_received_per_tile)) == 1):
            self.logger.debug("Queueing data for transmission")
            assert isinstance(full_station_data, np.ndarray)
            x_data = full_station_data[:, :, X_POL_INDEX].transpose()
            # Averaged x data (commented out for now)
            # x_data = x_pol_data.transpose() / x_pol_data_count
            self._x_bandpass_plots.append(json.dumps(x_data.tolist()))
            y_data = full_station_data[:, :, Y_POL_INDEX].transpose()
            # Averaged y data (commented out for now)
            # y_data = y_pol_data.transpose() / y_pol_data_count
            self._y_bandpass_plots.append(json.dumps(y_data.tolist()))
            self.logger.debug("Data queued for transmission.")

            # Reset vars
            x_pol_data = None
            x_pol_data_count = 0
            y_pol_data = None
            y_pol_data_count = 0
            interval_start = None
            files_received_per_tile = [0] * nof_tiles

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
        if not self._monitoring_bandpass:
            self.logger.info("Cannot stop bandpass monitor before it has started.")
            return (ResultCode.REJECTED, "Bandpass monitor not yet started.")
        if self._stop_bandpass:
            self.logger.info("Bandpass monitor already stopping.")
            return (ResultCode.REJECTED, "Bandpass monitor already stopping.")
        self._stop_bandpass = True
        self.logger.info("Bandpass monitor stopping.")
        return (ResultCode.OK, "Bandpass monitor stopping.")

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
                self.logger.warning(
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
                self.logger.warning(
                    "Could not retrieve eb_id from SKUID: %s. "
                    "Using a locally produced eb_id.",
                    e,
                )
        random_seq = str(random.randint(1, 999999999)).rjust(9, "0")
        today = date.today().strftime("%Y%m%d")
        uid = f"eb-local-{today}-{random_seq}"
        return uid

    @check_communicating
    def start_data_rate_monitor(
        self: DaqComponentManager,
        interval: float = 2.0,
        task_callback: TaskCallbackType | None = None,
    ) -> tuple[ResultCode, str]:
        """
        Start the data rate monitor on the receiver interface.

        :param interval: The interval in seconds at which to monitor the data rate.
        :param task_callback: Update task state, defaults to None.

        :return: a result code and response message
        """
        if self._measure_data_rate:
            return (ResultCode.REJECTED, "Already measuring data rate.")

        self._measure_data_rate = True

        def _measure_data_rate(interval: int) -> None:
            self.logger.info("Starting data rate monitor.")
            while self._measure_data_rate:
                self.logger.debug("Measuring data rate...")
                net = psutil.net_io_counters(pernic=True)
                t1_sent_bytes = net[
                    self._configuration["receiver_interface"]
                ].bytes_recv
                t1 = perf_counter()

                sleep(interval)

                net = psutil.net_io_counters(pernic=True)
                t2_sent_bytes = net[
                    self._configuration["receiver_interface"]
                ].bytes_recv
                t2 = perf_counter()
                nbytes = t2_sent_bytes - t1_sent_bytes
                data_rate = nbytes / (t2 - t1)
                self._data_rate = data_rate / 1024**3  # Gb/s
            self._data_rate = None

        data_rate_thread = threading.Thread(target=_measure_data_rate, args=[interval])
        data_rate_thread.start()
        return (ResultCode.OK, "Data rate measurement started.")

    def stop_data_rate_monitor(
        self: DaqComponentManager,
        task_callback: TaskCallbackType | None = None,
    ) -> tuple[ResultCode, str]:
        """
        Start the data rate monitor on the receiver interface.

        :param task_callback: Update task state, defaults to None.

        :return: a result code and response message
        """
        self._measure_data_rate = False
        return (ResultCode.OK, "Data rate measurement stopping.")

    @property
    @check_communicating
    def data_rate(self: DaqComponentManager) -> float | None:
        """
        Return the current data rate in Gb/s, or None if not being monitored.

        :return: the current data rate in Gb/s, or None if not being monitored.
        """
        return self._data_rate
