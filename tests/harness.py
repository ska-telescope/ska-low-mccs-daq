# -*- coding: utf-8 -*-
"""This module provides a flexible test harness for testing Tango devices."""
from __future__ import annotations

import unittest.mock
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable, Iterable

from ska_control_model import LoggingLevel, SimulationMode, TestMode
from ska_tango_testing.harness import TangoTestHarness, TangoTestHarnessContext
from tango import DeviceProxy
from tango.server import Device

if TYPE_CHECKING:
    from ska_low_mccs_spshw.subrack.subrack_simulator import SubrackSimulator


def _slug(device_type: str, device_id: int) -> str:
    return f"{device_type}_{device_id}"


def get_field_station_name() -> str:
    """
    Return the Field Station Tango device name.

    :return: the Field Station Tango device name
    """
    return "low-mccs/fieldstation/001"


def get_calibration_store_name() -> str:
    """
    Return the Calibration Store Tango device name.

    :return: the Calibration Store Tango device name
    """
    return "low-mccs/calibrationstore/001"


def get_station_calibrator_name() -> str:
    """
    Return the Station Calibrator Tango device name.

    :return: the Station Calibrator Tango device name
    """
    return "low-mccs/stationcalibrator/001"


def get_sps_station_name() -> str:
    """
    Return the SPS station Tango device name.

    :return: the SPS station Tango device name
    """
    return "low-mccs/sps_station/001"


def get_field_station_name() -> str:
    """
    Return the Field station Tango device name.

    :return: the Field station Tango device name
    """
    return "low-mccs/fieldstation/001"


def get_subrack_name(subrack_id: int) -> str:
    """
    Construct the subrack Tango device name from its ID number.

    :param subrack_id: the ID number of the subrack.

    :return: the subrack Tango device name
    """
    return f"low-mccs/subrack/{subrack_id:04}"


def get_tile_name(tile_id: int) -> str:
    """
    Construct the tile Tango device name from its ID number.

    :param tile_id: the ID number of the tile.

    :return: the tile Tango device name
    """
    return f"low-mccs/tile/{tile_id:04}"


class SpsTangoTestHarnessContext:
    """Handle for the SPSHW test harness context."""

    def __init__(self, tango_context: TangoTestHarnessContext):
        """
        Initialise a new instance.

        :param tango_context: handle for the underlying test harness
            context.
        """
        self._tango_context = tango_context

    def get_sps_station_device(self) -> DeviceProxy:
        """
        Get a proxy to the SPS station Tango device.

        :returns: a proxy to the SPS station Tango device.
        """
        return self._tango_context.get_device(get_sps_station_name())

    def get_station_calibrator_device(self) -> DeviceProxy:
        """
        Get a proxy to the Station Calibrator Tango device.

        :returns: a proxy to the Station Calibrator Tango device.
        """
        return self._tango_context.get_device(get_station_calibrator_name())

    def get_field_station_device(self) -> DeviceProxy:
        """
        Get a Field station Tango device.

        :returns: a proxy to the Field station Tango device.
        """
        return self._tango_context.get_device(get_field_station_name())

    def get_subrack_device(self, subrack_id: int) -> DeviceProxy:
        """
        Get a subrack Tango device by its ID number.

        :param subrack_id: the ID number of the subrack.

        :returns: a proxy to the subrack Tango device.
        """
        return self._tango_context.get_device(get_subrack_name(subrack_id))

    def get_subrack_address(self, subrack_id: int) -> tuple[str, int]:
        """
        Get the address of the subrack server.

        :param subrack_id: the ID number of this subrack instance.

        :returns: the address (hostname and port) of the DAQ server.
        """
        return self._tango_context.get_context(_slug("subrack", subrack_id))

    def get_tile_device(self, tile_id: int) -> DeviceProxy:
        """
        Get a tile Tango device by its ID number.

        :param tile_id: the ID number of the tile.

        :returns: a proxy to the tile Tango device.
        """
        return self._tango_context.get_device(get_tile_name(tile_id))


class SpsTangoTestHarness:
    """A test harness for testing monitoring and control of SPS hardware."""

    def __init__(self: SpsTangoTestHarness) -> None:
        """Initialise a new test harness instance."""
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
            get_station_calibrator_name(),
            device_class,
            FieldStationName=get_field_station_name(),
            CalibrationStoreName=get_calibration_store_name(),
            LoggingLevelDefault=logging_level,
        )

    def set_sps_station_device(  # pylint: disable=too-many-arguments
        self: SpsTangoTestHarness,
        cabinet_address: str = "10.0.0.0",
        subrack_ids: Iterable[int] = range(1, 3),
        tile_ids: Iterable[int] = range(1, 17),
        logging_level: int = int(LoggingLevel.DEBUG),
        device_class: type[Device] | str = "ska_low_mccs_spshw.SpsStation",
    ) -> None:
        """
        Set the SPS station Tango device in the test harness.

        This test harness currently only permits one SPS station device.

        :param cabinet_address: the network address of the SPS cabinet
        :param subrack_ids: IDs of the subracks in this station.
        :param tile_ids: IDS of the tiles in this station.
        :param logging_level: the Tango device's default logging level.
        :param device_class: The device class to use.
            This may be used to override the usual device class,
            for example with a patched subclass.
        """
        self._tango_test_harness.add_device(
            get_sps_station_name(),
            device_class,
            StationId=1,
            TileFQDNs=[get_tile_name(tile_id) for tile_id in tile_ids],
            SubrackFQDNs=[get_subrack_name(subrack_id) for subrack_id in subrack_ids],
            CabinetNetworkAddress=cabinet_address,
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
            _slug("subrack", subrack_id),
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
            get_field_station_name(),
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
            server_id = _slug("subrack", subrack_id)

            host = "localhost"

            def port(context: dict[str, Any]) -> int:
                return context[server_id][1]

        else:
            (host, port) = address

        self._tango_test_harness.add_device(
            get_subrack_name(subrack_id),
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
        self._tango_test_harness.add_mock_device(get_field_station_name(), mock)

    def add_mock_calibration_store_device(
        self: SpsTangoTestHarness,
        mock: unittest.mock.Mock,
    ) -> None:
        """
        Add a mock Calibration Store Tango device to this test harness.

        :param mock: the mock to be used as a mock Calibration Store device.
        """
        self._tango_test_harness.add_mock_device(get_calibration_store_name(), mock)

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
        self._tango_test_harness.add_mock_device(get_subrack_name(subrack_id), mock)

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
            get_tile_name(subrack_id),
            device_class,
            TileId=tile_id,
            SimulationConfig=int(SimulationMode.TRUE),
            TestConfig=int(TestMode.TEST),
            SubrackFQDN=get_subrack_name(subrack_id),
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
        self._tango_test_harness.add_mock_device(get_tile_name(tile_id), mock)

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
