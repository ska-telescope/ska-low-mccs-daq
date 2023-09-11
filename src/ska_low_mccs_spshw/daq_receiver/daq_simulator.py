# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.
"""
This module implements a simple DAQ receiver.

It exists to allow MccsDaqReceiver to be unit tested.
"""
from __future__ import annotations

import functools
import os
from enum import IntEnum
from typing import Any, Callable, Iterator, TypeVar, cast

from ska_control_model import ResultCode
from ska_low_mccs_daq_interface import run_server_forever

__all__ = ["DaqSimulator"]

Wrapped = TypeVar("Wrapped", bound=Callable[..., Any])


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
        self: DaqSimulator,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Check for component initialisation before calling the function.

        This is a wrapper function that implements the functionality of
        the decorator.

        :param self: This instance of an DaqSimulator.
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


# TODO: Redefined for now, to avoid having to import from pydaq.
# This really should not be exposed through the control interface at all.
class DaqModes(IntEnum):
    """Data acquisition modes."""

    RAW_DATA = 0
    CHANNEL_DATA = 1
    BEAM_DATA = 2
    CONTINUOUS_CHANNEL_DATA = 3
    INTEGRATED_BEAM_DATA = 4
    INTEGRATED_CHANNEL_DATA = 5
    STATION_BEAM_DATA = 6
    CORRELATOR_DATA = 7
    ANTENNA_BUFFER = 8


def convert_daq_modes(consumers_to_start: str) -> list[DaqModes]:
    """
    Convert a string representation of DaqModes into a list of DaqModes.

    Breaks a comma separated list into a list of words,
        strips whitespace and extracts the `enum` part and casts the string
        into a DaqMode or directly cast an int into a DaqMode.

    :param consumers_to_start: A string containing a comma separated
        list of DaqModes.

    :return: a converted list of DaqModes or an empty
        list if no consumers supplied.
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


class DaqSimulator:
    """An implementation of a DaqSimulator device."""

    def __init__(self: DaqSimulator):
        """Initialise this device."""
        self._initialised = False

        self._config = {
            "observation_metadata": "foo",
            "receiver_ports": "bah",
        }

        self._modes: list[DaqModes] = []

    def initialise(
        self: DaqSimulator, config: dict[str, Any]
    ) -> tuple[ResultCode, str]:
        """
        Initialise a new DaqReceiver instance.

        :param config: the configuration to apply

        :return: a resultcode, message tuple
        """
        if self._initialised:
            return ResultCode.REJECTED, "Daq already initialised"
        self._config.update(config)
        self._initialised = True
        return ResultCode.OK, "Daq successfully initialised"

    @property
    def initialised(self: DaqSimulator) -> bool:
        """
        Return whether the simulated DAQ is initialised.

        :return: whether the simulated DAQ is initialised.
        """
        return self._initialised

    @check_initialisation
    def start(
        self: DaqSimulator,
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
        self._modes = convert_daq_modes(modes_to_start)
        yield "LISTENING"

        def received_file_buffer() -> Any:
            """
            DAQ has written a file.

            :yield: metadata about file.
            """
            yield (
                "data_type",
                "file_name",
                "json_serialised_metadata_dict",
            )

        yield from received_file_buffer()
        # yield somethin' else
        yield "STOPPED"

    @check_initialisation
    def stop(self: DaqSimulator) -> tuple[ResultCode, str]:
        """
        Stop data acquisition.

        :return: a resultcode, message tuple
        """
        self._modes = []
        return ResultCode.OK, "Daq stopped"

    @check_initialisation
    def configure(
        self: DaqSimulator, config: dict[str, Any]
    ) -> tuple[ResultCode, str]:  # noqa: E501
        """
        Apply a configuration to the DaqReceiver.

        :param config: the configuration to apply

        :return: a resultcode, message tuple
        """
        if config:
            self._config.update(config)
            return ResultCode.OK, "Daq reconfigured"
        return ResultCode.REJECTED, "No configuration data supplied."

    @check_initialisation
    def get_configuration(
        self: DaqSimulator,
    ) -> dict[str, Any]:
        """
        Retrieve the current DAQ configuration.

        :return: a configuration dictionary.
        """
        config = self._config.copy()
        try:
            port = int(config["receiver_ports"])
        except ValueError:
            pass
        except TypeError:
            ports = [str(port) for port in config["receiver_ports"]]
            config["receiver_ports"] = "[" + ",".join(ports) + "]"
        else:
            config["receiver_ports"] = f"[{port}]"
        return config

    @check_initialisation
    def get_status(self: DaqSimulator) -> dict[str, Any]:
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
        running_consumers = [[mode.name, int(mode)] for mode in self._modes]
        return {
            "Running Consumers": running_consumers,
            "Receiver Interface": self._config.get("receiver_interface", 0),
            "Receiver Ports": self._config.get("receiver_ports", ""),
            "Receiver IP": [self._config.get("receiver_ip", "")],
        }


def main() -> None:
    """Entry point for a gRPC server that fronts a DAQ simulator."""
    daq_simulator = DaqSimulator()

    port = int(os.getenv("DAQ_SIMULATOR_PORT", "50051"))
    run_server_forever(daq_simulator, port)


if __name__ == "__main__":
    main()
