# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module implements component management for DaqReceivers."""
from __future__ import annotations

import logging
import threading
import warnings
from typing import Any, Callable, Optional, Sequence, Union

from pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from ska_control_model import CommunicationStatus, TaskStatus
from ska_low_mccs_common.component import MccsComponentManager, check_communicating

__all__ = ["DaqComponentManager"]


# pylint: disable=abstract-method
class DaqComponentManager(MccsComponentManager):
    """A component manager for a DaqReceiver."""

    # pylint: disable=too-many-arguments
    def __init__(
        self: DaqComponentManager,
        daq_id: int,
        receiver_interface: str,
        receiver_ip: str,
        receiver_ports: str,
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
        """
        self._consumers_to_start: list[DaqModes] | None

        super().__init__(
            logger,
            max_workers,
            communication_state_changed_callback,
            component_state_changed_callback,
        )
        self._receiver_started: bool = False
        self._daq_id = daq_id
        self._receiver_interface = receiver_interface
        self._receiver_ip = receiver_ip.encode()
        self._receiver_ports = receiver_ports
        self._received_data_callback = received_data_callback
        self._set_consumers_to_start(consumers_to_start)
        self._create_daq_instance()

    def _create_daq_instance(
        self: DaqComponentManager,
    ) -> None:
        """
        Create and initialise a DAQ instance.

        This method creates a DAQ instance and initialises it before
        returning.
        """
        self.logger.info("Creating, configuring and initialising DAQ receiver.")
        # Create DAQ instance
        self.daq_instance = DaqReceiver()

        # TODO: `initialise_daq` starts the daq receiver rather than `start_daq`.
        # `stop_daq` stops the daq receiver.
        # This means we can't stop the receiver and start it on a new interface unless
        # we re-init the device which is suboptimal.
        # It would be better if we could start the receiver in `start_daq` without
        # having to initialise/reinitialise the entire daq system.
        try:
            self.configure_daq(self._get_daq_config())
        # pylint: disable=broad-except
        except Exception as e:
            self.logger.error(f"Caught exception in `_create_daq_instance`: {e}")

        # Initialise library and start receiver.
        self.daq_instance.initialise_daq()
        self._receiver_started = True
        self.logger.info("Daq receiver created and initialised.")

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

    def _get_daq_config(self: DaqComponentManager) -> dict[str, Any]:
        """
        Retrieve and return a DAQ configuration.

        :return: A DAQ configuration.
        """
        # Read config from wherever we'll keep it (yaml/json?) then return it.
        # For now just return whatever config is useful for testing.
        # Anything not specified here will revert to default settings.

        # TODO: Might want to put some type checking in here for IP addresses and such
        # so that we don't store and (try to) apply an unusable configuration.

        daq_config = {
            "nof_tiles": 2,
            "receiver_ports": self._receiver_ports,
            "receiver_interface": self._receiver_interface,
            "receiver_ip": self._receiver_ip,
            "directory": ".",
            "acquisition_duration": -1,
        }
        return daq_config

    def get_configuration(self: DaqComponentManager) -> dict[str, Any]:
        """
        Get configuration from DAQ.

        :return: The configuration in the pydaq instance.
        """
        return self.daq_instance.get_configuration()

    def _get_consumers_to_start(self: DaqComponentManager) -> list[DaqModes]:
        """
        Retrieve a list of DAQ consumers to start.

        Returns the consumer list that is to be used when `start_daq` is called without
        specifying consumers. This is empty by default and if not set will return
        `[DaqModes.INTEGRATED_CHANNEL_DATA]`.

        :return: a list of DAQ modes.
        """
        if self._consumers_to_start is None:
            return [DaqModes.INTEGRATED_CHANNEL_DATA]
        return self._consumers_to_start

    def _set_consumers_to_start(
        self: DaqComponentManager, consumers_to_start: str
    ) -> None:
        """
        Set default consumers to start.

        Set consumers to be started when `start_daq` is called without specifying a
        consumer.

        :param consumers_to_start: A string containing a comma separated
            list of DaqModes.
        """
        try:
            if consumers_to_start != "":
                # Extract consumers_to_start and convert to DaqModes if supplied.
                consumer_list = consumers_to_start.split(
                    ","
                )  # Separate string into list of words.
                # Strip whitespace, extract the enum part of the consumer
                # (e.g. RAW_DATA) and cast into a DaqMode.
                self._consumers_to_start = [
                    DaqModes[consumer.strip().split(".")[-1]]
                    for consumer in consumer_list
                ]
            else:
                self._consumers_to_start = None
        # pylint: disable=broad-except
        except Exception as e:
            self.logger.error(
                f"Unhandled exception caught in `_set_consumers_to_start`: {e}"
            )
            self._consumers_to_start = None

    def configure_daq(
        self: DaqComponentManager,
        daq_config: dict[str, Any],
    ) -> None:
        """
        Apply a configuration to the DaqReceiver.

        :param daq_config: A dictionary containing configuration settings.
        """
        self.logger.info("Configuring DAQ receiver.")
        try:
            self.daq_instance.populate_configuration(daq_config)
        # pylint: disable=broad-except
        except Exception as e:
            self.logger.error(f"Exception caught in `configure_daq`: {e}")
        # if not self._validate_daq_configuration(daq_config):
        #     self.logger.warning("DAQ configuration could not be validated!")
        # TODO: Raise some exception here? How do we want to deal with this?
        self.logger.info("DAQ receiver configuration complete.")

    @check_communicating
    def start_daq(
        self: DaqComponentManager,
        modes_to_start: Optional[list[DaqModes]] = None,
        callbacks: Optional[Sequence[Callable]] = None,
        task_callback: Optional[Callable] = None,
    ) -> tuple[TaskStatus, str]:
        """
        Submit start data acquisition task with the current configuration.

        Extracts the required consumers from configuration and starts
        them.

        :param modes_to_start: The DAQ consumers to start.
        :param callbacks: The callbacks to pass to DAQ to be called when a buffer is
            filled. One callback per DAQ mode. Callbacks will be associated with the
            corresponding mode_to_start. e.g. callbacks[i] will be called when
            modes_to_start[i] has a full buffer.
        :param task_callback: Update task state, defaults to None

        :return: a task status and response message
        """
        self.logger.info("Submitting `_start_daq` task.")
        return self.submit_task(
            self._start_daq,
            args=[modes_to_start],
            task_callback=task_callback,
        )

    @check_communicating
    def _start_daq(
        self: DaqComponentManager,
        modes_to_start: Optional[list[Union[int, DaqModes]]] = None,
        task_callback: Optional[Callable] = None,
        task_abort_event: Union[threading.Event, None] = None,
    ) -> None:
        """
        Start data acquisition with the current configuration.

        Extracts the required consumers from configuration and starts
        them.

        :param modes_to_start: The DAQ consumers to start.
        :param callbacks: The callbacks to pass to DAQ to be called when a buffer is
            filled. One callback per DAQ mode. Callbacks will be associated with the
            corresponding mode_to_start. e.g. callbacks[i] will be called when
            modes_to_start[i] has a full buffer.
        :param task_callback: Update task state, defaults to None
        :param task_abort_event: Abort the task
        """
        if not self._receiver_started:
            self.daq_instance.initialise_daq()
            self._receiver_started = True
        if task_callback:
            task_callback(status=TaskStatus.IN_PROGRESS)
        # Retrieve default list of modes to start if not provided.
        if modes_to_start is None:
            modes_to_start = self._get_consumers_to_start()

        # Provide callback for each mode to start
        if modes_to_start is not None:
            callbacks = [self._received_data_callback] * len(modes_to_start)
        else:
            callbacks = []

        # Cast any ints in modes_to_start to a DaqMode.
        try:
            modes_to_start = [DaqModes(mode) for mode in modes_to_start]
        except ValueError as e:
            self.logger.error(f"Value Error! Invalid DaqMode supplied! {e}")
            if task_callback:
                task_callback(
                    status=TaskStatus.FAILED,
                    message=f"Value Error! Invalid DaqMode supplied! {e}",
                )

        self.logger.info(
            (
                f"Starting DAQ. {self.daq_instance._config['receiver_ip']} "
                "Listening on interface: "
                f"{self.daq_instance._config['receiver_interface']}:"
                f"{self.daq_instance._config['receiver_ports']}"
            )
        )
        self.daq_instance.start_daq(modes_to_start, callbacks)
        if task_callback:
            task_callback(status=TaskStatus.COMPLETED)

    def stop_daq(
        self: DaqComponentManager,
        task_callback: Optional[Callable] = None,
    ) -> tuple[TaskStatus, str]:
        """
        Stop data acquisition.

        Stops the DAQ receiver and all running consumers.

        :param task_callback: Update task state, defaults to None
        :return: a task status and response message
        """
        self.logger.info("Submitting `_stop_daq` task.")
        return self.submit_task(self._stop_daq, args=[], task_callback=task_callback)

    def _stop_daq(
        self: DaqComponentManager,
        task_callback: Optional[Callable] = None,
        task_abort_event: Union[threading.Event, None] = None,
    ) -> None:
        """
        Stop data acquisition.

        Stops the DAQ receiver and all running consumers.

        :param task_callback: Update task state, defaults to None
        :param task_abort_event: Abort the task
        """
        if task_callback:
            task_callback(status=TaskStatus.IN_PROGRESS)
        self.logger.info(
            "Stopping DAQ receiver listening on interface: "
            f"{self.daq_instance._config['receiver_interface']}"
        )
        self.daq_instance.stop_daq()
        self._receiver_started = False
        if task_callback:
            task_callback(status=TaskStatus.COMPLETED)
