# -*- coding: utf-8 -*
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains pytest-specific test harness for MCCS unit tests."""
import unittest
from typing import Callable, Optional

import pytest
from ska_low_mccs_common.testing.mock import (
    MockCallable,
    MockCallableDeque,
    MockChangeEventCallback,
)
from ska_low_mccs_common.testing.tango_harness import (
    DevicesToLoadType,
    DeviceToLoadType,
)


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


@pytest.fixture(name="devices_to_load")
def devices_to_load_fixture(
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


@pytest.fixture(name="mock_callback_factory")
def mock_callback_factory_fixture(
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


@pytest.fixture(name="mock_callback_deque_factory")
def mock_callback_deque_factory_fixture(
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


@pytest.fixture(name="device_state_changed_callback")
def device_state_changed_callback_fixture(
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


@pytest.fixture(name="device_admin_mode_changed_callback")
def device_admin_mode_changed_callback_fixture(
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


@pytest.fixture(name="device_health_state_changed_callback")
def device_health_state_changed_callback_fixture(
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


@pytest.fixture(name="communication_state_changed_callback")
def communication_state_changed_callback_fixture(
    mock_callback_factory: Callable[[], unittest.mock.Mock],
) -> MockCallable:
    """
    Return a mock callback for component manager communication status.

    :param mock_callback_factory: fixture that provides a mock callback
        factory (i.e. an object that returns mock callbacks when
        called).

    :return: a mock callback to be called when the communication status
        of a component manager changed.
    """
    return mock_callback_factory()


@pytest.fixture(name="component_fault_callback")
def component_fault_callback_fixture(
    mock_callback_factory: Callable[[], unittest.mock.Mock],
) -> MockCallable:
    """
    Return a mock callback for component fault.

    :param mock_callback_factory: fixture that provides a mock callback
        factory (i.e. an object that returns mock callbacks when
        called).

    :return: a mock callback to be called when the component manager
        detects that its component has faulted.
    """
    return mock_callback_factory()


@pytest.fixture(name="component_progress_changed_callback")
def component_progress_changed_callback_fixture(
    mock_callback_factory: Callable[[], unittest.mock.Mock],
) -> MockCallable:
    """
    Return a mock callback for component progress.

    :param mock_callback_factory: fixture that provides a mock callback
        factory (i.e. an object that returns mock callbacks when
        called).

    :return: a mock callback to be called when the component manager
        detects that its component progress value has changed.
    """
    return mock_callback_factory()


@pytest.fixture(name="device_to_load")
def device_to_load_fixture() -> Optional[DeviceToLoadType]:
    """
    Fixture that specifies the device to be loaded for testing.

    This default implementation specified no devices to be loaded,
    allowing the fixture to be left unspecified if no devices are
    needed.

    :return: specification of the device to be loaded
    """
    return None
