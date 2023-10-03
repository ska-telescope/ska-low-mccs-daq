# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.
"""This module implements the DaqServer part of the MccsDaqReceiver device."""
from __future__ import annotations

import functools
import json
import logging
import os
from enum import IntEnum
from typing import Any, Callable, Iterator, List, Optional, TypeVar, cast

import numpy as np
from pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from ska_control_model import ResultCode
from ska_low_mccs_daq_interface.server import run_server_forever

__all__ = ["DaqHandler", "main"]

Wrapped = TypeVar("Wrapped", bound=Callable[..., Any])


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
        self.logger = logging.getLogger("daq-server")
        self.state = DaqStatus.STOPPED
        self.request_stop = False
        self.buffer = DaqCallbackBuffer(self.logger)
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

    def _file_dump_callback(
        self: DaqHandler,
        data_mode: str,
        file_name: str,
        additional_info: Optional[int] = None,
    ) -> None:
        """
        Add metadata to buffer.

        :param data_mode: The DAQ data type written
        :param file_name: The filename written
        :param additional_info: Any additional information.
        """
        # We don't have access to the timestamp here so this will retrieve the most
        # recent match
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


def main() -> None:
    """
    Entrypoint for the module.

    Create and start a server.
    """
    port = os.getenv("DAQ_GRPC_PORT", default="50051")
    run_server_forever(DaqHandler(), int(port))


if __name__ == "__main__":
    main()
