# -*- coding: utf-8 -*-
"""This module provides a flexible test harness for testing Tango devices."""
from __future__ import annotations

import time
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable

import tango
from ska_control_model import LoggingLevel
from ska_tango_testing.harness import TangoTestHarness, TangoTestHarnessContext
from tango import DeviceProxy
from tango.server import Device

if TYPE_CHECKING:
    from ska_low_mccs_daq_interface import DaqServerBackendProtocol


def get_device_name_from_id(daq_id: int) -> str:
    """
    Construct the DAQ Tango device name from its ID number.

    :param daq_id: the ID number of the DAQ instance.

    :return: the DAQ Tango device name
    """
    return f"low-mccs/daqreceiver/{daq_id:03}"


class DaqTangoTestHarnessContext:
    """Handle for the DAQ test harness context."""

    def __init__(self, tango_context: TangoTestHarnessContext):
        """
        Initialise a new instance.

        :param tango_context: handle for the underlying test harness
            context.
        """
        self._tango_context = tango_context

    def get_daq_device(self, daq_id: int) -> DeviceProxy:
        """
        Get a DAQ receiver Tango device by its ID number.

        :param daq_id: the ID number of the DAQ receiver.

        :raises RuntimeError: if the device fails to become ready.

        :returns: a proxy to the DAQ receiver Tango device.
        """
        device_name = get_device_name_from_id(daq_id)
        device_proxy = self._tango_context.get_device(device_name)

        # TODO: This should simply be
        #     return device_proxy
        # but sadly, when we test against a fresh k8s deployment,
        # the device is not actually ready to be tested
        # until many seconds after the readiness probe reports it to be ready.
        # This should be fixed in the k8s readiness probe,
        # but for now we have to check for readiness here.
        for sleep_time in [0, 1, 2, 4, 8, 15, 30, 60]:
            if sleep_time:
                print(f"Sleeping {sleep_time} second(s)...")
                time.sleep(sleep_time)
            try:
                if device_proxy.state() != tango.DevState.INIT:
                    return device_proxy
                print(f"Device {device_name} still initialising.")
            except tango.DevFailed as dev_failed:
                print(
                    f"Device {device_name} raised DevFailed on state() call:\n"
                    f"{repr(dev_failed)}."
                )
        raise RuntimeError(f"Device {device_name} failed readiness.")

    def get_daq_server_address(self, daq_id: int) -> str:
        """
        Get the address of the DAQ server.

        :param daq_id: the ID number of this DAQ instance.

        :returns: the address (hostname and port) of the DAQ server.
        """
        port = self._tango_context.get_context(f"daq_{daq_id}")
        return f"localhost:{port}"


class DaqTangoTestHarness:
    """A test harness for testing monitoring and control of DAQ receivers."""

    def __init__(self: DaqTangoTestHarness) -> None:
        """Initialise a new test harness instance."""
        self._tango_test_harness = TangoTestHarness()

    def add_daq_instance(
        self: DaqTangoTestHarness,
        daq_id: int,
        daq_instance: DaqServerBackendProtocol,
    ) -> None:
        """
        And a DAQ instance to the test harness.

        :param daq_id: an ID number for the DAQ instance.
        :param daq_instance:
            the DAQ instance to be added to the test harness.
        """
        # Defer importing from ska_low_mccs_daq
        # until we know we need to launch a DAQ instance to test against.
        # This ensures that we can use this harness
        # to run tests against a real cluster,
        # from within a pod that does not have ska_low_mccs_daq installed.
        # pylint: disable-next=import-outside-toplevel
        from ska_low_mccs_daq_interface.server import server_context

        self._tango_test_harness.add_context_manager(
            f"daq_{daq_id}",
            server_context(daq_instance, 0),
        )

    def add_daq_device(  # pylint: disable=too-many-arguments
        self: DaqTangoTestHarness,
        daq_id: int,
        address: tuple[str, int] | None,
        receiver_interface: str,
        receiver_ip: str,
        receiver_ports: list[int],
        consumers_to_start: list[str],
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_daq.MccsDaqReceiver",
    ) -> None:
        """
        Add a DAQ Tango device to the test harness.

        :param daq_id: An ID number for the DAQ.
        :param address: address of the DAQ instance
            to be monitored and controlled by this Tango device.
            It is a tuple of hostname or IP address, and port.
        :param receiver_interface: The interface this DaqReceiver is to watch.
        :param receiver_ip: The IP address of this DaqReceiver.
        :param receiver_ports: The ports this DaqReceiver is to watch.
        :param consumers_to_start: list of consumers to start.
        :param logging_level: the Tango device's default logging level.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        """
        port: Callable[[dict[str, Any]], int] | int  # for the type checker

        if address is None:
            server_id = f"daq_{daq_id}"

            host = "localhost"

            def port(context: dict[str, Any]) -> int:
                return context[server_id]

        else:
            (host, port) = address

        self._tango_test_harness.add_device(
            get_device_name_from_id(daq_id),
            device_class,
            DaqId=daq_id,
            ReceiverInterface=receiver_interface,
            ReceiverIp=receiver_ip,
            ReceiverPorts=receiver_ports,
            Host=host,
            Port=port,
            ConsumersToStart=consumers_to_start,
            LoggingLevelDefault=logging_level,
        )

    def __enter__(
        self: DaqTangoTestHarness,
    ) -> DaqTangoTestHarnessContext:
        """
        Enter the context.

        :return: the entered context.
        """
        return DaqTangoTestHarnessContext(self._tango_test_harness.__enter__())

    def __exit__(
        self: DaqTangoTestHarness,
        exc_type: type[BaseException] | None,
        exception: BaseException | None,
        trace: TracebackType | None,
    ) -> bool | None:
        """
        Exit the context.

        :param exc_type: the type of exception thrown in the with block,
            if any.
        :param exception: the exception thrown in the with block, if
            any.
        :param trace: the exception traceback, if any,

        :return: whether the exception (if any) has been fully handled
            by this method and should be swallowed i.e. not re-raised
        """
        return self._tango_test_harness.__exit__(exc_type, exception, trace)
