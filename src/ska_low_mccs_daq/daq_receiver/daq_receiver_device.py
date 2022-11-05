# -*- coding: utf-8 -*-
#
# This file is part of the SKA SAT.LMC project
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.

"""This module implements the MccsDaqReceiver device."""

from __future__ import annotations  # allow forward references in type hints

import json
import logging
from typing import Any, Optional, cast

import tango
from ska_control_model import CommunicationStatus, HealthState
from ska_tango_base.base import SKABaseDevice
from ska_tango_base.commands import (
    DeviceInitCommand,
    FastCommand,
    ResultCode,
    SubmittedSlowCommand,
)
from tango.server import command, device_property

from ska_low_mccs_daq.daq_receiver.daq_component_manager import DaqComponentManager
from ska_low_mccs_daq.daq_receiver.daq_health_model import DaqHealthModel

__all__ = ["MccsDaqReceiver", "main"]

DevVarLongStringArrayType = tuple[list[ResultCode], list[Optional[str]]]


class MccsDaqReceiver(SKABaseDevice):
    """An implementation of a MccsDaqReceiver Tango device."""

    # -----------------
    # Device Properties
    # -----------------
    ReceiverInterface = device_property(
        dtype=str,
        mandatory=False,
        doc="The interface on which the DAQ receiver is listening for traffic.",
        default_value="",
    )
    ReceiverIp = device_property(
        dtype=str,
        mandatory=True,
        doc="The IP address this DAQ receiver is monitoring.",
    )
    ReceiverPorts = device_property(
        dtype=str,
        doc="The port/s this DaqReceiver is monitoring.",
        default_value="4660",
    )
    DaqId = device_property(
        dtype=int, doc="The ID of this DaqReceiver device.", default_value=0
    )
    ConsumersToStart = device_property(
        dtype=str, doc="The default consumer list to start.", default_value=""
    )

    # ---------------
    # Initialisation
    # ---------------
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialise this device object.

        :param args: positional args to the init
        :param kwargs: keyword args to the init
        """
        # We aren't supposed to define initialisation methods for Tango
        # devices; we are only supposed to define an `init_device` method. But
        # we insist on doing so here, just so that we can define some
        # attributes, thereby stopping the linters from complaining about
        # "attribute-defined-outside-init" etc. We still need to make sure that
        # `init_device` re-initialises any values defined in here.
        super().__init__(*args, **kwargs)

        self._health_state: HealthState = HealthState.UNKNOWN
        self._health_model: DaqHealthModel

    def init_device(self: MccsDaqReceiver) -> None:
        """
        Initialise the device.

        This is overridden here to change the Tango serialisation model.
        """
        util = tango.Util.instance()
        util.set_serial_model(tango.SerialModel.NO_SYNC)
        self._max_workers = 1
        super().init_device()

    def _init_state_model(self: MccsDaqReceiver) -> None:
        """Initialise the state model."""
        super()._init_state_model()
        self._health_state = HealthState.UNKNOWN  # InitCommand.do() does this too late.
        self._health_model = DaqHealthModel(self._component_state_changed_callback)
        self.set_change_event("healthState", True, False)

    def create_component_manager(self: MccsDaqReceiver) -> DaqComponentManager:
        """
        Create and return a component manager for this device.

        :return: a component manager for this device.
        """
        return DaqComponentManager(
            self.DaqId,
            self.ReceiverInterface,
            self.ReceiverIp,
            self.ReceiverPorts,
            self.ConsumersToStart,
            self.logger,
            self._max_workers,
            self._component_communication_state_changed,
            self._component_state_changed_callback,
        )

    def init_command_objects(self: MccsDaqReceiver) -> None:
        """Initialise the command handlers for commands supported by this device."""
        super().init_command_objects()

        for (command_name, command_object) in [
            ("Configure", self.ConfigureCommand),
            ("SetConsumers", self.SetConsumersCommand),
        ]:
            self.register_command_object(
                command_name,
                command_object(self.component_manager, self.logger),
            )

        for (command_name, method_name) in [
            ("Start", "start_daq"),
            ("Stop", "stop_daq"),
        ]:
            self.register_command_object(
                command_name,
                SubmittedSlowCommand(
                    command_name,
                    self._command_tracker,
                    self.component_manager,
                    method_name,
                    callback=None,
                    logger=self.logger,
                ),
            )

    # pylint: disable=too-few-public-methods
    class InitCommand(DeviceInitCommand):
        """Implements device initialisation for the MccsDaqReceiver device."""

        def do(
            self: MccsDaqReceiver.InitCommand,
            *args: Any,
            **kwargs: Any,
        ) -> tuple[ResultCode, str]:  # type: ignore[override]
            """
            Initialise the attributes and properties.

            :param args: Positional arg list.
            :param kwargs: Keyword arg list.

            :return: A tuple containing a return code and a string
                message indicating status. The message is for
                information purpose only.
            """
            # TODO
            return (ResultCode.OK, "Init command completed OK")

    # ----------
    # Callbacks
    # ----------
    def _component_communication_state_changed(
        self: MccsDaqReceiver,
        communication_state: CommunicationStatus,
    ) -> None:
        """
        Handle change in communications status between component manager and component.

        This is a callback hook, called by the component manager when
        the communications status changes. It is implemented here to
        drive the op_state.

        :param communication_state: the status of communications
            between the component manager and its component.
        """
        action_map = {
            CommunicationStatus.DISABLED: "component_disconnected",
            CommunicationStatus.NOT_ESTABLISHED: "component_unknown",
            CommunicationStatus.ESTABLISHED: "component_on",
        }

        action = action_map[communication_state]
        if action is not None:
            self.op_state_model.perform_action(action)

        self._health_model.is_communicating(
            communication_state == CommunicationStatus.ESTABLISHED
        )

    def _component_state_changed_callback(
        self: MccsDaqReceiver,
        state_change: dict[str, Any],
    ) -> None:
        """
        Handle change in the state of the component.

        This is a callback hook, called by the component manager when
        the state of the component changes.

        :param state_change: state change parameters.
        """
        if "fault" in state_change.keys():
            is_fault = state_change.get("fault")
            if is_fault:
                self.op_state_model.perform_action("component_fault")
                self._health_model.component_fault(True)
            else:
                self._health_model.component_fault(False)

        if "health_state" in state_change.keys():
            health = state_change.get("health_state")
            if self._health_state != health:
                self._health_state = cast(HealthState, health)
                self.push_change_event("healthState", health)

    # ----------
    # Attributes
    # ----------

    # def is_attribute_allowed(
    #     self: MccsDaqReceiver, attr_req_type: tango.AttReqType
    # ) -> bool:
    #     """
    #     Protect attribute access before being updated otherwise it reports alarm.

    #     :param attr_req_type: tango attribute type READ/WRITE

    #     :return: True if the attribute can be read else False
    #     """
    #     rc = self.get_state() in [
    #         tango.DevState.ON,
    #     ]
    #     return rc

    # @attribute(
    #     dtype=int,
    #     label="label",
    #     unit="unit",
    #     standard_unit="unit",
    #     max_alarm=90,
    #     min_alarm=1,
    #     max_warn=80,
    #     min_warn=5,
    #     fisallowed=is_attribute_allowed,
    # )
    # def some_attribute(self: XXXXXX) -> int:
    #     """
    #     Return some_attribute.

    #     :return: some_attribute
    #     """
    #     return self._component_manager._some_attribute

    # --------
    # Commands
    # --------
    @command(dtype_in="DevString", dtype_out="DevVarLongStringArray")
    def Start(self: MccsDaqReceiver, argin: str = "") -> DevVarLongStringArrayType:
        """
        Start the DaqConsumers.

        The MccsDaqReceiver will begin watching the interface specified in the
        configuration and will start the configured consumers.

        :param argin: JSON-formatted string representing the DaqModes and their
            corresponding callbacks to start, defaults to None.

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        handler = self.get_command_object("Start")
        if argin != "":
            params = json.loads(argin)

        # Initialise temps and extract individual args from argin.
        modes_to_start = None
        callbacks = None

        if "modes_to_start" in params.keys():
            modes_to_start = params["modes_to_start"]
        if "callbacks" in params.keys():
            callbacks = params["callbacks"]

        (result_code, message) = handler(modes_to_start, callbacks)
        return ([result_code], [message])

    @command(dtype_out="DevVarLongStringArray")
    def Stop(self: MccsDaqReceiver) -> DevVarLongStringArrayType:
        """
        Stop the DaqReceiver.

        The DAQ receiver will cease watching the specified interface
        and will stop all running consumers.

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        handler = self.get_command_object("Stop")
        (result_code, message) = handler()
        return ([result_code], [message])

    # pylint: disable=too-few-public-methods
    class ConfigureCommand(FastCommand):
        """Class for handling the Configure(argin) command."""

        def __init__(  # type: ignore
            self: MccsDaqReceiver.ConfigureCommand,
            component_manager,
            logger: Optional[logging.Logger] = None,
        ) -> None:
            """
            Initialise a new ConfigureCommand instance.

            :param component_manager: the device to which this command belongs.
            :param logger: a logger for this command to use.
            """
            self._component_manager = component_manager
            super().__init__(logger)

        # pylint: disable=arguments-differ
        def do(  # type: ignore[override]
            self: MccsDaqReceiver.ConfigureCommand,
            argin: dict[str, Any],
        ) -> tuple[ResultCode, str]:
            """
            Implement MccsDaqReceiver.ConfigureCommand command functionality.

            :param argin: A configuration dictionary.

            :return: A tuple containing a return code and a string
                message indicating status. The message is for
                information purpose only.
            """
            self._component_manager.configure_daq(argin)
            return (ResultCode.OK, "Configure command completed OK")

    # Args in might want to be changed depending on how we choose to
    # configure the DAQ system.
    @command(dtype_in="DevString", dtype_out="DevVarLongStringArray")
    def Configure(self: MccsDaqReceiver, argin: str) -> DevVarLongStringArrayType:
        """
        Configure the DaqReceiver.

        Applies the specified configuration to the DaqReceiver.

        :param argin: The daq configuration to apply.
        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        handler = self.get_command_object("Configure")
        (result_code, message) = handler(argin)
        return ([result_code], [message])

    # pylint: disable=too-few-public-methods
    class SetConsumersCommand(FastCommand):
        """Class for handling the SetConsumersCommand(argin) command."""

        def __init__(  # type: ignore
            self: MccsDaqReceiver.SetConsumersCommand,
            component_manager,
            logger: Optional[logging.Logger] = None,
        ) -> None:
            """
            Initialise a new SetConsumersCommand instance.

            :param component_manager: the device to which this command belongs.
            :param logger: a logger for this command to use.
            """
            self._component_manager = component_manager
            super().__init__(logger)

        # pylint: disable=arguments-differ
        def do(  # type: ignore[override]
            self: MccsDaqReceiver.SetConsumersCommand, argin: str
        ) -> tuple[ResultCode, str]:
            """
            Implement MccsDaqReceiver.SetConsumersCommand command functionality.

            :param argin: A configuration dictionary.
            :return: A tuple containing a return code and a string
                message indicating status. The message is for
                information purpose only.
            """
            self._component_manager._set_consumers_to_start(argin)
            return (ResultCode.OK, "SetConsumers command completed OK")

    @command(dtype_in="DevString", dtype_out="DevVarLongStringArray")
    def SetConsumers(self: MccsDaqReceiver, argin: str) -> DevVarLongStringArrayType:
        """
        Set the default list of consumers to start.

        Sets the default list of consumers to start when left unspecified in
        the `start_daq` command.

        :param argin: The daq configuration to apply.
        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        handler = self.get_command_object("SetConsumers")
        (result_code, message) = handler(argin)
        return ([result_code], [message])

    # @command(dtype_in="DevString", dtype_out="DevVarLongStringArray")
    # def Command(self: XXXXXX, argin: str) -> DevVarLongStringArrayType:
    #     """"""
    #     handler = self.get_command_object("Command")
    #     (result_code, message) = handler(argin)
    #     return ([result_code], [message])


# ----------
# Run server
# ----------
def main(*args: str, **kwargs: str) -> int:  # pragma: no cover
    """
    Entry point for module.

    :param args: positional arguments
    :param kwargs: named arguments

    :return: exit code
    """
    return MccsDaqReceiver.run_server(args=args or None, **kwargs)


if __name__ == "__main__":
    main()
