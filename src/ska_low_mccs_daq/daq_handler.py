# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.
"""This module implements the DaqServer part of the MccsDaqReceiver device."""
from __future__ import annotations

import datetime
import functools
import json
import logging
import os
import pprint
import queue
import re
import threading
from collections import deque
from time import perf_counter, sleep
from typing import Any, Callable, Iterator, Optional, TypeVar, cast

import h5py
import numpy as np
import psutil  # type: ignore
from ska_control_model import ResultCode, TaskStatus
from ska_low_mccs_daq_interface.server import run_server_forever

from .aavs_system.python.pydaq.daq_receiver_interface import DaqModes, DaqReceiver

__all__ = ["DaqHandler", "main"]

X_POL_INDEX = 0
Y_POL_INDEX = 1

Wrapped = TypeVar("Wrapped", bound=Callable[..., Any])

# pylint: disable = too-many-lines


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


# pylint: disable = too-many-instance-attributes
class DaqHandler:
    """An implementation of a DaqHandler device."""

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

    def __init__(
        self: DaqHandler,
        **extra_config: Any,
    ) -> None:
        """
        Initialise this device.

        :param extra_config: keyword args providing extra configuration.
        """
        print("Initialising DAQ handler with extra config:")
        pprint.pprint(extra_config)

        self._config = self.CONFIG_DEFAULTS | extra_config

        self.daq_instance: DaqReceiver | None = None
        self._receiver_started: bool = False
        self._initialised: bool = False
        self._stop_bandpass: bool = False
        self._monitoring_bandpass: bool = False
        self.logger = logging.getLogger("daq-server")
        self.client_queue: queue.SimpleQueue[tuple[str, str, str] | None] | None = None
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
        # TODO: Check this typehint. Floats might be ints, not sure.
        self._antenna_locations: dict[
            str, tuple[list[int], list[float], list[float]]
        ] = {}
        self._plots_to_send: bool = False
        self._y_bandpass_plots: deque[str] = deque(maxlen=1)
        self._x_bandpass_plots: deque[str] = deque(maxlen=1)
        self._rms_plots: deque[str] = deque(maxlen=1)
        self._station_name: str = "a_station_name"  # TODO: Get Station TRL/ID
        self._plot_transmission: bool = False
        self._files_to_plot: queue.Queue[str] = queue.Queue()
        self._measure_data_rate: bool = False
        self._data_rate: float | None = None

    # Callback called for every data mode.
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
        :param additional_info: Any additional information/metadata.
        """
        assert self.daq_instance is not None
        # Callbacks to call for all data modes.
        daq_mode = self._data_mode_mapping[data_mode]
        if daq_mode not in {DaqModes.STATION_BEAM_DATA, DaqModes.CORRELATOR_DATA}:
            metadata = self.daq_instance._persisters[daq_mode].get_metadata(
                tile_id=additional_info
            )
        else:
            metadata = self.daq_instance._persisters[daq_mode].get_metadata()
        if additional_info is not None and metadata is not None:
            metadata["additional_info"] = additional_info

        if self._monitoring_bandpass:
            self._files_to_plot.put(file_name)

        self._data_received_callback(
            data_mode=data_mode,
            file_name=file_name,
            metadata=metadata,
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

    def _data_received_callback(
        self: DaqHandler,
        data_mode: str,
        file_name: str,
        metadata: Optional[str] = None,
    ) -> None:
        """
        Send file receipt information.

        :param data_mode: The DAQ data type written
        :param file_name: The filename written
        :param metadata: Any additional information.
        """
        if self.client_queue:
            self.client_queue.put(
                (data_mode, file_name, json.dumps(metadata, cls=NumpyEncoder))
            )

    def initialise(
        self: DaqHandler, config: dict[str, Any], libaavsdaq_filepath: str = ""
    ) -> tuple[ResultCode, str]:  # noqa: E501
        """
        Initialise a new DaqReceiver instance.

        :param config: the configuration to apply
        :param libaavsdaq_filepath: a .so file to use as the C library

        :return: a resultcode, message tuple
        """
        self.logger.info("initialise() issued with: %s", config)
        self._config |= config

        if self._initialised is False:
            self.logger.debug("Creating DaqReceiver instance.")
            self.daq_instance = DaqReceiver()
            try:
                self.logger.info(
                    "Configuring before initialising with: %s", self._config
                )
                self.daq_instance.populate_configuration(self._config)
                self.logger.info("Initialising daq.")
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

        :raises ValueError: if an invalid DaqMode is supplied
        """
        assert self.daq_instance is not None
        try:
            # Convert string representation to DaqModes
            converted_modes_to_start: list[DaqModes] = convert_daq_modes(
                modes_to_start
            )  # noqa: E501
        except ValueError as e:
            self.logger.error("Value Error! Invalid DaqMode supplied! %s", e)
            raise

        if not self._receiver_started:
            self.daq_instance.initialise_daq()
            self._receiver_started = True

        try:
            self.client_queue = queue.SimpleQueue()
            callbacks = [self._file_dump_callback] * len(converted_modes_to_start)
            self.daq_instance.start_daq(converted_modes_to_start, callbacks)
            self.logger.info("Daq listening......")

            yield "LISTENING"
            yield from iter(self.client_queue.get, None)
            yield "STOPPED"
        finally:
            # prevent queue from building up indefinitely
            self.client_queue = None

    @check_initialisation
    def stop(self: DaqHandler) -> tuple[ResultCode, str]:
        """
        Stop data acquisition.

        :return: a resultcode, message tuple
        """
        assert self.daq_instance is not None
        self.logger.info("Stopping daq.....")
        self.daq_instance.stop_daq()
        self._receiver_started = False
        if self.client_queue:
            self.client_queue.put(None)
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
        assert self.daq_instance is not None
        try:
            if not config:
                self.logger.error(
                    "Daq was not reconfigured, no config data supplied."
                )  # noqa: E501
                return ResultCode.REJECTED, "No configuration data supplied."

            if "directory" in config:
                if not os.path.exists(config["directory"]):
                    # Note: The daq-handler does not have permission
                    # to create a root directory
                    # This will be set up by container infrastructure.
                    self.logger.info(
                        f'directory {config["directory"]} does not exist, Creating...'
                    )
                    os.makedirs(config["directory"])
                    self.logger.info(f'directory {config["directory"]} created!')

            self._config |= config
            self.daq_instance.populate_configuration(self._config)
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
        assert self.daq_instance is not None
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
            - Bandpass Monitor: "Monitoring Status": bool

        :return: A json string containing the status of this DaqReceiver.
        """
        assert self.daq_instance is not None
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
                (
                    receiver_ip.decode()
                    if isinstance(receiver_ip, bytes)
                    else receiver_ip
                )  # noqa: E501
            ],
            "Bandpass Monitor": self._monitoring_bandpass,
        }

    # TODO: Refactor this method to farm out some steps.
    # pylint: disable = too-many-locals, too-many-statements
    # pylint: disable = too-many-branches
    @check_initialisation
    def start_bandpass_monitor(  # noqa: C901
        self: DaqHandler,
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
        assert self.daq_instance is not None
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
            self.configure({"append_integrated": False})

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
            #     tmp+=1
            #     sleep(2)
            #     running_consumers = self.get_status().get("Running Consumers")
            #     if tmp > 5:
            #         return

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

        data_directory = self.daq_instance._config["directory"]
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

    @check_initialisation
    def stop_bandpass_monitor(self: DaqHandler) -> tuple[ResultCode, str]:
        """
        Stop monitoring antenna bandpasses.

        :return: a resultcode, message tuple
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

    def generate_rms_plots(  # noqa: C901
        self: DaqHandler, station_name: str, plotting_directory: str
    ) -> None:
        """
        Generate RMS plots.

        :param station_name: Station name.
        :param plotting_directory: Directory to store plots in.
        """
        # Note: This method is commented out until we can access antenna locations
        #   and tile proxies in order to retrieve adc power and properly label graphs.

        # Get station name (from somewhere...)
        # station_name = aavs_station.configuration["station"]["name"]
        # _connect_station()

        # Extract antenna locations
        # antenna_base, antenna_x, antenna_y = self._antenna_locations[station_name]

        # Generate dummy RMS data
        # colors = np.random.random(len(antenna_x)) * 30

        # Generate figure and canvas
        # fig = Figure(figsize=(18, 8))
        # canvas = FigureCanvas(fig)

        # # Generate plot for X
        # ax = fig.subplots(nrows=1, ncols=2, sharex="all", sharey="all")
        # fig.suptitle(f"{station_name} Antenna RMS", fontsize=14)

        # x_scatter = ax[0].scatter(
        #     antenna_x,
        #     antenna_y,
        #     s=50,
        #     marker="o",
        #     c=colors,
        #     cmap="jet",
        #     vmin=0,
        #     vmax=38,
        #     edgecolors="k",
        #     linewidths=0.8,
        # )
        # for i, _ in enumerate(antenna_x):
        #     ax[0].text(
        #         antenna_x[i] + 0.3,
        #         antenna_y[i] + 0.3,
        #         antenna_base[i],
        #         fontsize=7,
        #     )
        # ax[0].set_title(f"{station_name} Antenna RMS Map - X pol")
        # ax[0].set_xlabel("X")
        # ax[0].set_ylabel("Y")

        # # Generate plot for Y
        # y_scatter = ax[1].scatter(
        #     antenna_x,
        #     antenna_y,
        #     s=50,
        #     marker="o",
        #     c=colors,
        #     cmap="jet",
        #     vmin=0,
        #     vmax=38,
        #     edgecolors="k",
        #     linewidths=0.8,
        # )
        # for i, _ in enumerate(antenna_x):
        #     ax[1].text(
        #         antenna_x[i] + 0.3,
        #         antenna_y[i] + 0.3,
        #         antenna_base[i],
        #         fontsize=7,
        #     )
        # ax[1].set_title(f"{station_name} Antenna RMS Map - Y Pol")
        # ax[1].set_xlabel("X")
        # ax[1].set_ylabel("Y")

        # # Add colorbar
        # fig.subplots_adjust(
        #     bottom=0.1, top=0.9, left=0.1, right=0.88, wspace=0.05, hspace=0.17
        # )
        # cb_ax = fig.add_axes([0.9, 0.1, 0.02, 0.8])
        # fig.colorbar(y_scatter, label="RMS", cax=cb_ax)

        # # Continue until asked to stop
        # while not self._stop_bandpass:

        #     # Check station status
        #     # _connect_station()

        #     # Grab RMS values
        #     antenna_rms_x = []
        #     antenna_rms_y = []
        #     for tile in aavs_station.tiles:
        #         rms = tile.get_adc_rms()
        #         antenna_rms_x.extend(rms[0::2])
        #         antenna_rms_y.extend(rms[1::2])

        #     # Update colors
        #     x_scatter.set_array(np.array(antenna_rms_x))
        #     y_scatter.set_array(np.array(antenna_rms_y))

        #     # Save plot
        #     fig.suptitle(
        #         f"{station_name} Antenna RMS "
        #         f"({datetime.datetime.utcnow().strftime(self.TIME_FORMAT_STRING)})",
        #         fontsize=14,
        #     )
        #     saved_filepath = os.path.join(plotting_directory, "antenna_rms.svg")
        #     canvas.print_figure(
        #         saved_filepath,
        #         pad_inches=0,
        #         dpi=200,
        #         figsize=(18, 8),
        #     )
        #     self._rms_plots.put(saved_filepath)
        #     # Done, sleep for a bit
        #     sleep(1)

    # pylint: disable = too-many-locals
    def generate_bandpass_plots(  # noqa: C901
        self: DaqHandler,
        plotting_directory: str,
        station_name: str,
        cadence: int,
    ) -> None:
        """
        Generate antenna bandpass plots.

        :param station_name: The name of the station.
        :param plotting_directory: Directory to store plots in.
        :param cadence: Time in seconds over which to average bandpass data.
        """
        config = self.get_configuration()
        nof_channels = config["nof_channels"]
        nof_antennas_per_tile = config["nof_antennas"]
        nof_pols = config["nof_polarisations"]
        nof_tiles = config["nof_tiles"]

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

        # Loop until asked to stop
        self.logger.info("Entering bandpass plotting loop.")
        while not self._stop_bandpass:
            # Wait for files to be queued. Check every second.
            if self._files_to_plot.qsize() == 0:
                sleep(1)
                continue

            # Get the first item in the list
            filepath = self._files_to_plot.get()
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
                    continue
                try:
                    data = data.reshape((nof_channels, nof_antennas_per_tile, nof_pols))
                except ValueError as ve:
                    self.logger.error(
                        "ValueError caught reshaping data, skipping: %s", ve
                    )
                    continue

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
            # Every `cadence` seconds, plot graph and add the averages
            # to the queue to be sent to the Tango device,
            # Assert that we've received the same number (1+) of files per tile.
            if all(files_received_per_tile) and (
                len(set(files_received_per_tile)) == 1
            ):
                if (present - interval_start).total_seconds() > cadence:
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

        self.logger.info("Exiting bandpass plotting loop.")

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
        dir_name = os.path.join(parent, station_name)
        if not os.path.isdir(dir_name):
            try:
                os.makedirs(dir_name, exist_ok=True)

            except PermissionError as e:
                self.logger.error(e)
                self.logger.error(
                    "Could not create plotting directory %s. "
                    "Check that the path is valid and permission",
                    parent,
                )
                return False

            except NotADirectoryError as e:
                self.logger.error(e)
                self.logger.error(
                    "Specified plotting directory (%s) is a file. Please check", parent
                )
                return False

            except FileExistsError as e:
                self.logger.error(e)
                self.logger.error("Specified plotting directory (%s) is a file")
                return False

            except Exception as e:
                self.logger.error(e)
                self.logger.error(
                    "Unknown exception when creating plotting directory (%s)"
                )
                return False
        return True

    def get_data_rate(self: DaqHandler) -> float | None:
        """
        Get the data rate over the receiver network interface in Gb/s.

        :return: The data rate in Gb/s, None if not currently monitoring.
        """
        return self._data_rate

    def start_measuring_data_rate(
        self: DaqHandler, interval: float = 2.0
    ) -> tuple[ResultCode, str]:
        """
        Start measuring the data rate over the receiver network interface in Gb/s.

        :param interval: The interval in seconds to measure the data rate.

        :return: a resultcode, message tuple
        """
        if self._measure_data_rate:
            return (ResultCode.REJECTED, "Already measuring data rate.")

        self._measure_data_rate = True

        def _measure_data_rate(interval: int) -> None:
            self.logger.info("Starting data rate monitor.")
            while self._measure_data_rate:
                self.logger.debug("Measuring data rate...")
                net = psutil.net_io_counters(pernic=True)
                t1_sent_bytes = net[self._config["receiver_interface"]].bytes_recv
                t1 = perf_counter()

                sleep(interval)

                net = psutil.net_io_counters(pernic=True)
                t2_sent_bytes = net[self._config["receiver_interface"]].bytes_recv
                t2 = perf_counter()
                nbytes = t2_sent_bytes - t1_sent_bytes
                data_rate = nbytes / (t2 - t1)
                self._data_rate = data_rate / 1024**3  # Gb/s
            self._data_rate = None

        data_rate_thread = threading.Thread(target=_measure_data_rate, args=[interval])
        data_rate_thread.start()
        return (ResultCode.OK, "Data rate measurement started.")

    def stop_measuring_data_rate(self: DaqHandler) -> tuple[ResultCode, str]:
        """
        Stop measuring the data rate over the receiver network interface.

        :return: a resultcode, message tuple
        """
        self._measure_data_rate = False
        return (ResultCode.OK, "Data rate measurement stopping.")


def main() -> None:
    """
    Entrypoint for the module.

    Create and start a server.
    """
    handler = DaqHandler(
        receiver_interface=os.environ["DAQ_RECEIVER_INTERFACE"],
        receiver_ip=os.environ["DAQ_RECEIVER_IP"],
        receiver_ports=os.environ["DAQ_RECEIVER_PORTS"],
    )
    port = os.getenv("DAQ_GRPC_PORT", default="50051")

    run_server_forever(handler, int(port))


if __name__ == "__main__":
    main()
