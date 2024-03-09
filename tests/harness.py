# -*- coding: utf-8 -*-
"""This module provides a flexible test harness for testing Tango devices."""
from __future__ import annotations

import time
import unittest.mock
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable, Iterable

import tango
from ska_control_model import LoggingLevel, SimulationMode, TestMode
from ska_tango_testing.harness import TangoTestHarness, TangoTestHarnessContext
from tango.server import Device

if TYPE_CHECKING:
    from ska_low_mccs_daq_interface import DaqServerBackendProtocol

    from ska_low_mccs_spshw.subrack.subrack_simulator import SubrackSimulator

DEFAULT_STATION_LABEL = "ci-1"  # station 1 of cluster "ci"


def get_field_station_name(station_label: str | None = None) -> str:
    """
    Return the Field Station Tango device name.

    :param station_label: name of the station under test.
        Defaults to None, in which case the module default is used.

    :return: the Field Station Tango device name
    """
    return f"low-mccs/mockfieldstation/{station_label or DEFAULT_STATION_LABEL}"


def get_calibration_store_name(station_label: str | None = None) -> str:
    """
    Return the Calibration Store Tango device name.

    :param station_label: name of the station under test.
        Defaults to None, in which case the module default is used.

    :return: the Calibration Store Tango device name
    """
    return f"low-mccs/calibrationstore/{station_label or DEFAULT_STATION_LABEL}"


def get_station_calibrator_name(station_label: str | None = None) -> str:
    """
    Return the Station Calibrator Tango device name.

    :param station_label: name of the station under test.
        Defaults to None, in which case the module default is used.

    :return: the Station Calibrator Tango device name
    """
    return f"low-mccs/stationcalibrator/{station_label or DEFAULT_STATION_LABEL}"


def get_sps_station_name(station_label: str | None = None) -> str:
    """
    Return the SPS station Tango device name.

    :param station_label: name of the station under test.
        Defaults to None, in which case the module default is used.

    :return: the SPS station Tango device name
    """
    return f"low-mccs/sps_station/{station_label or DEFAULT_STATION_LABEL}"


def get_subrack_name(subrack_id: int, station_label: str | None = None) -> str:
    """
    Construct the subrack Tango device name from its ID number.

    :param subrack_id: the ID number of the subrack in the station.
    :param station_label: name of the station under test.
        Defaults to None, in which case the module default is used.

    :return: the subrack Tango device name
    """
    return f"low-mccs/subrack/{station_label or DEFAULT_STATION_LABEL}-{subrack_id}"


def get_tile_name(tile_id: int, station_label: str | None = None) -> str:
    """
    Construct the tile Tango device name from its ID number.

    :param tile_id: the ID number of the tile in the station.
    :param station_label: name of the station under test.
        Defaults to None, in which case the module default is used.

    :return: the tile Tango device name
    """
    return f"low-mccs/tile/{station_label or DEFAULT_STATION_LABEL}-{tile_id:02}"


def get_daq_name(station_label: str | None = None) -> str:
    """
    Construct the DAQ Tango device name from its ID number.

    :param station_label: name of the station under test.
        Defaults to None, in which case the module default is used.

    :return: the DAQ Tango device name
    """
    return f"low-mccs/daqreceiver/{station_label or DEFAULT_STATION_LABEL}"


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

    def get_sps_station_device(self: SpsTangoTestHarnessContext) -> tango.DeviceProxy:
        """
        Get a proxy to the SPS station Tango device.

        :returns: a proxy to the SPS station Tango device.
        """
        return self._tango_context.get_device(get_sps_station_name(self._station_label))

    def get_station_calibrator_device(
        self: SpsTangoTestHarnessContext,
    ) -> tango.DeviceProxy:
        """
        Get a proxy to the Station Calibrator Tango device.

        :raises RuntimeError: if the device fails to become ready.

        :returns: a proxy to the Station Calibrator Tango device.
        """
        device_name = get_station_calibrator_name(self._station_label)
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

    def get_calibration_store_device(self) -> tango.DeviceProxy:
        """
        Get a proxy to the Calibration Store Tango device.

        :raises RuntimeError: if the device fails to become ready.

        :returns: a proxy to the Calibration Store Tango device.
        """
        device_name = get_calibration_store_name(self._station_label)
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

    def get_field_station_device(self: SpsTangoTestHarnessContext) -> tango.DeviceProxy:
        """
        Get a Field station Tango device.

        :raises RuntimeError: if the device fails to become ready.

        :returns: a proxy to the Field station Tango device.
        """
        device_name = get_field_station_name(self._station_label)
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

    def get_subrack_device(
        self: SpsTangoTestHarnessContext, subrack_id: int
    ) -> tango.DeviceProxy:
        """
        Get a subrack Tango device by its ID number.

        :param subrack_id: the ID number of the subrack.

        :returns: a proxy to the subrack Tango device.
        """
        return self._tango_context.get_device(
            get_subrack_name(subrack_id, station_label=self._station_label)
        )

    def get_subrack_address(
        self: SpsTangoTestHarnessContext, subrack_id: int
    ) -> tuple[str, int]:
        """
        Get the address of the subrack server.

        :param subrack_id: the ID number of this subrack instance.

        :returns: the address (hostname and port) of the DAQ server.
        """
        return self._tango_context.get_context(f"subrack_{subrack_id}")

    def get_tile_device(
        self: SpsTangoTestHarnessContext, tile_id: int
    ) -> tango.DeviceProxy:
        """
        Get a tile Tango device by its ID number.

        :param tile_id: the ID number of the tile.

        :returns: a proxy to the tile Tango device.
        """
        return self._tango_context.get_device(
            get_tile_name(tile_id, station_label=self._station_label)
        )

    def get_daq_device(self: SpsTangoTestHarnessContext) -> tango.DeviceProxy:
        """
        Get the DAQ receiver Tango device.

        :raises RuntimeError: if the device fails to become ready.

        :returns: a proxy to the DAQ receiver Tango device.
        """
        device_name = get_daq_name(self._station_label)
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

    def get_daq_server_address(self: SpsTangoTestHarnessContext, daq_id: int) -> str:
        """
        Get the address of the DAQ server.

        :param daq_id: the ID number of this DAQ instance.

        :returns: the address (hostname and port) of the DAQ server.
        """
        port = self._tango_context.get_context("daq")
        return f"localhost:{port}"


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

    def set_station_calibrator_device(
        self: SpsTangoTestHarness,
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_spshw.MccsStationCalibrator",
    ) -> None:
        """
        Set the Station Calibrator Tango device in the test harness.

        This test harness currently only permits one SPS station device so should also
        only permit one Station Calibrator

        :param logging_level: the Tango device's default logging level.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        """
        self._tango_test_harness.add_device(
            get_station_calibrator_name(self._station_label),
            device_class,
            FieldStationName=get_field_station_name(self._station_label),
            CalibrationStoreName=get_calibration_store_name(self._station_label),
            LoggingLevelDefault=logging_level,
        )

    # pylint: disable=too-many-arguments
    def set_calibration_store_device(
        self: SpsTangoTestHarness,
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_spshw.MccsCalibrationStore",
        database_host: str = "station-calibration-postgresql",
        database_port: int = 5432,
        database_name: str = "postgres",
        database_admin_user: str = "postgres",
        database_admin_password: str = "",
    ) -> None:
        """
        Set the Calibration Store Tango device in the test harness.

        This test harness currently only permits one SPS station device so should also
        only permit one Calibration Store

        :param logging_level: the Tango device's default logging level.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        :param database_host: the database host
        :param database_port: the database port
        :param database_name: the database name
        :param database_admin_user: the database admin user
        :param database_admin_password: the database admin password
        """
        self._tango_test_harness.add_device(
            get_calibration_store_name(self._station_label),
            device_class,
            DatabaseHost=database_host,
            DatabasePort=database_port,
            DatabaseName=database_name,
            DatabaseAdminUser=database_admin_user,
            DatabaseAdminPassword=database_admin_password,
            LoggingLevelDefault=logging_level,
        )

    def set_sps_station_device(  # pylint: disable=too-many-arguments
        self: SpsTangoTestHarness,
        station_address: str = "10.0.0.128",
        subrack_ids: Iterable[int] = range(1, 3),
        tile_ids: Iterable[int] = range(1, 17),
        daq_trl: str = "",
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_spshw.SpsStation",
    ) -> None:
        """
        Set the SPS station Tango device in the test harness.

        This test harness currently only permits one SPS station device.

        :param station_address: the network address at which this station's
            allocated address block for data starts
        :param subrack_ids: IDs of the subracks in this station.
        :param tile_ids: IDS of the tiles in this station.
        :param daq_trl: TRL of this Station's DAQ.
        :param logging_level: the Tango device's default logging level.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        """
        self._tango_test_harness.add_device(
            get_sps_station_name(self._station_label),
            device_class,
            StationId=1,
            DaqTRL=daq_trl,
            TileFQDNs=[
                get_tile_name(tile_id, station_label=self._station_label)
                for tile_id in tile_ids
            ],
            SubrackFQDNs=[
                get_subrack_name(subrack_id, station_label=self._station_label)
                for subrack_id in subrack_ids
            ],
            StationNetworkAddress=station_address,
            LoggingLevelDefault=logging_level,
        )

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
            f"subrack_{subrack_id}",
            SubrackServerContextManager(subrack_simulator),
        )

    def add_field_station_device(
        self: SpsTangoTestHarness,
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_spshw.mocks.MockFieldStation",
    ) -> None:
        """
        Set the Field station Tango device in the test harness.

        :param logging_level: the Tango device's default logging level.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        """
        self._tango_test_harness.add_device(
            get_field_station_name(self._station_label),
            device_class,
            LoggingLevelDefault=logging_level,
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
            server_id = f"subrack_{subrack_id}"

            host = "localhost"

            def port(context: dict[str, Any]) -> int:
                return context[server_id][1]

        else:
            (host, port) = address

        self._tango_test_harness.add_device(
            get_subrack_name(subrack_id, station_label=self._station_label),
            device_class,
            SubrackIp=host,
            SubrackPort=port,
            UpdateRate=update_rate,
            LoggingLevelDefault=logging_level,
        )

    def add_mock_field_station_device(
        self: SpsTangoTestHarness,
        mock: unittest.mock.Mock,
    ) -> None:
        """
        Add a mock Field Station Tango device to this test harness.

        :param mock: the mock to be used as a mock Field Station device.
        """
        self._tango_test_harness.add_mock_device(
            get_field_station_name(self._station_label), mock
        )

    def add_mock_calibration_store_device(
        self: SpsTangoTestHarness,
        mock: unittest.mock.Mock,
    ) -> None:
        """
        Add a mock Calibration Store Tango device to this test harness.

        :param mock: the mock to be used as a mock Calibration Store device.
        """
        self._tango_test_harness.add_mock_device(
            get_calibration_store_name(self._station_label), mock
        )

    def add_mock_subrack_device(
        self: SpsTangoTestHarness,
        subrack_id: int,
        mock: unittest.mock.Mock,
    ) -> None:
        """
        Add a mock subrack Tango device to this test harness.

        :param subrack_id: An ID number for the mock subrack.
        :param mock: the mock to be used as a mock subrack device.
        """
        self._tango_test_harness.add_mock_device(
            get_subrack_name(subrack_id, station_label=self._station_label), mock
        )

    def add_tile_device(  # pylint: disable=too-many-arguments
        self: SpsTangoTestHarness,
        tile_id: int,
        subrack_id: int = 1,
        subrack_bay: int = 1,
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_spshw.MccsTile",
    ) -> None:
        """
        Add a tile Tango device to the test harness.

        :param tile_id: ID number of the tile.
        :param subrack_id: ID number of this tile's subrack.
        :param subrack_bay: the bay position of this tile in the subrack.
        :param logging_level: the Tango device's default logging level.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        """
        self._tango_test_harness.add_device(
            get_tile_name(tile_id, station_label=self._station_label),
            device_class,
            TileId=tile_id,
            SimulationConfig=int(SimulationMode.TRUE),
            TestConfig=int(TestMode.TEST),
            SubrackFQDN=get_subrack_name(subrack_id, station_label=self._station_label),
            SubrackBay=subrack_bay,
            AntennasPerTile=8,
            LoggingLevelDefault=logging_level,
            TpmIp="10.0.10.201",
            TpmCpldPort=10000,
            TpmVersion="tpm_v1_6",
        )

    def add_mock_tile_device(
        self: SpsTangoTestHarness,
        tile_id: int,
        mock: unittest.mock.Mock,
    ) -> None:
        """
        Add a mock tile Tango device to this test harness.

        :param tile_id: An ID number for the mock tile.
        :param mock: the mock to be used as a mock tile device.
        """
        self._tango_test_harness.add_mock_device(
            get_tile_name(tile_id, station_label=self._station_label), mock
        )

    def set_daq_instance(
        self: SpsTangoTestHarness,
        daq_instance: DaqServerBackendProtocol | None = None,
    ) -> None:
        """
        And a DAQ instance to the test harness.

        :param daq_instance:
            the DAQ instance to be added to the test harness.
        """
        # Defer importing from any MCCS packages
        # until we know we need to launch a DAQ instance to test against.
        # This ensures that we can use this harness
        # to run tests against a real cluster,
        # from within a pod that does not have MCCS packages installed.
        # pylint: disable-next=import-outside-toplevel
        from ska_low_mccs_daq_interface.server import server_context

        # pylint: disable-next=import-outside-toplevel
        from ska_low_mccs_spshw.daq_receiver.daq_simulator import DaqSimulator

        if daq_instance is None:
            daq_instance = DaqSimulator()

        self._tango_test_harness.add_context_manager(
            "daq",
            server_context(daq_instance, 0),
        )

    def set_daq_device(  # pylint: disable=too-many-arguments
        self: SpsTangoTestHarness,
        daq_id: int,
        address: tuple[str, int] | None,
        receiver_interface: str = "eth0",
        receiver_ip: str = "172.17.0.230",
        receiver_ports: list[int] | None = None,
        consumers_to_start: list[str] | None = None,
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_spshw.MccsDaqReceiver",
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

        if receiver_ports is None:
            receiver_ports = [4660]
        if consumers_to_start is None:
            consumers_to_start = ["DaqModes.INTEGRATED_CHANNEL_DATA"]

        if address is None:
            server_id = "daq"
            host = "localhost"

            def port(context: dict[str, Any]) -> int:
                return context[server_id]

        else:
            (host, port) = address

        self._tango_test_harness.add_device(
            get_daq_name(self._station_label),
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
