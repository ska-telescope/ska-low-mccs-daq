# -*- coding: utf-8 -*-
"""This module provides a flexible test harness for testing Tango devices."""
from __future__ import annotations

import time
import unittest.mock
from types import TracebackType

import tango
from ska_control_model import LoggingLevel
from ska_tango_testing.harness import TangoTestHarness, TangoTestHarnessContext
from tango.server import Device

DEFAULT_STATION_LABEL = "ci-1"  # station 1 of cluster "ci"


def get_lmc_daq_name(station_label: str | None = None) -> str:
    """
    Construct the DAQ Tango device name from its ID number.

    :param station_label: name of the station under test.
        Defaults to None, in which case the module default is used.

    :return: the DAQ Tango device name
    """
    return f"low-mccs/daqreceiver/{station_label or DEFAULT_STATION_LABEL}"


def get_bandpass_daq_name(station_label: str | None = None) -> str:
    """
    Construct the DAQ Tango device name from its ID number.

    :param station_label: name of the station under test.
        Defaults to None, in which case the module default is used.

    :return: the DAQ Tango device name
    """
    return f"low-mccs/daqreceiver/{station_label or DEFAULT_STATION_LABEL}-bandpass"


# pylint: disable = too-few-public-methods
class SpsTangoTestHarnessContext:
    """Handle for the SPSHW test harness context."""

    def __init__(
        self: SpsTangoTestHarnessContext,
        tango_context: TangoTestHarnessContext,
        station_label: str,
    ) -> None:
        """
        Initialise a new instance.

        :param tango_context: handle for the underlying test harness
            context.
        :param station_label: name of the station under test.
        """
        self._station_label = station_label
        self._tango_context = tango_context

    def get_daq_device(
        self: SpsTangoTestHarnessContext, station_label: str | None = None
    ) -> tango.DeviceProxy:
        """
        Get the DAQ receiver Tango device.

        :param station_label: optional station_label override.

        :raises RuntimeError: if the device fails to become ready.

        :returns: a proxy to the DAQ receiver Tango device.
        """
        device_name = get_lmc_daq_name(station_label or self._station_label)
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


class SpsTangoTestHarness:
    """A test harness for testing monitoring and control of SPS hardware."""

    def __init__(self: SpsTangoTestHarness, station_label: str | None = None) -> None:
        """
        Initialise a new test harness instance.

        :param station_label: name of the station under test.
            Defaults to None, in which case "ci-1" is used.
        """
        self._station_label = station_label or DEFAULT_STATION_LABEL
        self._tango_test_harness = TangoTestHarness()

    def add_mock_lmc_daq_device(
        self: SpsTangoTestHarness,
        mock: unittest.mock.Mock,
        bandpass: bool = False,
    ) -> None:
        """
        Add a mock daq Tango device to this test harness.

        :param mock: the mock to be used as a mock daq device.
        :param bandpass: whether this is a bandpass DAQ.
        """
        self._tango_test_harness.add_mock_device(
            get_lmc_daq_name(self._station_label), mock
        )

    def add_mock_bandpass_daq_device(
        self: SpsTangoTestHarness,
        mock: unittest.mock.Mock,
        bandpass: bool = False,
    ) -> None:
        """
        Add a mock daq Tango device to this test harness.

        :param mock: the mock to be used as a mock daq device.
        :param bandpass: whether this is a bandpass DAQ.
        """
        self._tango_test_harness.add_mock_device(
            get_bandpass_daq_name(self._station_label), mock
        )

    def set_lmc_daq_device(  # pylint: disable=too-many-arguments
        self: SpsTangoTestHarness,
        daq_id: int,
        address: tuple[str, int] | None,
        receiver_interface: str | None = None,
        consumers_to_start: list[str] | None = None,
        ringbuffer_max_warning: float = 20,
        ringbuffer_max_alarm: float = 70,
        logging_level: int = int(LoggingLevel.DEBUG),
        station_label: str | None = None,
        device_class: type[Device] | str = "ska_low_mccs_daq.MccsDaqReceiver",
    ) -> None:
        """
        Add a DAQ Tango device to the test harness.

        :param daq_id: An ID number for the DAQ.
        :param address: address of the DAQ instance
            to be monitored and controlled by this Tango device.
            It is a tuple of hostname or IP address, and port.
        :param receiver_interface: The interface on which the DAQ receiver
            is listening for traffic.
        :param consumers_to_start: list of consumers to start.
        :param ringbuffer_max_warning: the max warning to configure the ringbuffer
            alarms with.
        :param ringbuffer_max_alarm: the max alarm to configure the ringbuffer alarms
            with.
        :param logging_level: the Tango device's default logging level.
        :param station_label: optional station label override.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        """
        if consumers_to_start is None:
            consumers_to_start = ["DaqModes.INTEGRATED_CHANNEL_DATA"]

        if address is None:
            host = "localhost"

        else:
            (host, _) = address

        self._tango_test_harness.add_device(
            get_lmc_daq_name(station_label or self._station_label),
            device_class,
            DaqId=daq_id,
            ReceiverInterface=receiver_interface,
            Host=host,
            ConsumersToStart=consumers_to_start,
            LoggingLevelDefault=logging_level,
            SimulationMode=True,
            # RingbufferOccupancyWarning=ringbuffer_max_warning,
            # RingbufferOccupancyAlarm=ringbuffer_max_alarm,
        )

    def set_bandpass_daq_device(  # pylint: disable=too-many-arguments
        self: SpsTangoTestHarness,
        daq_id: int,
        address: tuple[str, int] | None,
        consumers_to_start: list[str] | None = None,
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_daq.MccsDaqReceiver",
    ) -> None:
        """
        Add a DAQ Tango device to the test harness.

        :param daq_id: An ID number for the DAQ.
        :param address: address of the DAQ instance
            to be monitored and controlled by this Tango device.
            It is a tuple of hostname or IP address, and port.
        :param consumers_to_start: list of consumers to start.
        :param logging_level: the Tango device's default logging level.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        """
        if consumers_to_start is None:
            consumers_to_start = ["DaqModes.INTEGRATED_CHANNEL_DATA"]

        if address is None:
            host = "localhost"

        else:
            (host, _) = address

        self._tango_test_harness.add_device(
            get_bandpass_daq_name(self._station_label),
            device_class,
            DaqId=daq_id,
            Host=host,
            ConsumersToStart=consumers_to_start,
            LoggingLevelDefault=logging_level,
            SimulationMode=True,
        )

    def __enter__(
        self: SpsTangoTestHarness,
    ) -> SpsTangoTestHarnessContext:
        """
        Enter the context.

        :return: the entered context.
        """
        return SpsTangoTestHarnessContext(
            self._tango_test_harness.__enter__(), self._station_label
        )

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
