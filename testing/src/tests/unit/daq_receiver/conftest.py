# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module defined a pytest harness for testing the MCCS station module."""
from __future__ import annotations

import logging
import unittest.mock
from typing import Any, Callable

import pytest
import pytest_mock
from ska_control_model import TaskStatus
from ska_low_mccs import MccsDaqReceiver
from ska_low_mccs.daq_receiver import DaqComponentManager
from ska_low_mccs_common.testing import TangoHarness
from ska_low_mccs_common.testing.mock import MockCallable
from ska_low_mccs_common.testing.mock.mock_callable import MockCallableDeque


class MockLongRunningCommand(MockCallable):
    """
    Mock the call to submit a LRC.

    A long running command submission, if successful, returns a
    TaskStatus and result message.
    """

    def __call__(self: MockCallable, *args: Any, **kwargs: Any) -> Any:
        """
        Handle a callback call.

        Create a standard mock, call it, and put it on the queue. (This
        approach lets us take advantange of the mock's assertion
        functionality later.)

        :param args: positional args in the call
        :param kwargs: keyword args in the call

        :return: the object's return calue
        """
        called_mock = unittest.mock.Mock()
        called_mock(*args, **kwargs)
        self._queue.put(called_mock)
        return TaskStatus.QUEUED, "Task queued"


@pytest.fixture()
def daq_id() -> int:
    """
    Return the daq id of this daq receiver.

    :return: the daq id of this daq receiver.
    """
    # TODO: This must match the DaqId property of the daq receiver under
    # test. We should refactor the harness so that we can pull it
    # straight from the device configuration.
    return "1"


@pytest.fixture()
def receiver_interface() -> int:
    """
    Return the interface this daq receiver is watching.

    :return: the interface this daq receiver is watching.
    """
    return "eth0"


@pytest.fixture()
def receiver_ip() -> int:
    """
    Return the ip of this daq receiver.

    :return: the ip of this daq receiver.
    """
    # TODO: Will b-strings always work for ip addresses or did I guess lucky?
    return b"172.17.0.255"


@pytest.fixture()
def acquisition_duration() -> int:
    """
    Return the duration of data capture in seconds.

    :return: Duration of data capture.
    """
    return 5


@pytest.fixture()
def receiver_port() -> int:
    """
    Return the port(s) this daq receiver is watching.

    :return: the port(s) this daq receiver is watching.
    """
    return [4660]


# @pytest.fixture()
# def apiu_fqdn() -> str:
#     """
#     Return the FQDN of the Tango device that manages the station's APIU.

#     :return: the FQDN of the Tango device that manages the station's
#         APIU.
#     """
#     # TODO: This must match the AntennaFDQNs property of the station
#     # under test. We should refactor the harness so that we can pull it
#     # straight from the device configuration.
#     return "low-mccs/apiu/001"


# @pytest.fixture()
# def antenna_fqdns() -> list[str]:
#     """
#     Return the FQDNs of the Tango devices that manage the station's antennas.

#     :return: the FQDNs of the Tango devices that manage the station's
#         antennas.
#     """
#     # TODO: This must match the AntennaFDQNs property of the station
#     # under test. We should refactor the harness so that we can pull it
#     # straight from the device configuration.
#     return [
#         "low-mccs/antenna/000001",
#         "low-mccs/antenna/000002",
#         "low-mccs/antenna/000003",
#         "low-mccs/antenna/000004",
#     ]


# @pytest.fixture()
# def tile_fqdns() -> list[str]:
#     """
#     Return the FQDNs of the Tango devices that manage the station's tiles.

#     :return: the FQDNs of the Tango devices that manage the station's
#         tiles.
#     """
#     # TODO: This must match the TileFDQNs property of the station
#     # under test. We should refactor the harness so that we can pull it
#     # straight from the device configuration.
#     return ["low-mccs/tile/0001", "low-mccs/tile/0002"]


# @pytest.fixture()
# def mock_apiu() -> MockDeviceBuilder:
#     """
#     Fixture that provides a mock apiu.

#     The only special behaviour of these mocks is they return a
#     (result_code, message) tuple in response to the SetPointingDelay
#     call.

#     :return: a factory for device proxy mocks
#     """
#     builder = MockDeviceBuilder()
#     builder.add_result_command("Off", result_code=ResultCode.OK)
#     builder.add_result_command("On", result_code=ResultCode.OK)
#     return builder()


# @pytest.fixture()
# def mock_antenna_factory() -> MockDeviceBuilder:
#     """
#     Fixture that provides a factory for mock antennas.

#     The only special behaviour of these mocks is they return a
#     (result_code, message) tuple in response to the SetPointingDelay
#     call.

#     :return: a factory for device proxy mocks
#     """
#     builder = MockDeviceBuilder()
#     builder.add_result_command("Off", result_code=ResultCode.OK)
#     builder.add_result_command("On", result_code=ResultCode.OK)
#     return builder


# @pytest.fixture()
# def mock_tile_factory() -> MockDeviceBuilder:
#     """
#     Fixture that provides a factory for mock tiles.

#     The only special behaviour of these mocks is they return a
#     (result_code, message) tuple in response to the SetPointingDelay
#     call.

#     :return: a factory for device proxy mocks
#     """
#     builder = MockDeviceBuilder()
#     builder.add_result_command("Off", result_code=ResultCode.OK)
#     builder.add_result_command("On", result_code=ResultCode.OK)
#     builder.add_result_command("SetPointingDelay", result_code=ResultCode.OK)
#     return builder


# @pytest.fixture()
# def initial_mocks(
#     apiu_fqdn: str,
#     mock_apiu: unittest.mock.Mock,
#     antenna_fqdns: list[str],
#     mock_antenna_factory: Callable[[], unittest.mock.Mock],
#     tile_fqdns: list[str],
#     mock_tile_factory: Callable[[], unittest.mock.Mock],
# ) -> dict[str, unittest.mock.Mock]:
#     """
#     Return a specification of the mock devices to be set up in the Tango test harness.

#     This is a pytest fixture that can be used to inject pre-build mock
#     devices into the Tango test harness at specified FQDNs.

#     :param apiu_fqdn: FQDN of this station's APIU
#     :param mock_apiu: a mock APIU device to be injected into the Tango
#         test harness

#     :param antenna_fqdns: FQDNs of the antenna for which mocks are to be
#         set up
#     :param mock_antenna_factory: a factory for mock antenna devices to
#         be injected into the Tango test harness
#     :param tile_fqdns: FQDNs of the files for which mocks are to be set
#         up
#     :param mock_tile_factory: a factory for mock tile devices to be
#         injected into the Tango test harness

#     :return: specification of the mock devices to be set up in the Tango
#         test harness.
#     """
#     initial_mocks = {apiu_fqdn: mock_apiu}
#     initial_mocks.update(
#         {antenna_fqdn: mock_antenna_factory() for antenna_fqdn in antenna_fqdns}
#     )
#     initial_mocks.update({tile_fqdn: mock_tile_factory() for tile_fqdn in tile_fqdns})
#     return initial_mocks


# @pytest.fixture()
# def apiu_health_changed_callback(
#     mock_callback_factory: Callable[[], unittest.mock.Mock],
# ) -> Callable[[HealthState], None]:
#     """
#     Return a mock callback for a change in the health of the APIU.

#     :param mock_callback_factory: fixture that provides a mock callback
#         factory (i.e. an object that returns mock callbacks when
#         called).

#     :return: a mock callback to be called when the component manager
#         detects that health of the APIU has changed.
#     """
#     return mock_callback_factory()


# @pytest.fixture()
# def antenna_health_changed_callback(
#     mock_callback_factory: Callable[[], unittest.mock.Mock],
# ) -> Callable[[HealthState], None]:
#     """
#     Return a mock callback for a change in the health of an antenna.

#     :param mock_callback_factory: fixture that provides a mock callback
#         factory (i.e. an object that returns mock callbacks when
#         called).

#     :return: a mock callback to be called when the component manager
#         detects that health of an antenna has changed.
#     """
#     return mock_callback_factory()


# @pytest.fixture()
# def tile_health_changed_callback(
#     mock_callback_factory: Callable[[], unittest.mock.Mock],
# ) -> Callable[[HealthState], None]:
#     """
#     Return a mock callback for a change in the health of a tile.

#     :param mock_callback_factory: fixture that provides a mock callback
#         factory (i.e. an object that returns mock callbacks when
#         called).

#     :return: a mock callback to be called when the component manager
#         detects that health of a tile has changed.
#     """
#     return mock_callback_factory()


# @pytest.fixture()
# def is_configured_changed_callback(
#     mock_callback_factory: Callable[[], unittest.mock.Mock],
# ) -> Callable[[bool], None]:
#     """
#     Return a mock callback for a change in whether the station is configured.

#     :param mock_callback_factory: fixture that provides a mock callback
#         factory (i.e. an object that returns mock callbacks when
#         called).

#     :return: a mock callback for a change in whether the station is
#         configured.
#     """
#     return mock_callback_factory()


@pytest.fixture()
def component_state_changed_callback(
    mock_callback_deque_factory: Callable[[], unittest.mock.Mock],
) -> Callable[[], None]:
    """
    Return a mock callback for a change in whether the station changes state.

    :param mock_callback_deque_factory: fixture that provides a mock callback deque
        factory.

    :return: a mock callback deque holding a sequence of calls to component_state_changed_callback.
    """
    return mock_callback_deque_factory()


@pytest.fixture()
def max_workers() -> int:
    """
    Max worker threads available to run a LRC.

    Return an integer specifying the maximum number of worker threads available to
    execute long-running-commands.

    :return: the max number of worker threads.
    """
    max_workers = 1
    return max_workers


@pytest.fixture()
def daq_component_manager(
    tango_harness: TangoHarness,
    daq_id: int,
    receiver_interface: str,
    receiver_ip: str,
    receiver_port: int,
    logger: logging.Logger,
    max_workers: int,
    communication_state_changed_callback: MockCallable,
    component_state_changed_callback: MockCallableDeque,
) -> DaqComponentManager:
    """
    Return a daq receiver component manager.

    :param tango_harness: a test harness for Tango devices
    :param daq_id: the daq id of the daq receiver
    :param receiver_interface: The interface this DaqReceiver is to watch.
    :param receiver_ip: The IP address of this DaqReceiver.
    :param receiver_port: The port this DaqReceiver is to watch.
    :param logger: the logger to be used by this object.
    :param max_workers: max number of threads available to run a LRC.
    :param communication_state_changed_callback: callback to be
        called when the status of the communications channel between
        the component manager and its component changes
    :param component_state_changed_callback: callback to call when the
        device state changes.

    :return: a daq component manager
    """
    return DaqComponentManager(
        daq_id,
        receiver_interface,
        receiver_ip,
        receiver_port,
        logger,
        max_workers,
        communication_state_changed_callback,
        component_state_changed_callback,
    )


@pytest.fixture()
def mock_daq_component_manager(
    daq_id: int,
    receiver_interface: str,
    receiver_ip: str,
    receiver_port: int,
    logger: logging.Logger,
    max_workers: int,
    communication_state_changed_callback: MockCallable,
    component_state_changed_callback: MockCallableDeque,
) -> DaqComponentManager:
    """
    Return a daq component manager.

    :param daq_id: the daq id of the daq receiver
    :param receiver_interface: The interface this DaqReceiver is to watch.
    :param receiver_ip: The IP address of this DaqReceiver.
    :param receiver_port: The port this DaqReceiver is to watch.
    :param logger: the logger to be used by this object.
    :param max_workers: max number of threads available to run a LRC.
    :param communication_state_changed_callback: callback to be
        called when the status of the communications channel between
        the component manager and its component changes.
    :param component_state_changed_callback: callback to call when the
        device state changes.

    :return: a daq component manager
    """
    return DaqComponentManager(
        daq_id,
        receiver_interface,
        receiver_ip,
        receiver_port,
        logger,
        max_workers,
        communication_state_changed_callback,
        component_state_changed_callback,
    )


@pytest.fixture()
def mock_component_manager(
    mocker: pytest_mock.MockerFixture,
) -> unittest.mock.Mock:
    """
    Return a mock to be used as a component manager for the daq device.

    :param mocker: fixture that wraps the :py:mod:`unittest.mock`
        module

    :return: a mock to be used as a component manager for the daq
        device.
    """
    mock_component_manager = mocker.Mock()
    mock_component_manager.start_daq = MockLongRunningCommand()
    mock_component_manager.stop_daq = MockLongRunningCommand()
    mock_component_manager.configure_daq = MockLongRunningCommand()
    return mock_component_manager


@pytest.fixture()
def patched_daq_class(
    mock_component_manager: unittest.mock.Mock,
) -> type[MccsDaqReceiver]:
    """
    Return a daq device class that has been patched for testing.

    :param mock_component_manager: the mock component manage to patch
        into this daq receiver.

    :return: a daq device class that has been patched for testing.
    """

    class PatchedDaq(MccsDaqReceiver):
        """A daq class that has had its component manager mocked out for testing."""

        def create_component_manager(
            self: PatchedDaq,
        ) -> unittest.mock.Mock:
            """
            Return a mock component manager instead of the usual one.

            :return: a mock component manager
            """
            return mock_component_manager

    return PatchedDaq
