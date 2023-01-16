# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains pytest-specific test harness for MCCS unit tests."""
import json
import logging
import unittest
from typing import Any, Callable, Generator, Optional, Union

import pytest
from ska_low_mccs_common import MccsDeviceProxy
from ska_low_mccs_common.testing.mock import (
    MockCallable,
    MockCallableDeque,
    MockChangeEventCallback,
    MockDeviceBuilder,
)
from ska_low_mccs_common.testing.tango_harness import (
    DevicesToLoadType,
    DeviceToLoadType,
    TangoHarness,
)
from tango.server import command

from ska_low_mccs_daq.daq_receiver import DaqComponentManager, MccsDaqReceiver


@pytest.fixture()
def daq_receiver(
    tango_harness: TangoHarness,
) -> MccsDeviceProxy:
    """
    Return the daq_receiver device.

    :param tango_harness: a test harness for tango devices

    :return: the daq_receiver device
    """
    return tango_harness.get_device("low-mccs-daq/daqreceiver/001")


def pytest_itemcollected(item: pytest.Item) -> None:
    """
    Modify a test after it has been collected by pytest.

    This pytest hook implementation adds the "forked" custom mark to all
    tests that use the ``tango_harness`` fixture, causing them to be
    sandboxed in their own process.

    :param item: the collected test for which this hook is called
    """
    if "tango_harness" in item.fixturenames:  # type: ignore[attr-defined]
        item.add_marker("forked")


@pytest.fixture()
def devices_to_load(
    device_to_load: Optional[DeviceToLoadType],
) -> Optional[DevicesToLoadType]:
    """
    Fixture that provides specifications of devices to load.

    In this case, it maps the simpler single-device spec returned by the
    "device_to_load" fixture used in unit testing, onto the more
    general multi-device spec.

    :param device_to_load: fixture that provides a specification of a
        single device to load; used only in unit testing where tests
        will only ever stand up one device at a time.

    :return: specification of the devices (in this case, just one
        device) to load
    """
    if device_to_load is None:
        return None

    device_spec: DevicesToLoadType = {
        "path": device_to_load["path"],
        "package": device_to_load["package"],
        "devices": [
            {
                "name": device_to_load["device"],
                "proxy": device_to_load["proxy"],
            }
        ],
    }
    if "patch" in device_to_load:
        assert device_spec["devices"] is not None  # for the type checker
        device_spec["devices"][0]["patch"] = device_to_load["patch"]

    return device_spec


@pytest.fixture()
def mock_callback_factory(
    mock_callback_called_timeout: float,
    mock_callback_not_called_timeout: float,
) -> Callable[[], MockCallable]:
    """
    Return a factory that returns a new mock callback each time it is called.

    Use this fixture in tests that need more than one mock_callback. If
    your tests only needs a single mock callback, it is simpler to use
    the :py:func:`mock_callback` fixture.

    :param mock_callback_called_timeout: the time to wait for a mock
        callback to be called when a call is expected
    :param mock_callback_not_called_timeout: the time to wait for a mock
        callback to be called when a call is unexpected

    :return: a factory that returns a new mock callback each time it is
        called.
    """
    return lambda: MockCallable(
        called_timeout=mock_callback_called_timeout,
        not_called_timeout=mock_callback_not_called_timeout,
    )


@pytest.fixture(scope="module")
def initial_mocks() -> dict[str, unittest.mock.Mock]:
    """
    Fixture that registers device proxy mocks prior to patching.

    By default no initial mocks are registered, but this fixture can be
    overridden by test modules/classes that need to register initial
    mocks.

    (Overruled here with the same implementation, just to give the
    fixture module scope)

    :return: an empty dictionary
    """
    return {}


@pytest.fixture(scope="module")
def mock_factory() -> Callable[[], unittest.mock.Mock]:
    """
    Fixture that provides a mock factory for device proxy mocks.

    This default factory provides vanilla mocks,
    but this fixture can be overridden by test modules/classes
    to provide mocks with specified behaviours.

    (Overruled here with the same implementation, just to give the
    fixture module scope)

    :return: a factory for device proxy mocks
    """
    return MockDeviceBuilder()


@pytest.fixture(scope="module")
def tango_config() -> dict[str, Any]:
    """
    Fixture that returns basic configuration information for a Tango test harness.

    e.g. such as whether or not to run in a separate process.

    :return: a dictionary of configuration key-value pairs
    """
    return {"process": True}


@pytest.fixture(scope="module")
def tango_harness(
    tango_harness_factory: Callable[
        [
            dict[str, Any],
            DevicesToLoadType,
            Callable[[], unittest.mock.Mock],
            dict[str, unittest.mock.Mock],
        ],
        TangoHarness,
    ],
    tango_config: dict[str, str],
    devices_to_load: DevicesToLoadType,
    mock_factory: Callable[[], unittest.mock.Mock],
    initial_mocks: dict[str, unittest.mock.Mock],
) -> Generator[TangoHarness, None, None]:
    """
    Create a test harness for testing Tango devices.

    (This overwrites the `tango_harness` fixture, in order to change the
    fixture scope.)

    :param tango_harness_factory: a factory that provides a test harness
        for testing tango devices
    :param tango_config: basic configuration information for a tango
        test harness
    :param devices_to_load: fixture that provides a specification of the
        devices that are to be included in the devices_info dictionary
    :param mock_factory: the factory to be used to build mocks
    :param initial_mocks: a pre-build dictionary of mocks to be used
        for particular

    :yields: the test harness
    """
    with tango_harness_factory(
        tango_config, devices_to_load, mock_factory, initial_mocks
    ) as harness:
        yield harness


@pytest.fixture()
def mock_callback_deque_factory(
    mock_callback_called_timeout: float,
    mock_callback_not_called_timeout: float,
) -> Callable[[], MockCallableDeque]:
    """
    Return a factory that returns a new mock callback using a deque when called.

    Use this fixture in tests that need more than one mock_callback. If
    your tests only needs a single mock callback, it is simpler to use
    the :py:func:`mock_callback` fixture.

    :param mock_callback_called_timeout: the time to wait for a mock
        callback to be called when a call is expected
    :param mock_callback_not_called_timeout: the time to wait for a mock
        callback to be called when a call is unexpected

    :return: a factory that returns a new mock callback each time it is
        called.
    """
    return lambda: MockCallableDeque(
        called_timeout=mock_callback_called_timeout,
        not_called_timeout=mock_callback_not_called_timeout,
    )


@pytest.fixture()
def device_state_changed_callback(
    mock_change_event_callback_factory: Callable[[str], MockChangeEventCallback],
) -> MockChangeEventCallback:
    """
    Return a mock change event callback for device state change.

    :param mock_change_event_callback_factory: fixture that provides a
        mock change event callback factory (i.e. an object that returns
        mock callbacks whMockCallableen called).

    :return: a mock change event callback to be registered with the
        device via a change event subscription, so that it gets called
        when the device state changes.
    """
    return mock_change_event_callback_factory("state")


@pytest.fixture()
def device_admin_mode_changed_callback(
    mock_change_event_callback_factory: Callable[[str], MockChangeEventCallback],
) -> MockChangeEventCallback:
    """
    Return a mock change event callback for device admin mode change.

    :param mock_change_event_callback_factory: fixture that provides a
        mock change event callback factory (i.e. an object that returns
        mock callbacks when called).

    :return: a mock change event callback to be registered with the
        device via a change event subscription, so that it gets called
        when the device admin mode changes.
    """
    return mock_change_event_callback_factory("adminMode")


@pytest.fixture()
def device_health_state_changed_callback(
    mock_change_event_callback_factory: Callable[[str], MockChangeEventCallback],
) -> MockChangeEventCallback:
    """
    Return a mock change event callback for device health state change.

    :param mock_change_event_callback_factory: fixture that provides a
        mock change event callback factory (i.e. an object that returns
        mock callbacks when called).

    :return: a mock change event callback to be called when the
        device health state changes. (The callback has not yet been
        subscribed to the device; this must be done as part of the
        test.)
    """
    return mock_change_event_callback_factory("healthState")


@pytest.fixture()
def communication_state_changed_callback(
    mock_callback_factory: Callable[[], unittest.mock.Mock],
) -> unittest.mock.Mock:
    """
    Return a mock callback for component manager communication status.

    :param mock_callback_factory: fixture that provides a mock callback
        factory (i.e. an object that returns mock callbacks when
        called).

    :return: a mock callback to be called when the communication status
        of a component manager changed.
    """
    return mock_callback_factory()


@pytest.fixture()
def component_fault_callback(
    mock_callback_factory: Callable[[], unittest.mock.Mock],
) -> unittest.mock.Mock:
    """
    Return a mock callback for component fault.

    :param mock_callback_factory: fixture that provides a mock callback
        factory (i.e. an object that returns mock callbacks when
        called).

    :return: a mock callback to be called when the component manager
        detects that its component has faulted.
    """
    return mock_callback_factory()


@pytest.fixture()
def component_progress_changed_callback(
    mock_callback_factory: Callable[[], unittest.mock.Mock],
) -> unittest.mock.Mock:
    """
    Return a mock callback for component progress.

    :param mock_callback_factory: fixture that provides a mock callback
        factory (i.e. an object that returns mock callbacks when
        called).

    :return: a mock callback to be called when the component manager
        detects that its component progress value has changed.
    """
    return mock_callback_factory()


@pytest.fixture()
def device_to_load() -> Optional[DeviceToLoadType]:
    """
    Fixture that specifies the device to be loaded for testing.

    This default implementation specified no devices to be loaded,
    allowing the fixture to be left unspecified if no devices are
    needed.

    :return: specification of the device to be loaded
    """
    return None


# These are from tarc/tests/unit/conftest. If this works they'll need
# moving up a level to src/tests/conftest


@pytest.fixture()
def daq_component_manager(
    tango_harness: TangoHarness,
    daq_id: int,
    receiver_interface: str,
    receiver_ip: str,
    receiver_ports: str,
    default_consumers_to_start: str,
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
    :param receiver_ports: The ports this DaqReceiver is to watch.
    :param default_consumers_to_start: The default consumers to be started.
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
        receiver_ports,
        default_consumers_to_start,
        logger,
        max_workers,
        communication_state_changed_callback,
        component_state_changed_callback,
    )


@pytest.fixture()
def component_state_changed_callback(
    mock_callback_deque_factory: Callable[[], unittest.mock.Mock],
) -> Callable[[], None]:
    """
    Return a mock callback for a change in DaqReceiver state.

    :param mock_callback_deque_factory: fixture that provides a mock callback deque
        factory.

    :return: a mock callback deque holding a sequence of
        calls to component_state_changed_callback.
    """
    return mock_callback_deque_factory()


@pytest.fixture()
def daq_id() -> str:
    """
    Return the daq id of this daq receiver.

    :return: the daq id of this daq receiver.
    """
    # TODO: This must match the DaqId property of the daq receiver under
    # test. We should refactor the harness so that we can pull it
    # straight from the device configuration.
    return "1"


@pytest.fixture(name="daq_fqdn")
def daq_fqdn_fixture(daq_id: str) -> str:
    """
    Return the fqdn of this daq receiver.

    :param daq_id: The ID of this daq receiver.
    :return: the fqdn of this daq receiver.
    """
    return f"low-mccs-daq/daqreceiver/{daq_id.zfill(3)}"


@pytest.fixture()
def receiver_interface() -> str:
    """
    Return the interface this daq receiver is watching.

    :return: the interface this daq receiver is watching.
    """
    return "eth0"


@pytest.fixture()
def receiver_ip() -> str:
    """
    Return the ip of this daq receiver.

    :return: the ip of this daq receiver.
    """
    return "172.17.0.230"


@pytest.fixture()
def acquisition_duration() -> int:
    """
    Return the duration of data capture in seconds.

    :return: Duration of data capture.
    """
    return 2


@pytest.fixture()
def receiver_ports() -> str:
    """
    Return the port(s) this daq receiver is watching.

    :return: the port(s) this daq receiver is watching.
    """
    return "4660"


@pytest.fixture()
def default_consumers_to_start() -> str:
    """
    Return an empty string.

    :return: An empty string.
    """
    return ""


@pytest.fixture()
def max_workers() -> int:
    """
    Max worker threads available to run a LRC.

    Return an integer specifying the maximum number of worker threads available to
        execute long-running-commands.

    :return: the max number of worker threads.
    """
    return 1


@pytest.fixture(scope="session")
def patched_daq_class() -> type[MccsDaqReceiver]:
    """
    Return a daq device class that has been patched for testing.

    :return: a daq device class that has been patched for testing.
    """

    class PatchedDaq(MccsDaqReceiver):
        """MccsDaqReceiver with extra commands for testing purposes."""

        @command(dtype_in="DevString")
        def StateChangedCallback(self, argin: Union[str, bytes]) -> None:
            """
            Passthrough for component_state_changed_callback.

            This allows us to mock a call to the state_changed_callback.

            :param argin: A json string containing the state change.
            """
            self._component_state_changed_callback(json.loads(argin))

        @command(dtype_out=bool)
        def GetDaqFault(self) -> bool:
            """
            Return the fault status of this DaqReceiver.

            :return: The fault state of the device.
            """
            return self._health_model._faulty

        @command(dtype_out=int)
        def GetDaqHealth(self) -> int:
            """
            Return the health state of this DaqReceiver.

            :return: Healthstate of the device.
            """
            return self._health_state

        @command(dtype_out=str)
        def GetRunningConsumers(self) -> str:
            """
            Return a dict containing running state of consumers.

            :return: Dictionary containing state of consumers.
            """
            self.component_manager: DaqComponentManager  # Typehint only.
            return json.dumps(self.component_manager.daq_instance._running_consumers)

    return PatchedDaq
