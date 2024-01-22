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
from typing import Any, Optional, Union, cast

import numpy as np
from ska_control_model import CommunicationStatus, HealthState, ResultCode
from ska_tango_base.base import BaseComponentManager, SKABaseDevice
from ska_tango_base.commands import (
    CommandTrackerProtocol,
    DeviceInitCommand,
    FastCommand,
    SubmittedSlowCommand,
)
from tango.server import attribute, command, device_property

from ..version import version_info
from .daq_component_manager import DaqComponentManager
from .daq_health_model import DaqHealthModel

__all__ = ["MccsDaqReceiver", "main"]

DevVarLongStringArrayType = tuple[list[ResultCode], list[Optional[str]]]


class _StartDaqCommand(SubmittedSlowCommand):
    """
    Class for handling the Start command.

    This command starts the DAQ device
    to listen for UDP traffic on a specific interface.
    """

    def __init__(
        self: _StartDaqCommand,
        command_tracker: CommandTrackerProtocol,
        component_manager: BaseComponentManager,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialise a new instance.

        :param command_tracker: the device's command tracker
        :param component_manager: the component manager on which this
            command acts.
        :param logger: a logger for this command to use.
        """
        super().__init__(
            "Start",
            command_tracker,
            component_manager,
            "start_daq",
            callback=None,
            logger=logger,
        )

    def do(  # type: ignore[override]
        self: _StartDaqCommand,
        *args: Any,
        modes_to_start: str = "",
        **kwargs: Any,
    ) -> tuple[ResultCode, str]:
        """
        Implement :py:meth:`.MccsDaqReceiver.Start` command.

        :param args: unspecified positional arguments. This should be
            empty and is provided for typehinting purposes only.
        :param modes_to_start: A DAQ mode, must be a string
        :param kwargs: unspecified keyword arguments. This should be
            empty and is provided for typehinting purposes only.

        :return: A tuple containing a return code and a string
                message indicating status. The message is for
                information purpose only.
        """
        assert (
            not args and not kwargs
        ), f"do method has unexpected arguments: {args}, {kwargs}"

        return super().do(modes_to_start)


class _StartBandpassMonitorCommand(SubmittedSlowCommand):
    """
    Start monitoring antenna bandpasses.

        The MccsDaqReceiver will begin monitoring antenna bandpasses
            and producing plots of the spectra.

        :param argin: A json dictionary with keywords.
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
        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
    """

    def __init__(
        self: _StartBandpassMonitorCommand,
        command_tracker: CommandTrackerProtocol,
        component_manager: BaseComponentManager,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialise a new instance.

        :param command_tracker: the device's command tracker
        :param component_manager: the component manager on which this
            command acts.
        :param logger: a logger for this command to use.
        """
        super().__init__(
            "StartBandpassMonitor",
            command_tracker,
            component_manager,
            "start_bandpass_monitor",
            callback=None,
            logger=logger,
        )

    # pylint: disable = arguments-differ
    def do(  # type: ignore[override]
        self: _StartBandpassMonitorCommand,
        *args: Any,
        argin: str,
        **kwargs: Any,
    ) -> tuple[ResultCode, str]:
        """
        Implement :py:meth:`.MccsDaqReceiver.StartBandpassMonitor` command.

        :param args: unspecified positional arguments. This should be
            empty and is provided for typehinting purposes only.
        :param argin: A json dictionary with keywords.
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
        :param kwargs: unspecified keyword arguments. This should be
            empty and is provided for typehinting purposes only.

        :return: A tuple containing a return code and a string
                message indicating status. The message is for
                information purpose only.
        """
        assert (
            not args and not kwargs
        ), f"do method has unexpected arguments: {args}, {kwargs}"

        return super().do(argin)


# pylint: disable = too-many-instance-attributes
class MccsDaqReceiver(SKABaseDevice):
    """An implementation of a MccsDaqReceiver Tango device."""

    # -----------------
    # Device Properties
    # -----------------
    ReceiverInterface = device_property(
        dtype=str,
        mandatory=False,
        # pylint: disable-next=line-too-long
        doc="The interface on which the DAQ receiver is listening for traffic.",  # noqa: E501
        default_value="",
    )
    # TODO: Remove ReceiverIp property?
    ReceiverIp = device_property(
        dtype=str,
        mandatory=False,
        doc="The IP address this DAQ receiver is monitoring.",
        default_value="",
    )
    ReceiverPorts = device_property(
        dtype=str,
        doc="The port/s this DaqReceiver is monitoring.",
        default_value="4660",
    )
    Host = device_property(
        dtype=str, doc="The host for communication with the DAQ receiver."
    )
    Port = device_property(
        dtype=str,
        doc="The port for communication with the DAQ receiver.",
        default_value=50051,
    )
    DaqId = device_property(
        dtype=int, doc="The ID of this DaqReceiver device.", default_value=0
    )
    ConsumersToStart = device_property(
        dtype=str, doc="The default consumer list to start.", default_value=""
    )
    SkuidUrl = device_property(
        dtype=str,
        doc="The location of a running SKUID service.",
        default_value="",
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
        self._received_data_mode: str
        self._received_data_result: str
        self._x_bandpass_plot: np.ndarray
        self._y_bandpass_plot: np.ndarray
        self._rms_plot: np.ndarray
        self._skuid_url: str

    def init_device(self: MccsDaqReceiver) -> None:
        """
        Initialise the device.

        This is overridden here to change the Tango serialisation model.
        """
        self._max_workers = 5
        super().init_device()

        self._build_state = ",".join(
            [
                version_info["name"],
                version_info["version"],
                version_info["description"],
            ]
        )
        self._version_id = version_info["version"]

        device_name = f'{str(self.__class__).rsplit(".",maxsplit=1)[-1][0:-2]}'
        version = f"{device_name} Software Version: {self._version_id}"
        properties = (
            f"Initialised {device_name} device with properties:\n"
            f"\tReceiverInterface: {self.ReceiverInterface}\n"
            f"\tReceiverIp: {self.ReceiverIp}\n"
            f"\tReceiverPorts: {self.ReceiverPorts}\n"
            f"\tHost: {self.Host}\n"
            f"\tPort: {self.Port}\n"
            f"\tDaqId: {self.DaqId}\n"
            f"\tConsumersToStart: {self.ConsumersToStart}\n"
            f"\tSkuidUrl: {self.SkuidUrl}\n"
        )
        self.logger.info(
            "\n%s\n%s\n%s", str(self.GetVersionInfo()), version, properties
        )

    def _init_state_model(self: MccsDaqReceiver) -> None:
        """Initialise the state model."""
        super()._init_state_model()
        self._health_state = (
            HealthState.UNKNOWN
        )  # InitCommand.do() does this too late.# noqa: E501
        self._health_model = DaqHealthModel(self._component_state_callback)
        self._received_data_mode = ""
        self._received_data_result = ""
        self._x_bandpass_plot = np.zeros(shape=(256, 511), dtype=float)
        self._y_bandpass_plot = np.zeros(shape=(256, 511), dtype=float)
        self._rms_plot = np.zeros(shape=(256, 511), dtype=float)
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
            f"{self.Host}:{self.Port}",
            self.ConsumersToStart,
            self.SkuidUrl,
            self.logger,
            self._max_workers,
            self._component_communication_state_changed,
            self._component_state_callback,
            self._received_data_callback,
        )

    def init_command_objects(self: MccsDaqReceiver) -> None:
        # pylint: disable-next=line-too-long
        """Initialise the command handlers for commands supported by this device."""  # noqa: E501
        super().init_command_objects()

        for command_name, command_object in [
            ("Configure", self.ConfigureCommand),
            ("SetConsumers", self.SetConsumersCommand),
            ("DaqStatus", self.DaqStatusCommand),
            ("GetConfiguration", self.GetConfigurationCommand),
            ("Stop", self.StopCommand),
            # ("StartBandpassMonitor", self.StartBandpassMonitorCommand),
            ("StopBandpassMonitor", self.StopBandpassMonitorCommand),
        ]:
            self.register_command_object(
                command_name,
                command_object(self.component_manager, self.logger),
            )

        for command_name, command_class in [
            ("Start", _StartDaqCommand),
            ("StartBandpassMonitor", _StartBandpassMonitorCommand),
        ]:
            self.register_command_object(
                command_name,
                command_class(
                    self._command_tracker,
                    self.component_manager,
                    logger=self.logger,
                ),
            )

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
            self._device.set_change_event("dataReceivedResult", True, False)
            self._device.set_change_event("xPolBandpass", True, False)
            self._device.set_change_event("yPolBandpass", True, False)
            self._device.set_change_event("rmsPlot", True, False)

            # Archived attributes should be logged to the EDA eventually.
            self._device.set_archive_event("xPolBandpass", True, False)
            self._device.set_archive_event("yPolBandpass", True, False)
            self._device.set_archive_event("rmsPlot", True, False)

            return (ResultCode.OK, "Init command completed OK")

    # ----------
    # Callbacks
    # ----------
    def _component_communication_state_changed(
        self: MccsDaqReceiver,
        communication_state: CommunicationStatus,
    ) -> None:
        """
        Handle change in communication between component manager and component.

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

    # pylint: disable = too-many-arguments
    def _component_state_callback(
        self: MccsDaqReceiver,
        fault: Optional[bool] = None,
        health: Optional[HealthState] = None,
        x_bandpass_plot: Optional[np.ndarray] = None,
        y_bandpass_plot: Optional[np.ndarray] = None,
        rms_plot: Optional[np.ndarray] = None,
        **kwargs: Optional[Any],
    ) -> None:
        """
        Handle change in the state of the component.

        This is a callback hook, called by the component manager when
        the state of the component changes.

        :param fault: New fault state of device.
        :param health: New health state of device.
        :param x_bandpass_plot: A filepath for a bandpass plot.
        :param y_bandpass_plot: A filepath for a bandpass plot.
        :param rms_plot: A filepath for an rms plot.
        :param kwargs: Other state changes of device.
        """
        if fault:
            self.op_state_model.perform_action("component_fault")
            self._health_model.component_fault(True)
        elif fault is False:
            self._health_model.component_fault(False)

        if health is not None:
            if self._health_state != health:
                self._health_state = cast(HealthState, health)
                self.push_change_event("healthState", health)

        if x_bandpass_plot is not None:
            if isinstance(x_bandpass_plot, list):
                x_bandpass_plot = x_bandpass_plot[0]
            self._x_bandpass_plot = x_bandpass_plot
            # TODO: Should we be pushing these
            # events with self.x_bandpass_plot?
            self.push_change_event("xPolBandpass", x_bandpass_plot)
            self.push_archive_event("xPolBandpass", x_bandpass_plot)

        if y_bandpass_plot is not None:
            if isinstance(y_bandpass_plot, list):
                y_bandpass_plot = y_bandpass_plot[0]
            self._y_bandpass_plot = y_bandpass_plot
            self.push_change_event("yPolBandpass", y_bandpass_plot)
            self.push_archive_event("yPolBandpass", y_bandpass_plot)

        if rms_plot is not None:
            if isinstance(rms_plot, list):
                rms_plot = rms_plot[0]
            self._rms_plot = rms_plot
            self.push_change_event("rmsPlot", rms_plot)
            self.push_archive_event("rmsPlot", rms_plot)

    def _received_data_callback(
        self: MccsDaqReceiver,
        data_mode: str,
        file_name: str,
        metadata: str,
    ) -> None:
        """
        Handle the receiving of data from a tile.

        This will be called by pydaq when data is received from a tile

        :param data_mode: the DaqMode in which data was received.
        :param file_name: the name of the file that the data was saved to
        :param metadata: the metadata for the data received
        """
        self.logger.info(
            "Data of type %s has been written to file %s", data_mode, file_name
        )
        metadata_dict = json.loads(metadata)
        event_value: dict[str, Union[str, int]] = {
            "data_mode": data_mode,
            "file_name": file_name,
            "metadata": metadata_dict,
        }
        if "additional_info" in metadata_dict:
            if data_mode == "station":
                event_value["amount_of_data"] = metadata_dict["additional_info"]
            elif data_mode != "correlator":
                event_value["tile"] = metadata_dict["additional_info"]

        result = json.dumps(event_value)
        if (
            self._received_data_mode != data_mode
            or self._received_data_result != result
        ):
            self._received_data_mode = data_mode
            self._received_data_result = result
            self.push_change_event(
                "dataReceivedResult",
                (self._received_data_mode, self._received_data_result),
            )

    # --------
    # Commands
    # --------
    class DaqStatusCommand(FastCommand):
        """A class for the MccsDaqReceiver's DaqStatus() command."""

        def __init__(  # type: ignore
            self: MccsDaqReceiver.DaqStatusCommand,
            component_manager,
            logger: Optional[logging.Logger] = None,
        ) -> None:
            """
            Initialise a new instance.

            :param component_manager: the device to which this command belongs.
            :param logger: a logger for this command to use.
            """
            self._component_manager = component_manager
            super().__init__(logger)

        # pylint: disable=arguments-differ
        def do(  # type: ignore[override]
            self: MccsDaqReceiver.DaqStatusCommand,
        ) -> str:
            """
            Stateless hook for device DaqStatus() command.

            :return: The status of this Daq device.
            """
            return self._component_manager.daq_status()

    @command(dtype_out="DevString")
    def DaqStatus(self: MccsDaqReceiver) -> str:
        """
        Provide status information for this MccsDaqReceiver.

        This method returns status as a json string with entries for:
            - Daq Health: [HealthState.name: str, HealthState.value: int]
            - Running Consumers: [DaqMode.name: str, DaqMode.value: int]
            - Receiver Interface: "Interface Name": str
            - Receiver Ports: [Port_List]: list[int]
            - Receiver IP: "IP_Address": str

        :return: A json string containing the status of this DaqReceiver.

        :example:
            >>> daq = tango.DeviceProxy("low-mccs/daqreceiver/001")
            >>> jstr = daq.DaqStatus()
            >>> dict = json.loads(jstr)
        """
        handler = self.get_command_object("DaqStatus")
        # We append health_state to the status here.
        status = json.loads(handler())
        health_state = [self._health_state.name, self._health_state.value]
        status["Daq Health"] = health_state
        return json.dumps(status)

    @command(dtype_in="DevString", dtype_out="DevVarLongStringArray")
    def Start(
        self: MccsDaqReceiver, argin: str = ""
    ) -> DevVarLongStringArrayType:  # noqa: E501
        """
        Start the DaqConsumers.

        The MccsDaqReceiver will begin watching the interface specified in the
            configuration and will start the configured consumers.

        :param argin: A json dictionary with optional keywords.
            '{"modes_to_start"}'.
        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.

        :example:
            >>> daq = tango.DeviceProxy("low-mccs/daqreceiver/001")
            >>> argin = '{"modes_to_start": "INTEGRATED_CHANNEL_DATA,
            RAW_DATA"}'
            >>> daq.Start(argin) # use specified consumers
            >>> daq.Start("") # Uses default consumers.
        """
        if argin != "":
            kwargs = json.loads(argin)
        else:
            kwargs = {}
        handler = self.get_command_object("Start")
        (result_code, message) = handler(**kwargs)
        return ([result_code], [message])

    class StopCommand(FastCommand):
        """Class for handling the Stop() command."""

        def __init__(  # type: ignore
            self: MccsDaqReceiver.StopCommand,
            component_manager,
            logger: Optional[logging.Logger] = None,
        ) -> None:
            """
            Initialise a new StopCommand instance.

            :param component_manager: the device to which this command belongs.
            :param logger: a logger for this command to use.
            """
            self._component_manager = component_manager
            super().__init__(logger)

        # pylint: disable=arguments-differ
        def do(  # type: ignore[override]
            self: MccsDaqReceiver.StopCommand,
        ) -> tuple[ResultCode, str]:
            """
            Implement MccsDaqReceiver.StopCommand command functionality.

            :return: A tuple containing a return code and a string
                message indicating status. The message is for
                information purpose only.
            """
            return self._component_manager.stop_daq()

    @command(dtype_out="DevVarLongStringArray")
    def Stop(self: MccsDaqReceiver) -> DevVarLongStringArrayType:
        """
        Stop the DaqReceiver.

        The DAQ receiver will cease watching the specified interface
        and will stop all running consumers.

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.

        :example:
            >>> daq = tango.DeviceProxy("low-mccs/daqreceiver/001")
            >>> daq.Stop()
        """
        handler = self.get_command_object("Stop")
        (result_code, message) = handler()
        return ([result_code], [message])

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
            argin: str,
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
    def Configure(
        self: MccsDaqReceiver, argin: str
    ) -> DevVarLongStringArrayType:  # noqa: E501
        """
        Configure the DaqReceiver.

        Applies the specified configuration to the DaqReceiver.

        :param argin: A JSON string containing the daq configuration to apply.
        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.

        :example:
            >>> daq = tango.DeviceProxy("low-mccs/daqreceiver/001")
            >>> daq_config = {
                "receiver_ports": "4660",
                "receiver_interface": "eth0",
            }
            >>> daq.Configure(json.dumps(daq_config))
        """
        handler = self.get_command_object("Configure")

        (result_code, message) = handler(argin)
        return ([result_code], [message])

    @command(dtype_out="DevString")
    def GetConfiguration(self: MccsDaqReceiver) -> str:
        """
        Get the Configuration from DAQ.

        :return: A JSON-encoded dictionary of the configuration.

        :example:
            >>> daq = tango.DeviceProxy("low-mccs/daqreceiver/001")
            >>> jstr = daq.GetConfiguration()
            >>> dict = json.loads(jstr)
        """
        handler = self.get_command_object("GetConfiguration")
        return handler()

    class GetConfigurationCommand(FastCommand):
        """Class for handling the GetConfiguration() command."""

        def __init__(  # type: ignore
            self: MccsDaqReceiver.GetConfigurationCommand,
            component_manager,
            logger: Optional[logging.Logger] = None,
        ) -> None:
            """
            Initialise a new GetConfigurationCommand instance.

            :param component_manager: the device to which this command belongs.
            :param logger: a logger for this command to use.
            """
            self._component_manager = component_manager
            super().__init__(logger)

        # pylint: disable=arguments-differ
        def do(  # type: ignore[override]
            self: MccsDaqReceiver.GetConfigurationCommand,
        ) -> str:
            """
            Implement :py:meth:`.MccsDaqReceiver.GetConfiguration` command.

            :return: The configuration as received from pydaq
            """
            response = self._component_manager.get_configuration()
            return json.dumps(response)

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
            Implement MccsDaqReceiver.SetConsumersCommand functionality.

            :param argin: A string containing a comma separated
                list of DaqModes.
            :return: A tuple containing a return code and a string
                message indicating status. The message is for
                information purpose only.
            """
            return self._component_manager._set_consumers_to_start(argin)

    @command(dtype_in="DevString", dtype_out="DevVarLongStringArray")
    def SetConsumers(
        self: MccsDaqReceiver, argin: str
    ) -> DevVarLongStringArrayType:  # noqa: E501
        """
        Set the default list of consumers to start.

        Sets the default list of consumers to start when left unspecified in
        the `start_daq` command.

        :param argin: A string containing a comma separated
            list of DaqModes.
        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.

        :example:
            >>> daq = tango.DeviceProxy("low-mccs/daqreceiver/001")
            # pylint: disable=line-too-long
            >>> consumers = "DaqModes.INTEGRATED_BEAM_DATA,ANTENNA_BUFFER, BEAM_DATA," # noqa: E501
            >>> daq.SetConsumers(consumers)
        """
        handler = self.get_command_object("SetConsumers")
        (result_code, message) = handler(argin)
        return ([result_code], [message])

    @command(dtype_in="DevString", dtype_out="DevVarLongStringArray")
    def StartBandpassMonitor(
        self: MccsDaqReceiver, argin: str
    ) -> DevVarLongStringArrayType:
        """
        Start monitoring antenna bandpasses.

        The MccsDaqReceiver will begin monitoring antenna bandpasses
            and producing plots of the spectra.

        :param argin: A json dictionary with keywords.
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
        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        handler = self.get_command_object("StartBandpassMonitor")
        (result_code, message) = handler(argin=argin)
        return ([result_code], [message])

    class StopBandpassMonitorCommand(FastCommand):
        """Class for handling the StopBandpassMonitorCommand() command."""

        def __init__(  # type: ignore
            self: MccsDaqReceiver.StopBandpassMonitorCommand,
            component_manager,
            logger: Optional[logging.Logger] = None,
        ) -> None:
            """
            Initialise a new StopBandpassMonitorCommand instance.

            :param component_manager: the device to which this command belongs.
            :param logger: a logger for this command to use.
            """
            self._component_manager = component_manager
            super().__init__(logger)

        # pylint: disable=arguments-differ
        def do(  # type: ignore[override]
            self: MccsDaqReceiver.StopBandpassMonitorCommand,
        ) -> tuple[ResultCode, str]:
            """
            Implement MccsDaqReceiver.SetConsumersCommand functionality.

            Stop monitoring antenna bandpasses.

            The MccsDaqReceiver will cease monitoring antenna bandpasses
                and producing plots of the spectra.

            :return: A tuple containing a return code and a string
                message indicating status. The message is for
                information purpose only.
            """
            return self._component_manager.stop_bandpass_monitor()

    @command(dtype_out="DevVarLongStringArray")
    def StopBandpassMonitor(self: MccsDaqReceiver) -> DevVarLongStringArrayType:
        """
        Stop monitoring antenna bandpasses.

        The MccsDaqReceiver will cease monitoring antenna bandpasses
            and producing plots of the spectra.

        :return: A tuple containing a return code and a string
            message indicating status. The message is for
            information purpose only.
        """
        handler = self.get_command_object("StopBandpassMonitor")
        (result_code, message) = handler()
        return ([result_code], [message])

    @attribute(
        dtype=("str",),
        max_dim_x=2,  # Always the last result (unique_id, JSON-encoded result)
    )
    def dataReceivedResult(self: MccsDaqReceiver) -> tuple[str, str]:
        """
        Read the result of the receiving of data.

        :return: A tuple containing the data mode of transmission and a json
            string with any additional data about the data such as the file
            name.
        """
        return self._received_data_mode, self._received_data_result

    @attribute(
        dtype=(("DevFloat",),),
        max_dim_x=256,  # Antennas
        max_dim_y=511,  # Channels
    )
    def xPolBandpass(self: MccsDaqReceiver) -> np.ndarray:
        """
        Read the last bandpass plot data for the x-polarisation.

        :return: The last block of x-polarised bandpass data.
        """
        return self._x_bandpass_plot

    @attribute(
        dtype=(("DevFloat",),),
        max_dim_x=256,
        max_dim_y=511,
    )
    def yPolBandpass(self: MccsDaqReceiver) -> np.ndarray:
        """
        Read the last bandpass plot data for the y-polarisation.

        :return: The last block of y-polarised bandpass data.
        """
        return self._y_bandpass_plot

    @attribute(
        dtype=(("DevFloat",),),
        max_dim_x=256,
        max_dim_y=511,
    )
    def rmsPlot(self: MccsDaqReceiver) -> np.ndarray:
        """
        Read the last rms plot filepath.

        :return: The last block of rms data.
        """
        return self._rms_plot


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
