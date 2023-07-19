# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.
"""This module implements the DaqServer part of the MccsDaqReceiver device."""
from __future__ import annotations

import functools
import logging
import os
import json
import shutil
import tempfile
import threading
from enum import IntEnum
from multiprocessing import Process
from time import sleep
from typing import Any, Callable, Iterator, List, Optional, TypeVar, cast

import pexpect
from aavs_calibration.common import get_antenna_positions
from pyaavs import station
from pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from ska_control_model import ResultCode
from ska_low_mccs_daq_interface.server import run_server_forever
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

__all__ = ["DaqHandler", "main"]

Wrapped = TypeVar("Wrapped", bound=Callable[..., Any])


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

# Global store containing files to be processed
antenna_locations = {}
files_to_plot = {}


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
        additional_info: Optional[str] = None,
    ) -> None:
        """
        Add a item to the buffer and set pending evaluation to true.

        :param data_type: The DAQ data type written
        :param file_name: The filename written
        :param additional_info: Any additional information.
        """
        self.logger.info(
            f"File: {file_name}, with data: {data_type} added to buffer"
        )  # noqa: E501

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
            yield (self.data_types_received[i], self.written_files[i])

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


class DaqHandler:
    """An implementation of a DaqHandler device."""

    def __init__(self: DaqHandler):
        """Initialise this device."""
        self.daq_instance: DaqReceiver = None
        self._receiver_started: bool = False
        self._initialised: bool = False
        self._stop_bandpass: bool = False
        self.logger = logging.getLogger("daq-server")
        self.state = DaqStatus.STOPPED
        self.request_stop = False
        self.buffer = DaqCallbackBuffer(self.logger)

    def _file_dump_callback(
        self: DaqHandler,
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
    ) -> Iterator[str | tuple[str, str]]:
        """
        Start data acquisition with the current configuration.

        A infinite streaming loop will be started until told to stop.
        This will notify the client of state changes and metadata
        of files written to disk, e.g. `data_type`.`file_name`.

        :param modes_to_start: string listing the modes to start.

        :yield: a status update.
        """
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
        }

    @check_initialisation
    def start_bandpass_monitor(
        self: DaqHandler,
        argin: str,
    ) -> tuple[ResultCode, str]:
        """
        Begin monitoring antenna bandpasses.

        :param argin: A dict of arguments to pass to `start_bandpass_monitor` command.
            KEYS:
            * station_config_path: Path to station configuration file. Mandatory.
            * plot_directory: Plotting directory. Mandatory.
            * monitor_rms: Flag to enable or disable RMS monitoring. Optional. Default False.
            * auto_handle_daq: Flag to indicate whether the DaqReceiver should be automatically
                reconfigured, started and stopped during this process if necessary. Optional. Default False.

        :return: a resultcode, message tuple
        """
        global antenna_locations
        self._stop_bandpass = False
        params = json.loads(argin)
        try:
            station_config_path: str = params["station_config_path"]
            plot_directory: str = params["plot_directory"]
        except KeyError:
            self.logger.error("PANIC!")
            return (
                ResultCode.REJECTED,
                "Invalid configuration detected. Please check.",
            )  # TODO: A more useful message.
        monitor_rms: bool = params["monitor_rms"] or False
        auto_handle_daq: bool = params["auto_handle_daq"] or False

        # Check DAQ is in the correct state for monitoring bandpasses.
        # If not, throw an error if we chose not to auto_handle_daq otherwise configure appropriately.
        current_config = self.get_configuration()
        if current_config["append_integrated"]:
            if not auto_handle_daq:
                self.logger.error(
                    "Current DAQ config is invalid."
                    "The `append_integrated` option must be set to false for bandpass monitoring."
                )
                return (
                    ResultCode.REJECTED,
                    "Current DAQ config is invalid."
                    "The `append_integrated` option must be set to false for bandpass monitoring.",
                )
            self.configure({"append_integrated": False})

        running_consumers = self.get_status().get("Running Consumers")
        if "INTEGRATED_CHANNEL_DATA" not in running_consumers:
            if not auto_handle_daq:
                self.logger.error(
                    "INTEGRATED_CHANNEL_DATA consumer must be running before bandpasses can be monitored."
                    "Running consumers: %s",
                    running_consumers,
                )
                return (
                    ResultCode.REJECTED,
                    "INTEGRATED_CHANNEL_DATA consumer must be running before bandpasses can be monitored.",
                )
            self.start(modes_to_start="INTEGRATED_CHANNEL_DATA")
            # TODO: poll_until_consumer_running

        # Load configuration file
        station.load_configuration_file(station_config_path)
        station_conf = station.configuration

        # Extract station name
        station_name = station_conf["station"]["name"]
        if station_name.upper() == "UNNAMED":
            self.logger.error(
                "Please set station name in configuration file %s, currently unnamed",
                station_config_path,
            )
            return (
                ResultCode.REJECTED,
                f"Please set station name in configuration file {station_config_path}, currently unnamed",
            )

        # Check that the station is configured to transmit data over 1G
        if station_conf["network"]["lmc"]["use_teng_integrated"]:
            self.logger.error(
                "Station %s must be configured to send integrated data over the 1G network, "
                "and each station should define a different destination port. Please check",
                station_config_path,
            )
            return (
                ResultCode.REJECTED,
                f"Station {station_config_path} must be configured to send integrated data "
                "over the 1G network, and each station should define a different destination port. Please check",
            )

        # Get and store antenna positions
        antenna_locations[station_name] = get_antenna_positions(station_name)

        # Create plotting directory structure
        if not self.create_plotting_directory(plot_directory, station_name):
            self.logger.error(
                "Unable to create plotting director at %s", plot_directory
            )
            return (
                ResultCode.FAILED,
                f"Unable to create plotting directory at: {plot_directory}",
            )

        # Create data directory
        data_directory = tempfile.mkdtemp()
        self.logger.info("Using temp dir %s", data_directory)

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

        yield (ResultCode.STARTED, "Bandpass monitoring active.")
        # Wait for stop, monitoring disk space in the meantime
        max_dir_size = 200 * 1024 * 1024
        while not self._stop_bandpass:
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
            sleep(5)

        # Stop and clean up
        self.logger.info("Waiting for threads and processes to terminate.")
        if auto_handle_daq:
            self.stop()
        observer.stop()
        shutil.rmtree(data_directory, ignore_errors=True)
        observer.join()
        bandpass_plotting_thread.join()

    @check_initialisation
    def stop_bandpass_monitor(self: DaqHandler) -> tuple[ResultCode, str]:
        self._stop_bandpass = True
        # TODO: Check this has stopped.
        return (ResultCode.OK, "Bandpass monitor stopping.")

    def generate_rms_plots(self, config, plotting_directory) -> None:
        """
        Generate RMS plots.

        :param config: Station configuration file.
        :param directory: Directory to store plots in.
        """
        global files_to_plot
        for _ in range(10):
            logging.debug("I want to be an RMS plot when I grow up...")

    def generate_bandpass_plots(self, station_name, plotting_directory) -> None:
        """
        Generate antenna bandpass plots.

        :param station_name: The name of the station.
        :param plotting_directory: Directory to store plots in.
        """
        global files_to_plot
        for _ in range(10):
            logging.debug("I want to be a bandpass plot when I grow up...")

    # pylint: disable=broad-except
    def create_plotting_directory(self, parent, station_name):
        """
        Create plotting directory structure for this station.

        :param parent: Parent plotting directory
        :param station_name: Station name
        """
        # Check if plot directory exists and if not create it
        if not os.path.exists(parent):
            try:
                os.mkdir(parent)
            except Exception:
                logging.error(
                    "Could not create plotting directory %s. "
                    "Check that the path is valid and permission",
                    parent,
                )
                return False
        elif os.path.isdir(parent):
            if not os.path.exists(os.path.join(parent, station_name)):
                try:
                    os.mkdir(os.path.join(parent, station_name))
                except Exception:
                    logging.error(
                        "Could not plotting subdirectory for %s in %s. " "Please check",
                        parent,
                        station_name,
                    )
                    return False
        else:
            logging.error(
                "Specified plotting directory (%s) is a file. Please check", parent
            )
            return False

        return True


class IntegratedDataHandler(FileSystemEventHandler):
    """Detects file created in the data directory and generates plots"""

    def __init__(self, station_name):
        """Constructor
        :param station_name: Station name"""
        self._station_name = station_name
        files_to_plot[station_name] = []

    def on_any_event(self, event):
        """
        Check every event for newly created files to process.
        """
        # We are only interested in newly created files
        global files_to_plot

        if event.event_type == "created":

            # Ignore lock files and other temporary files
            if not ("channel" in event.src_path and not "lock" in event.src_path):
                return

            # Add to list
            sleep(0.1)
            logging.info("Detected %s", event.src_path)
            files_to_plot[self._station_name].append(event.src_path)


def main() -> None:
    """
    Entrypoint for the module.

    Create and start a server.
    """
    port = os.getenv("DAQ_GRPC_PORT", default="50051")
    run_server_forever(DaqHandler(), int(port))


if __name__ == "__main__":
    main()
