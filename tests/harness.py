# -*- coding: utf-8 -*-
"""This module provides a flexible test harness for testing Tango devices."""
from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable

from ska_control_model import LoggingLevel
from ska_tango_testing.harness import TangoTestHarness, TangoTestHarnessContext
from tango import DeviceProxy
from tango.server import Device

if TYPE_CHECKING:
    from ska_low_mccs_spshw.subrack.subrack_simulator import SubrackSimulator


def _slug(device_type: str, device_id: int) -> str:
    return f"{device_type}_{device_id}"


def _subrack_name(subrack_id: int) -> str:
    """
    Construct the subrack Tango device name from its ID number.

    :param subrack_id: the ID number of the subrack.

    :return: the subrack Tango device name
    """
    return f"low-mccs/subrack/{subrack_id:04}"


class SpsTangoTestHarnessContext:
    """Handle for the SPSHW test harness context."""

    def __init__(self, tango_context: TangoTestHarnessContext):
        """
        Initialise a new instance.

        :param tango_context: handle for the underlying test harness
            context.
        """
        self._tango_context = tango_context

    def get_subrack_device(self, subrack_id: int) -> DeviceProxy:
        """
        Get a subrack Tango device by its ID number.

        :param subrack_id: the ID number of the subrack.

        :returns: a proxy to the subrack Tango device.
        """
        return self._tango_context.get_device(_subrack_name(subrack_id))

    def get_subrack_address(self, subrack_id: int) -> tuple[str, int]:
        """
        Get the address of the subrack server.

        :param subrack_id: the ID number of this subrack instance.

        :returns: the address (hostname and port) of the DAQ server.
        """
        return self._tango_context.get_context(_slug("subrack", subrack_id))


class SpsTangoTestHarness:
    """A test harness for testing monitoring and control of SPS hardware."""

    def __init__(self: SpsTangoTestHarness) -> None:
        """Initialise a new test harness instance."""
        self._tango_test_harness = TangoTestHarness()

    def add_subrack_simulator(
        self: SpsTangoTestHarness,
        subrack_id: int,
        subrack_simulator: SubrackSimulator | None = None,
    ) -> None:
        """
        And a subrack simulator to the test harness.

        :param subrack_id: an ID number for the subrack.
        :param subrack_simulator: the subrack simulator to be added to
            the harness.
        """
        # Defer importing from ska_low_mccs_spshw
        # until we know we need to launch a subrack simulator to test against.
        # This ensures that we can use this harness to run tests against a real cluster,
        # from within a pod that does not have ska_low_mccs_spshw installed.
        # pylint: disable-next=import-outside-toplevel
        from ska_low_mccs_spshw.subrack.subrack_simulator_server import (
            SubrackServerContextManager,
        )

        self._tango_test_harness.add_context_manager(
            _slug("subrack", subrack_id),
            SubrackServerContextManager(subrack_simulator),
        )

    def add_subrack_device(  # pylint: disable=too-many-arguments
        self: SpsTangoTestHarness,
        subrack_id: int,
        address: tuple[str, int] | None = None,
        update_rate: float = 1.0,
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_spshw.MccsSubrack",
    ) -> None:
        """
        Add a subrack Tango device to the test harness.

        :param subrack_id: An ID number for the subrack.
        :param address: address of the subrack to be
            monitored and controlled by this Tango device.
            It is a tuple of hostname or IP address, and port.
        :param update_rate: How often to update monitored attriutes.
        :param logging_level: the Tango device's default logging level.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        """
        port: Callable[[dict[str, Any]], int] | int  # for the type checker

        if address is None:
            server_id = _slug("subrack", subrack_id)

            host = "localhost"

            def port(context: dict[str, Any]) -> int:
                return context[server_id][1]

        else:
            (host, port) = address

        self._tango_test_harness.add_device(
            _subrack_name(subrack_id),
            device_class,
            SubrackIp=host,
            SubrackPort=port,
            UpdateRate=update_rate,
            LoggingLevelDefault=logging_level,
        )

    def __enter__(
        self: SpsTangoTestHarness,
    ) -> SpsTangoTestHarnessContext:
        """
        Enter the context.

        :return: the entered context.
        """
        return SpsTangoTestHarnessContext(self._tango_test_harness.__enter__())

    def __exit__(
        self: SpsTangoTestHarness,
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
            by this method and should be swallowed i.e. not re-
            raised
        """
        return self._tango_test_harness.__exit__(exc_type, exception, trace)
