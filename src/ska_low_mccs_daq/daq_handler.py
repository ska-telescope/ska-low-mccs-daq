# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.
"""This module implements the DaqServer part of the MccsDaqReceiver device."""
from __future__ import annotations

import base64
import datetime
import functools
import json
import logging
import os
import queue
import re

# import shutil
# import tempfile
import threading
from enum import IntEnum
from multiprocessing import Process
from time import sleep
from typing import Any, Callable, Iterator, List, Optional, TypeVar, cast

import h5py
import numpy as np

# import pexpect
# from aavs_calibration.common import get_antenna_positions
from matplotlib.backends.backend_svg import FigureCanvasSVG as FigureCanvas
from matplotlib.figure import Figure
from past.utils import old_div
from pyaavs import station
from pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from ska_control_model import ResultCode, TaskStatus
from ska_low_mccs_daq_interface.server import run_server_forever
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

__all__ = ["DaqHandler", "main"]

Wrapped = TypeVar("Wrapped", bound=Callable[..., Any])

# pylint: disable = redefined-builtin
print = functools.partial(print, flush=True)  # noqa: A001
# pylint: disable = broad-exception-raised, bare-except
# pylint: disable = global-variable-not-assigned, too-many-lines


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


class DaqStatus(IntEnum):
    """DAQ Status."""

    STOPPED = 0
    RECEIVING = 1
    LISTENING = 2


# Global parameters
nof_antennas_per_tile = 16
nof_channels = 512
bandwidth = 400.0
nof_pols = 2
files_to_plot: dict[str, list[str]] = {}


class DaqCallbackBuffer:
    """A DAQ callback buffer to flush to the client every poll."""

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
        additional_info: str,
    ) -> None:
        """
        Add a item to the buffer and set pending evaluation to true.

        :param data_type: The DAQ data type written
        :param file_name: The filename written
        :param additional_info: Any additional information and metadata.
        """
        self.logger.info(
            f"File: {file_name}, with data: {data_type} added to buffer"
        )  # noqa: E501

        self.data_types_received.append(data_type)
        self.written_files.append(file_name)
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
            yield (
                self.data_types_received[i],
                self.written_files[i],
                self.extra_info[i],
            )

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


def check_initialisation(func: Wrapped) -> Wrapped:
    """
    Return a function that checks component initialisation before calling.

    This function is intended to be used as a decorator:

    .. code-block:: python

        @check_initialisation
        def scan(self):
            ...

    :param func: the wrapped function

    :return: the wrapped function
    """

    @functools.wraps(func)
    def _wrapper(
        self: DaqHandler,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Check for component initialisation before calling the function.

        This is a wrapper function that implements the functionality of
        the decorator.

        :param self: This instance of an DaqHandler.
        :param args: positional arguments to the wrapped function
        :param kwargs: keyword arguments to the wrapped function

        :raises ValueError: if component initialisation has
            not been completed.
        :return: whatever the wrapped function returns
        """
        if not self.initialised:
            raise ValueError(
                f"Cannot execute '{type(self).__name__}.{func.__name__}'. "
                "DaqReceiver has not been initialised. "
                "Set adminMode to ONLINE to re-initialise."
            )
        return func(self, *args, **kwargs)

    return cast(Wrapped, _wrapper)


class DaqHandler:  # pylint: disable=too-many-instance-attributes
    """An implementation of a DaqHandler device."""

    def __init__(self: DaqHandler):
        """Initialise this device."""
        self.daq_instance: DaqReceiver = None
        self._receiver_started: bool = False
        self._initialised: bool = False
        self._stop_bandpass: bool = False
        self._monitoring_bandpass: bool = False
        self.logger = logging.getLogger("daq-server")
        self.state = DaqStatus.STOPPED
        self.request_stop = False
        self.buffer = DaqCallbackBuffer(self.logger)
        # TODO: Check this typehint. Floats might be ints, not sure.
        self._antenna_locations: dict[
            str, tuple[list[int], list[float], list[float]]
        ] = {}
        self._plots_to_send: bool = False
        self._x_bandpass_plots: queue.Queue = queue.Queue()
        self._y_bandpass_plots: queue.Queue = queue.Queue()
        self._rms_plots: queue.Queue = queue.Queue()

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

    # def _file_dump_callback(
    #     self: DaqHandler,
    #     data_mode: str,
    #     file_name: str,
    #     additional_info: Optional[int] = None,
    # ) -> None:
    #     """
    #     Add metadata to buffer.

    #     :param data_mode: The DAQ data type written
    #     :param file_name: The filename written
    #     :param additional_info: Any additional information.
    #     """
    #     # We don't have access to the timestamp here so this will retrieve the most
    #     # recent match
    # daq_mode = self._data_mode_mapping[data_mode]
    # if daq_mode not in {DaqModes.STATION_BEAM_DATA, DaqModes.CORRELATOR_DATA}:
    #     metadata = self.daq_instance._persisters[daq_mode].get_metadata(
    #         tile_id=additional_info
    #     )
    # else:
    #     metadata = self.daq_instance._persisters[daq_mode].get_metadata()
    # if additional_info is not None:
    #     metadata["additional_info"] = additional_info

    # self.buffer.add(data_mode, file_name, json.dumps(metadata, cls=NumpyEncoder))

    # # Callback called for every data mode.
    def _file_dump_callback(  # noqa: C901
        self: DaqHandler,
        data_mode: str,
        file_name: str,
        additional_info: Optional[str] = None,
    ) -> None:
        """
        Call a callback for specific data mode.

        Callbacks for all or specific data modes should be called here.

        :param data_mode: The DAQ data type written
        :param file_name: The filename written
        :param additional_info: Any additional information.
        """
        # Callbacks to call for all data modes.
        daq_mode = self._data_mode_mapping[data_mode]
        if daq_mode not in {DaqModes.STATION_BEAM_DATA, DaqModes.CORRELATOR_DATA}:
            metadata = self.daq_instance._persisters[daq_mode].get_metadata(
                tile_id=additional_info
            )
        else:
            metadata = self.daq_instance._persisters[daq_mode].get_metadata()
        if additional_info is not None:
            metadata["additional_info"] = additional_info

        self.buffer.add(data_mode, file_name, json.dumps(metadata, cls=NumpyEncoder))

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
            self._integrated_channel_callback(
                data_mode=data_mode,
                file_name=file_name,
                additional_info=additional_info,
            )

        if data_mode == "correlator":
            pass

    def _integrated_channel_callback(
        self: DaqHandler,
        data_mode: str,
        file_name: str,
        additional_info: Optional[str] = None,
    ) -> None:
        """
        Call callbacks for only the integrated channel DaqMode.

        :param data_mode: The DAQ data type written
        :param file_name: The filename written
        :param additional_info: Any additional information.
        """

    def _update_status(self: DaqHandler) -> None:
        """Update the status of DAQ."""
        if self.state == DaqStatus.STOPPED:
            return
        if self.buffer.pending_evaluation:
            self.state = DaqStatus.RECEIVING
        else:
            self.state = DaqStatus.LISTENING

    def initialise(
        self: DaqHandler, config: dict[str, Any]
    ) -> tuple[ResultCode, str]:  # noqa: E501
        """
        Initialise a new DaqReceiver instance.

        :param config: the configuration to apply

        :return: a resultcode, message tuple
        """
        if self._initialised is False:
            self.logger.info("Initialising daq.")
            self.daq_instance = DaqReceiver()
            try:
                if config:
                    self.daq_instance.populate_configuration(config)

                self.daq_instance.initialise_daq()
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

    @property
    def initialised(self) -> bool:
        """
        Return whether the DAQ is initialised.

        :return: whether the DAQ is initialised.
        """
        return self._initialised

    @check_initialisation
    def start(
        self: DaqHandler,
        modes_to_start: str,
    ) -> Iterator[str | tuple[str, str, str]]:
        """
        Start data acquisition with the current configuration.

        A infinite streaming loop will be started until told to stop.
        This will notify the client of state changes and metadata
        of files written to disk, e.g. `data_type`.`file_name`.

        :param modes_to_start: string listing the modes to start.

        :yield: a status update.
        """
        print("IN START")
        if not self._receiver_started:
            self.daq_instance.initialise_daq()
            self._receiver_started = True
        try:
            # Convert string representation to DaqModes
            converted_modes_to_start: list[DaqModes] = convert_daq_modes(
                modes_to_start
            )  # noqa: E501
        except ValueError as e:
            self.logger.error("Value Error! Invalid DaqMode supplied! %s", e)
            return
        # yuck
        callbacks = [self._file_dump_callback] * len(converted_modes_to_start)
        self.daq_instance.start_daq(converted_modes_to_start, callbacks)
        self.request_stop = False

        yield "LISTENING"

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
            self._update_status()

        # if we have got here we have stopped
        yield "STOPPED"

    @check_initialisation
    def stop(self: DaqHandler) -> tuple[ResultCode, str]:
        """
        Stop data acquisition.

        :return: a resultcode, message tuple
        """
        self.logger.info("Stopping daq.....")
        self.daq_instance.stop_daq()
        self._receiver_started = False
        self.request_stop = True
        return ResultCode.OK, "Daq stopped"

    @check_initialisation
    def configure(
        self: DaqHandler, config: dict[str, Any]
    ) -> tuple[ResultCode, str]:  # noqa: E501
        """
        Apply a configuration to the DaqReceiver.

        :param config: the configuration to apply

        :return: a resultcode, message tuple
        """
        self.logger.info("Configuring daq with: %s", config)
        try:
            if not config:
                self.logger.error(
                    "Daq was not reconfigured, no config data supplied."
                )  # noqa: E501
                return ResultCode.REJECTED, "No configuration data supplied."

            self.daq_instance.populate_configuration(config)
            self.logger.info("Daq successfully reconfigured.")
            return ResultCode.OK, "Daq reconfigured"

        # pylint: disable=broad-except
        except Exception as e:
            self.logger.error(f"Caught exception in DaqHandler.configure: {e}")
            return ResultCode.FAILED, f"Caught exception: {e}"

    @check_initialisation
    def get_configuration(
        self: DaqHandler,
    ) -> dict[str, Any]:
        """
        Retrieve the current DAQ configuration.

        :return: a configuration dictionary.
        """
        return self.daq_instance.get_configuration()

    @check_initialisation
    def get_status(self: DaqHandler) -> dict[str, Any]:
        """
        Provide status information for this MccsDaqReceiver.

        This method returns status as a json string with entries for:
            - Running Consumers: [DaqMode.name: str, DaqMode.value: int]
            - Receiver Interface: "Interface Name": str
            - Receiver Ports: [Port_List]: list[int]
            - Receiver IP: "IP_Address": str

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
        return {
            "Running Consumers": running_consumer_list,
            "Receiver Interface": receiver_interface,
            "Receiver Ports": receiver_ports,
            "Receiver IP": [
                receiver_ip.decode()
                if isinstance(receiver_ip, bytes)
                else receiver_ip  # noqa: E501
            ],
            "Bandpass Monitor": self._monitoring_bandpass,
        }

    # TODO: Refactor this method to farm out some steps.
    # pylint: disable = too-many-locals, too-many-statements
    # pylint: disable = too-many-return-statements, too-many-branches
    @check_initialisation
    def start_bandpass_monitor(  # noqa: C901
        self: DaqHandler,
        argin: str,
    ) -> Iterator[tuple[TaskStatus, str, str | None, str | None, str | None]]:
        """
        Begin monitoring antenna bandpasses.

        :param argin: A dict of arguments to pass to `start_bandpass_monitor` command.

            * station_config_path: Path to station configuration file.
                Mandatory.

            * plot_directory: Plotting directory.
                Mandatory.

            * monitor_rms: Flag to enable or disable RMS monitoring.
                Optional. Default False.

            * auto_handle_daq: Flag to indicate whether the DaqReceiver should
                be automatically reconfigured, started and stopped during this
                process if necessary.
                Optional. Default False.

        :yields: Taskstatus, Message, bandpass/rms plot(s).
        :returns: TaskStatus, Message, None, None, None
        """
        if self._monitoring_bandpass:
            yield (
                TaskStatus.REJECTED,
                "Bandpass monitor is already active.",
                None,
                None,
                None,
            )
            return
        print("IN DAQ HANDLER START BANDPASS")
        self._stop_bandpass = False
        params: dict[str, Any] = json.loads(argin)
        try:
            station_config_path: str = params["station_config_path"]
            plot_directory: str = params["plot_directory"]
        except KeyError:
            self.logger.error(
                "Param `argin` must have keys for `station_config_path` "
                "and `plot_directory`"
            )
            yield (
                TaskStatus.REJECTED,
                "Param `argin` must have keys for `station_config_path` "
                "and `plot_directory`",
                None,
                None,
                None,
            )
            return
        monitor_rms: bool = cast(bool, params.get("monitor_rms", False))
        auto_handle_daq: bool = cast(bool, params.get("auto_handle_daq", False))
        print("CHECKING CONFIG")
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
            self.configure({"append_integrated": False})

        # Check correct consumer is running.
        running_consumers = self.get_status().get("Running Consumers", "")
        # print(running_consumers)
        # print("INTEGRATED_CHANNEL_DATA" in running_consumers)
        if "INTEGRATED_CHANNEL_DATA" not in running_consumers:
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
            # TODO: Need to be able to start consumers incrementally for this.
            # result = self.start(modes_to_start="INTEGRATED_CHANNEL_DATA")
            # tmp=0
            # while "INTEGRATED_CHANNEL_DATA" not in running_consumers:
            #     tmp+=1
            #     sleep(2)
            #     print(running_consumers)
            #     running_consumers = self.get_status().get("Running Consumers")
            #     if tmp > 5:
            #         return

        # Load configuration file
        if not os.path.exists(station_config_path) or not os.path.isfile(
            station_config_path
        ):
            self.logger.error(
                "Specified configuration file (%s) does not exist.", station_config_path
            )
            yield (
                TaskStatus.REJECTED,
                f"Specified configuration file ({station_config_path}) does not exist.",
                None,
                None,
                None,
            )
            return
        station.load_configuration_file(station_config_path)
        station_conf = station.configuration

        # Extract station name
        station_name = station_conf["station"]["name"]
        if station_name.upper() == "UNNAMED":
            self.logger.error(
                "Please set station name in configuration file %s, currently unnamed",
                station_config_path,
            )
            yield (
                TaskStatus.REJECTED,
                "Please set station name in configuration file "
                f"{station_config_path}, currently unnamed.",
                None,
                None,
                None,
            )
            return

        # Check that the station is configured to transmit data over 1G
        if station_conf["network"]["lmc"]["use_teng_integrated"]:
            self.logger.error(
                "Station %s must be configured to send integrated data over the "
                "1G network, and each station should define a different "
                "destination port. Please check",
                station_config_path,
            )
            yield (
                TaskStatus.REJECTED,
                f"Station {station_config_path} must be configured to send "
                "integrated data over the 1G network, and each station should "
                "define a different destination port. Please check",
                None,
                None,
                None,
            )
            return

        # Get and store antenna positions
        # TODO: PyMongo errors here atm. Due to no DB? Look into this.
        # try:
        #     self._antenna_locations[station_name]=get_antenna_positions(station_name)
        # except Exception as e:  # py lint: disable = broad-exception-caught
        #     self.logger.error(
        #         "Caught exception while trying to get antenna positions: %s", e
        #     )

        # Create plotting directory structure
        if not self.create_plotting_directory(plot_directory, station_name):
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

        data_directory = self.daq_instance._config["directory"]
        self.logger.info("Using data dir %s", data_directory)
        # Create data directory
        # data_directory = tempfile.mkdtemp()
        # self.logger.info("Using temp dir %s", data_directory)

        print("STARTING PROCESSES")
        # Start rms thread
        if monitor_rms:
            rms = Process(
                target=self.generate_rms_plots,
                args=(station_conf, os.path.join(plot_directory, station_name)),
            )
            rms.start()

        # Start directory monitor
        observer = Observer()
        data_handler = IntegratedDataHandler(station_name)
        observer.schedule(data_handler, data_directory)
        observer.start()

        # Start plotting thread
        bandpass_plotting_thread = threading.Thread(
            target=self.generate_bandpass_plots,
            args=(os.path.join(plot_directory, station_name), station_name),
        )
        bandpass_plotting_thread.start()
        # Wait for stop, monitoring disk space in the meantime
        max_dir_size = 200 * 1024 * 1024
        print("Setting _monitoring_bandpass and entering wait loop")
        self._monitoring_bandpass = True

        yield (TaskStatus.IN_PROGRESS, "Bandpass monitor active", None, None, None)
        print("AFTER SECOND YIELD")
        while not self._stop_bandpass:
            print(f"IN BANDPASS LOOP: {self._stop_bandpass}")
            dir_size = sum(
                os.path.getsize(f)
                for f in os.listdir(data_directory)
                if os.path.isfile(f)
            )
            if dir_size > max_dir_size:
                self.logger.error(
                    "Consuming too much disk space! Stopping bandpass monitor!"
                )
                self._stop_bandpass = True
                break

            try:
                x_bandpass_plot = self._x_bandpass_plots.get(block=False)
            except queue.Empty:
                # self.logger.error("Caught exception: %s", e)
                x_bandpass_plot = None
            except Exception as e:  # pylint: disable = broad-exception-caught
                print(f"x CAUGHT EXC: {e}")

            try:
                y_bandpass_plot = self._y_bandpass_plots.get(block=False)
            except queue.Empty:
                # self.logger.error("Caught exception: %s", e)
                y_bandpass_plot = None
            except Exception as e:  # pylint: disable = broad-exception-caught
                print(f"y CAUGHT EXC: {e}")

            try:
                rms_plot = self._rms_plots.get(block=False)
            except queue.Empty:
                # self.logger.error("Caught exception: %s", e)
                rms_plot = None
            except Exception as e:  # pylint: disable = broad-exception-caught
                print(f"rms CAUGHT EXC: {e}")

            if all(
                plot is None for plot in [x_bandpass_plot, y_bandpass_plot, rms_plot]
            ):
                # If we don't have any plots, don't uselessly spam [None]s.
                pass
            else:
                msg = (
                    TaskStatus.IN_PROGRESS,
                    "plot sent",
                    x_bandpass_plot,
                    y_bandpass_plot,
                    rms_plot,
                )
                print(f"Yielding: {msg}")
                yield (
                    TaskStatus.IN_PROGRESS,
                    "plot sent",
                    x_bandpass_plot,
                    y_bandpass_plot,
                    rms_plot,
                )
            sleep(1)
        print("STOPPING BANDPASS")
        # Stop and clean up
        self.logger.info("Waiting for threads and processes to terminate.")
        # TODO: Need to be able to stop consumers incrementally for this.
        # if auto_handle_daq:
        #     self.stop()
        observer.stop()

        # shutil.rmtree(data_directory, ignore_errors=True)
        observer.join()
        bandpass_plotting_thread.join()
        self._monitoring_bandpass = False

        yield (TaskStatus.COMPLETED, "Bandpass monitoring complete.", None, None, None)

    @check_initialisation
    def stop_bandpass_monitor(self: DaqHandler) -> tuple[ResultCode, str]:
        """
        Stop monitoring antenna bandpasses.

        :return: a resultcode, message tuple
        """
        self._stop_bandpass = True
        print(f"IN STOP BANDPASS. STATUS: {self._stop_bandpass}")
        # TODO: Check this has stopped.
        return (ResultCode.OK, "Bandpass monitor stopping.")

    # pylint: disable = too-many-locals
    def generate_rms_plots(  # noqa: C901
        self: DaqHandler, config: dict[str, Any], plotting_directory: str
    ) -> None:
        """
        Generate RMS plots.

        :param config: Station configuration file.
        :param plotting_directory: Directory to store plots in.
        """
        global files_to_plot

        def _connect_station() -> None:
            """Return a connected station."""
            # Connect to station and see if properly formed
            while True:
                try:
                    aavs_station.check_station_status()
                    if not aavs_station.properly_formed_station:
                        raise Exception
                    break
                except:  # noqa: E722
                    sleep(10)
                    try:
                        aavs_station.connect()
                    except:  # noqa: E722
                        continue

        # Create and connect to station
        aavs_station = station.Station(config)
        station_name = aavs_station.configuration["station"]["name"]
        print("BEFORE CONNECT STATION")
        _connect_station()
        print("AFTER CONNECT STATION")

        # Extract antenna locations
        antenna_base, antenna_x, antenna_y = self._antenna_locations[station_name]

        # Generate dummy RMS data
        colors = np.random.random(len(antenna_x)) * 30

        # Generate figure and canvas
        fig = Figure(figsize=(18, 8))
        canvas = FigureCanvas(fig)

        # Generate plot for X
        ax = fig.subplots(nrows=1, ncols=2, sharex="all", sharey="all")
        fig.suptitle(f"{station_name} Antenna RMS", fontsize=14)

        x_scatter = ax[0].scatter(
            antenna_x,
            antenna_y,
            s=50,
            marker="o",
            c=colors,
            cmap="jet",
            vmin=0,
            vmax=38,
            edgecolors="k",
            linewidths=0.8,
        )
        for i, _ in enumerate(antenna_x):
            ax[0].text(
                # pylint: disable = unnecessary-list-index-lookup
                antenna_x[i] + 0.3,
                antenna_y[i] + 0.3,
                antenna_base[i],
                fontsize=7,
            )
        ax[0].set_title(f"{station_name} Antenna RMS Map - X pol")
        ax[0].set_xlabel("X")
        ax[0].set_ylabel("Y")

        # Generate plot for Y
        y_scatter = ax[1].scatter(
            antenna_x,
            antenna_y,
            s=50,
            marker="o",
            c=colors,
            cmap="jet",
            vmin=0,
            vmax=38,
            edgecolors="k",
            linewidths=0.8,
        )
        for i, _ in enumerate(antenna_x):
            ax[1].text(
                # pylint: disable = unnecessary-list-index-lookup
                antenna_x[i] + 0.3,
                antenna_y[i] + 0.3,
                antenna_base[i],
                fontsize=7,
            )
        ax[1].set_title(f"{station_name} Antenna RMS Map - Y Pol")
        ax[1].set_xlabel("X")
        ax[1].set_ylabel("Y")

        # Add colorbar
        fig.subplots_adjust(
            bottom=0.1, top=0.9, left=0.1, right=0.88, wspace=0.05, hspace=0.17
        )
        cb_ax = fig.add_axes([0.9, 0.1, 0.02, 0.8])
        fig.colorbar(y_scatter, label="RMS", cax=cb_ax)

        # Continue until asked to stop
        while not self._stop_bandpass:

            # Check station status
            _connect_station()

            # Grab RMS values
            antenna_rms_x = []
            antenna_rms_y = []
            for tile in aavs_station.tiles:
                rms = tile.get_adc_rms()
                antenna_rms_x.extend(rms[0::2])
                antenna_rms_y.extend(rms[1::2])

            # Update colors
            x_scatter.set_array(np.array(antenna_rms_x))
            y_scatter.set_array(np.array(antenna_rms_y))

            # Save plot
            fig.suptitle(
                f"{station_name} Antenna RMS "
                f'({datetime.datetime.utcnow().strftime("%m/%d/%Y %H:%M:%S")})',
                fontsize=14,
            )
            saved_filepath = os.path.join(plotting_directory, "antenna_rms.svg")
            canvas.print_figure(
                saved_filepath,
                pad_inches=0,
                dpi=200,
                figsize=(18, 8),
            )
            self._rms_plots.put(saved_filepath)
            # Done, sleep for a bit
            sleep(5)

    # pylint: disable = too-many-locals
    def generate_bandpass_plots(
        self: DaqHandler, plotting_directory: str, station_name: str
    ) -> None:
        """
        Generate antenna bandpass plots.

        :param station_name: The name of the station.
        :param plotting_directory: Directory to store plots in.
        """
        print("ENTERING GENERATE BANDPASS PLOTS")
        global files_to_plot  # pylint: disable=global-variable-not-assigned

        _directory = plotting_directory
        _freq_range = np.arange(1, nof_channels) * (old_div(bandwidth, nof_channels))
        _filename_expression = re.compile(
            r"channel_integ_(?P<tile>\d+)_(?P<timestamp>\d+_\d+)_0.hdf5"
        )

        # Define fibre - antenna mapping
        _fibre_preadu_mapping = {
            0: 1,
            1: 2,
            2: 3,
            3: 4,
            7: 13,
            6: 14,
            5: 15,
            4: 16,
            8: 5,
            9: 6,
            10: 7,
            11: 8,
            15: 9,
            14: 10,
            13: 11,
            12: 12,
        }

        # Define plotting parameters
        _ribbon_color = {
            1: "gray",
            2: "g",
            3: "r",
            4: "k",
            5: "y",
            6: "m",
            7: "deeppink",
            8: "c",
            9: "gray",
            10: "g",
            11: "r",
            12: "k",
            13: "y",
            14: "m",
            15: "deeppink",
            16: "c",
        }
        _pol_map = ["X", "Y"]

        # Set up figure and initialise with dummy data
        plot_lines = []
        fig = Figure(figsize=(8, 4))
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)

        for antenna in range(nof_antennas_per_tile):
            tpm_input = _fibre_preadu_mapping[antenna]
            plot_lines.append(
                ax.plot(
                    _freq_range,
                    list(range(511)),
                    label=f"Antenna {antenna} (RX {tpm_input})",
                    color=_ribbon_color[tpm_input],
                    linewidth=0.6,
                )[0]
            )

        # Extract antenna locations
        # antenna_base, _, _ = self._antenna_locations[station_name]

        # Make nice
        ax.set_xlim((0, bandwidth))
        ax.set_ylim((0, 40))
        ax.set_title(f"Tile {0} - Pol {_pol_map[0]}", fontdict={"fontweight": "bold"})
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Power (dB)")
        date_text = ax.text(300, 38, "Today's Date", weight="bold", size="10")
        # legend = ax.legend(loc="lower center", ncol=4, prop={"size": 4})
        ax.minorticks_on()
        ax.grid(b=True, which="major", color="0.3", linestyle="-", linewidth=0.5)
        ax.grid(b=True, which="minor", color="0.8", linestyle="--", linewidth=0.1)

        # Loop until asked to stop
        while not self._stop_bandpass:
            # print("IN BANDPASS PLOTTER LOOP")
            # Wait for files to be queued
            while len(files_to_plot[station_name]) == 0 and not self._stop_bandpass:
                sleep(0.1)

            if self._stop_bandpass:
                return
            # print(f"DETECTED FILE. PROCESSING: {files_to_plot[station_name]}")
            # Get the first item in the list
            filepath = files_to_plot[station_name].pop(0)
            self.logger.info("Processing %s", filepath)

            # Extract Tile number
            filename = os.path.basename(os.path.abspath(filepath))
            parts = _filename_expression.match(filename)
            if parts is not None:
                tile_number = int(parts.groupdict()["tile"])

            print(f"Opening file: {filepath}")
            # Open newly create HDF5 file
            with h5py.File(filepath, "r") as f:
                # Data is in channels/antennas/pols order
                data = f["chan_"]["data"][:]
                # timestamp = f["sample_timestamps"]["data"][0]
                data = data.reshape((nof_channels, nof_antennas_per_tile, nof_pols))
                # Convert to power in dB
                np.seterr(divide="ignore")
                data = 10 * np.log10(data)
                data[np.isneginf(data)] = 0
                np.seterr(divide="warn")

            # Format datetime
            # TODO: TypeError: only integer scalar arrays can be
            # converted to a scalar index
            # date_time = datetime.datetime.utcfromtimestamp(timestamp).strftime(
            #     "%y-%m-%d %H:%M:%S"
            # )

            print("Creating plot(s)...")
            # Loop over polarisations (separate plots)
            for pol in range(nof_pols):

                # Loop over antennas, change plot data and label text
                for i, antenna in enumerate(range(nof_antennas_per_tile)):
                    plot_lines[i].set_ydata(data[1:, antenna, pol])
                    # legend.get_texts()[i].set_text(
                    #     f"{i:0>2d} - RX {_fibre_preadu_mapping[antenna]:0>2d} - "
                    #     f"Base {antenna_base[tile_number * 16 + i]:0>3d}"
                    # )

                # Update title and time
                ax.set_title(f"Tile {tile_number + 1} - Pol {_pol_map[pol]}")
                # TODO:
                # date_text.set_text(date_time)
                date_text.set_text("Today's Date")
                saved_plot_path: str = os.path.join(
                    _directory,
                    f"tile_{tile_number + 1}_pol_{_pol_map[pol].lower()}.svg",
                )
                print(f"Saving plot to: {saved_plot_path}")
                # Save updated figure
                canvas.print_figure(
                    saved_plot_path,
                    pad_inches=0,
                    dpi=200,
                    figsize=(8, 4),
                )
                print(f"DATA FLAGS: {data.flags}")
                if pol == 0:
                    # self._x_bandpass_plots.put(saved_plot_path)
                    print(f"unencoded xpol data: {data[1:, :, pol]}")
                    x_pol_data = data[1:, :, pol].tobytes()
                    print(f"byte-encoded xpol data: {x_pol_data}")
                    print(f"data type: {data.dtype}")
                    decoded_x_pol_data = np.frombuffer(x_pol_data, dtype=data.dtype)
                    reshaped_decoded_x = decoded_x_pol_data.reshape(
                        (nof_channels - 1, nof_antennas_per_tile)
                    )

                    print(f"decoded_x_pol_data: {decoded_x_pol_data}")
                    print(f"reshaped_decoded_x: {reshaped_decoded_x}")

                    self._x_bandpass_plots.put(x_pol_data)
                elif pol == 1:
                    # self._y_bandpass_plots.put(saved_plot_path)
                    self._y_bandpass_plots.put(
                        base64.b64encode(data[1:, :, pol].copy(order="C"))
                    )

            # Ready from file, delete it
            # os.unlink(filepath)
            # print("FINISHED PLOT")

    # pylint: disable=broad-except
    def create_plotting_directory(
        self: DaqHandler, parent: str, station_name: str
    ) -> bool:
        """
        Create plotting directory structure for this station.

        :param parent: Parent plotting directory
        :param station_name: Station name

        :return: True if this method succeeded else False
        """
        # Check if plot directory exists and if not create it
        if not os.path.exists(parent):
            try:
                os.mkdir(parent)
            except Exception:
                self.logger.error(
                    "Could not create plotting directory %s. "
                    "Check that the path is valid and permission",
                    parent,
                )
                return False
        else:
            # if path exists it's assumed it's a file?
            #  Seems wrong. Adding isdir check. - AJC
            if not os.path.isdir(parent):
                self.logger.error(
                    "Specified plotting directory (%s) is a file. Please check", parent
                )
                return False
        if os.path.isdir(parent):
            if not os.path.exists(os.path.join(parent, station_name)):
                try:
                    os.mkdir(os.path.join(parent, station_name))
                except Exception as e:
                    self.logger.error(
                        "Exception: %s. Could not create plotting subdirectory "
                        "for %s in %s. ",
                        e,
                        parent,
                        station_name,
                    )
                    return False
        else:
            self.logger.error(
                "Specified plotting directory (%s) is a file. Please check", parent
            )
            return False

        return True


class IntegratedDataHandler(FileSystemEventHandler):
    """Detect files created in the data directory and generate plots."""

    def __init__(self: IntegratedDataHandler, station_name: str):
        """
        Initialise a new instance.

        :param station_name: Station name
        """
        self._station_name = station_name
        files_to_plot[station_name] = []
        self.logger = logging.getLogger("daq-server")

    def on_any_event(self: IntegratedDataHandler, event: FileSystemEvent) -> None:
        """
        Check every event for newly created files to process.

        :param event: Event to check.
        """
        # We are only interested in newly created files
        global files_to_plot  # pylint: disable=global-variable-not-assigned
        if event.event_type in ["created", "modified"]:
            # Ignore lock files and other temporary files
            if not ("channel" in event.src_path and "lock" not in event.src_path):
                return

            # Add to list
            sleep(0.1)
            self.logger.info("Detected %s", event.src_path)
            files_to_plot[self._station_name].append(event.src_path)
            print(
                f"files_to_plot[{self._station_name}]: "
                f"{files_to_plot[self._station_name]}"
            )


def main() -> None:
    """
    Entrypoint for the module.

    Create and start a server.
    """
    port = os.getenv("DAQ_GRPC_PORT", default="50051")
    run_server_forever(DaqHandler(), int(port))


if __name__ == "__main__":
    main()
