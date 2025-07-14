# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
# pylint: disable=too-many-lines
"""This module implements component management for DaqReceivers."""
from __future__ import annotations

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
from typing import Any, Callable, Final, Optional

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


class NumpyEncoder(json.JSONEncoder):
    """Converts numpy types to JSON."""

    # pylint: disable=arguments-renamed
    def default(self: NumpyEncoder, obj: Any) -> Any:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


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
        self._initialised = False
        self._daq_id = str(daq_id).zfill(3)
        self._dedicated_bandpass_daq = dedicated_bandpass_daq
        self._configuration: dict[str, Any] = {"nof_tiles": nof_tiles}
        self._nof_tiles = nof_tiles
        if receiver_interface:
            self._configuration["receiver_interface"] = receiver_interface
        if receiver_ip:
            self._configuration["receiver_ip"] = receiver_ip
        if receiver_ports:
            self._configuration["receiver_ports"] = receiver_ports
        self._configuration = self.CONFIG_DEFAULTS | self._configuration
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
        self._full_station_data: np.ndarray = np.zeros(shape=(512, 256, 2), dtype=float)
        self._files_received_per_tile: list[int] = [0] * nof_tiles
        self._event_queue: queue.Queue[tuple[str, float]] = queue.Queue()
        threading.Thread(target=self._event_loop, name="EventLoop").start()

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
        self.start_data_rate_monitor(1)

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
        try:
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
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                "Failed to retrieve loadbalancer IP, "
                f"likely there is no loadbalancer service: {e}"
            )
            return ""

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
        merged_config = self._configuration | config
        self.logger.info("initialise() issued with: %s", merged_config)

        if self._initialised is False:
            self.logger.debug("Creating DaqReceiver instance.")
            if self._simulation_mode:
                self._daq_client = DaqSimulator(**self._configuration)
            else:
                self._daq_client = DaqReceiver()
            try:
                self.logger.info(
                    "Configuring before initialising with: %s", self._configuration
                )
                self._daq_client.populate_configuration(merged_config)
                self._configuration = merged_config
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
            self.logger.info("Auto starting bandpass monitor.")
            self.configure_daq(
                **{"append_integrated": False, "nof_tiles": self._nof_tiles}
            )
            self.start_bandpass_monitor()
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
        **daq_config: Any,
    ) -> tuple[ResultCode, str]:
        """
        Apply a configuration to the DaqReceiver.

        :param daq_config: Validated kwargs containing configuration settings.

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
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
            merged_config = self._configuration | daq_config
            self._daq_client.populate_configuration(merged_config)
            self._configuration = merged_config
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
        **attributes: float,
    ) -> None:
        """
        Call a callback for specific data mode.

        Callbacks for all or specific data modes should be called here.

        :param data_mode: The DAQ data type written
        :param file_name: The filename written
        :param additional_info: Any additional information/metadata.
        :param attributes: any attributes to update the value for.
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

        self._received_data_callback(
            file_name,
            data_mode,
            json.dumps(metadata, cls=NumpyEncoder),
        )

        for attribute_name, attribute_value in attributes.items():
            self._attribute_callback(attribute_name, attribute_value)

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

        if data_mode == "integrated_channel" and self._monitoring_bandpass:
            self.generate_bandpass_plots(file_name)

        if data_mode == "correlator":
            pass

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
        if self._started_event.is_set():
            if task_callback:
                task_callback(
                    status=TaskStatus.REJECTED,
                    result=(
                        ResultCode.REJECTED,
                        "DAQ already started, call Stop() first.",
                    ),
                )
            return TaskStatus.REJECTED, "DAQ already started, call Stop() first."
        self._started_event.set()
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
        Start DAQ.

        :param modes_to_start: A comma separated string of daq modes.
        :param task_callback: Update task state, defaults to None
        :param task_abort_event: Check for abort, defaults to None

        :raises ValueError: If an invalid DaqMode is supplied.
        """
        if task_callback:
            task_callback(status=TaskStatus.IN_PROGRESS)
        # Check data directory is in correct format, if not then reconfigure.
        # This delays the start call by a lot if SKUID isn't there.
        if not self._data_directory_format_adr55_compliant():
            config = {"directory": self._construct_adr55_filepath()}
            self.configure_daq(**config)
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

        if not self._receiver_started:
            self._daq_client.initialise_daq()
            self._receiver_started = True

        self.client_queue = queue.SimpleQueue()
        callbacks = [self._file_dump_callback] * len(converted_modes_to_start)
        self._daq_client.start_daq(converted_modes_to_start, callbacks)
        self.logger.info("Daq listening......")

        if task_callback:
            task_callback(
                status=TaskStatus.COMPLETED,
                result=(ResultCode.OK, "Daq started"),
            )

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
        self._daq_client.stop_daq()
        self._receiver_started = False
        self._started_event.clear()
        if self._component_state_callback:
            self._component_state_callback(reset_consumer_attributes=True)
        if task_callback:
            task_callback(status=TaskStatus.COMPLETED)

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

    @property
    @check_communicating
    def get_running_consumers(self: DaqComponentManager) -> list:
        """
        Provide a list of the status consumers.

        :return: A list of running consumers in the format:
            [[Consumer Name, Consumer Value (int)],]
        """
        full_consumer_list = self._daq_client._running_consumers.items()
        running_consumer_list = [
            [consumer.name, consumer.value]
            for consumer, running in full_consumer_list
            if running
        ]
        return running_consumer_list

    @property
    @check_communicating
    def get_receiver_interface(self: DaqComponentManager) -> str:
        """
        Return the receiver interface as string.

        :return: "Interface Name"
        """
        return str(self._daq_client._config["receiver_interface"])

    @property
    @check_communicating
    def get_receiver_ports(self: DaqComponentManager) -> Any:
        """
        Provide a list of ports used by the receiver.

        :return: ["port number"]
        """
        return self._daq_client._config["receiver_ports"]

    @property
    @check_communicating
    def get_receiver_ip(self: DaqComponentManager) -> str:
        """Read the receiver IP address and save it.

        :return: receiver ip as string
        """
        return self._external_ip_override or str(
            self._daq_client._config["receiver_ip"]
        )

    def start_bandpass_monitor(
        self: DaqComponentManager,
        task_callback: TaskCallbackType | None = None,
    ) -> tuple[TaskStatus, str]:
        """
        Start monitoring antenna bandpasses.

        The MccsDaqReceiver will begin monitoring antenna bandpasses
            and producing plots of the spectra.

        :param task_callback: Update task state, defaults to None

        :return: a Taskstatus and response message
        """
        if self._monitoring_bandpass:
            self.logger.info("Bandpass monitor already started.")
            return (TaskStatus.REJECTED, "Bandpass monitor already started.")
        self.logger.info("Starting bandpass monitor.")
        return self.submit_task(
            self._start_bandpass_monitor,
            task_callback=task_callback,
        )

    @check_communicating
    def _start_bandpass_monitor(
        self: DaqComponentManager,
        task_callback: TaskCallbackType | None = None,
        task_abort_event: Optional[threading.Event] = None,
    ) -> None:
        """
        Start monitoring antenna bandpasses.

        The MccsDaqReceiver will begin monitoring antenna bandpasses
            and producing plots of the spectra.

        :param task_callback: Update task state, defaults to None
        :param task_abort_event: Check for abort, defaults to None

        """
        if task_callback:
            task_callback(status=TaskStatus.IN_PROGRESS)
        self._full_station_data = np.zeros(shape=(512, 256, 2), dtype=float)
        self._files_received_per_tile = [0] * self._nof_tiles
        self._monitoring_bandpass = True
        if task_callback:
            task_callback(
                status=TaskStatus.COMPLETED,
                result=(ResultCode.OK, "Bandpass monitor active"),
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

        # x_pol_data: np.ndarray | None = None
        # x_pol_data_count: int = 0
        # y_pol_data: np.ndarray | None = None
        # y_pol_data_count: int = 0

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
                self._files_received_per_tile[tile_number] += 1
            except IndexError as e:
                self.logger.error(
                    f"Caught exception: {e}. "
                    f"Tile {tile_number} out of bounds! "
                    f"Max tile number: {len(self._files_received_per_tile)}"
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
                data = self._to_db(
                    data.reshape((nof_channels, nof_antennas_per_tile, nof_pols))
                )
            except ValueError as ve:
                self.logger.error("ValueError caught reshaping data, skipping: %s", ve)
                return

        # Append Tile data to full station set.
        # full_station_data is made of blocks of data per TPM in TPM order.
        # Each block of TPM data is in port order.
        start_index = nof_antennas_per_tile * tile_number
        self._full_station_data[
            :, start_index : start_index + nof_antennas_per_tile, :
        ] = data

        # present = datetime.datetime.now()
        # if interval_start is None:
        #     interval_start = present

        # TODO: This block is currently useless. Get averaging back in.
        # Loop over polarisations (separate plots)
        # for pol in range(nof_pols):
        #     # Assign first data point or maintain sum of all data.
        #     # Divide by _pol_data_count to calculate the moving average on-demand.
        #     if pol == X_POL_INDEX:
        #         if x_pol_data is None:
        #             x_pol_data_count = 1
        #             x_pol_data = full_station_data[:, :, pol]
        #         else:
        #             x_pol_data_count += 1
        #             x_pol_data = x_pol_data + full_station_data[:, :, pol]
        #     elif pol == Y_POL_INDEX:
        #         if y_pol_data is None:
        #             y_pol_data_count = 1
        #             y_pol_data = full_station_data[:, :, pol]
        #         else:
        #             y_pol_data_count += 1
        #             y_pol_data = y_pol_data + full_station_data[:, :, pol]

        # Delete read file.
        os.unlink(filepath)
        # to the queue to be sent to the Tango device,
        # Assert that we've received the same number (1+) of files per tile.
        if all(self._files_received_per_tile) and (
            len(set(self._files_received_per_tile)) == 1
        ):
            x_data = self._full_station_data[:, :, X_POL_INDEX].transpose()
            # Averaged x data (commented out for now)
            # x_data = x_pol_data.transpose() / x_pol_data_count
            y_data = self._full_station_data[:, :, Y_POL_INDEX].transpose()
            # Averaged y data (commented out for now)
            # y_data = y_pol_data.transpose() / y_pol_data_count
            if self._component_state_callback is not None:
                self._component_state_callback(
                    x_bandpass_plot=x_data, y_bandpass_plot=y_data
                )
            self.logger.debug("Bandpasses transmitted.")

            # Reset vars
            # x_pol_data = None
            # x_pol_data_count = 0
            # y_pol_data = None
            # y_pol_data_count = 0
            # interval_start = None
            self._files_received_per_tile = [0] * nof_tiles
            self._full_station_data = np.zeros(shape=(512, 256, 2), dtype=float)

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
        self._monitoring_bandpass = False
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

    def __take_network_snapshot(self: DaqComponentManager) -> tuple[int, int, int]:
        net = psutil.net_io_counters(pernic=True)
        interface_stats = net[self._daq_client._config["receiver_interface"]]
        return (
            interface_stats.bytes_recv,
            interface_stats.packets_recv,
            interface_stats.dropin,
        )

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
            self.logger.info("Starting net IO sampling.")
            while self._measure_data_rate:
                try:
                    (
                        t1_bytes_received,
                        t1_packets_received,
                        t1_packets_dropped,
                    ) = self.__take_network_snapshot()
                    t1 = perf_counter()

                    sleep(interval)

                    (
                        t2_bytes_received,
                        t2_packets_received,
                        t2_packets_dropped,
                    ) = self.__take_network_snapshot()
                    t2 = perf_counter()
                    bytes_received = t2_bytes_received - t1_bytes_received
                    packets_received = t2_packets_received - t1_packets_received
                    packets_dropped = t2_packets_dropped - t1_packets_dropped
                    data_rate = bytes_received / (t2 - t1)
                    receive_rate = packets_received / (t2 - t1)
                    drop_rate = packets_dropped / (t2 - t1)
                    self._attribute_callback("data_rate", data_rate / 1024**3)
                    self._attribute_callback("receive_rate", receive_rate)
                    self._attribute_callback("drop_rate", drop_rate)
                except Exception:  # pylint: disable=broad-exception-caught
                    self.logger.error(
                        "Caught error in data rate monitor.", exc_info=True
                    )
                    sleep(1)
            self.logger.info("Stopped net IO sampling.")

        data_rate_thread = threading.Thread(
            target=_measure_data_rate, args=[interval], name="DataRateMonitor"
        )
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

    def _event_loop(self: DaqComponentManager) -> None:
        """Event loop for handling attribute updated from DAQ."""
        while True:
            try:
                attribute_name, attribute_value = self._event_queue.get()
                if self._component_state_callback is not None:
                    self._component_state_callback(**{attribute_name: attribute_value})
            except Exception:  # pylint: disable=broad-exception-caught
                self.logger.warning("Caught exception in event loop.", exc_info=True)

    def _attribute_callback(
        self: DaqComponentManager, attribute_name: str, attribute_value: float
    ) -> None:
        """
        Record changes in attributes from DAQ.

        :param attribute_name: name of the attribute.
        :param attribute_value: value of the attribute.
        """
        self._event_queue.put((attribute_name, attribute_value))
