# -*- coding: utf-8 -*-
# pylint: skip-file
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains pytest-specific test harness for MCCS unit tests."""
from __future__ import annotations

import os
from typing import Any, Iterator

import pytest
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from tests.harness import DaqTangoTestHarness, DaqTangoTestHarnessContext

DeviceMappingType = dict[str, dict[str, Any]]


def pytest_itemcollected(item: pytest.Item) -> None:
    """
    Modify a test after it has been collected by pytest.

    This pytest hook implementation adds the "forked" custom mark to all
    tests that use the ``test_context`` fixture, causing them to be
    sandboxed in their own process.

    :param item: the collected test for which this hook is called
    """
    if "test_context" in item.fixturenames:  # type: ignore[attr-defined]
        item.add_marker("forked")


@pytest.fixture(name="daq_id", scope="session")
def daq_id_fixture() -> int:
    """
    Return the daq id of this daq receiver.

    :return: the daq id of this daq receiver.
    """
    return 1


@pytest.fixture(name="receiver_interface", scope="session")
def receiver_interface_fixture() -> str:
    """
    Return the interface this daq receiver is watching.

    :return: the interface this daq receiver is watching.
    """
    return "eth0"


@pytest.fixture(name="receiver_ip", scope="session")
def receiver_ip_fixture() -> str:
    """
    Return the ip of this daq receiver.

    :return: the ip of this daq receiver.
    """
    return "172.17.0.230"


@pytest.fixture(name="acquisition_duration", scope="session")
def acquisition_duration_fixture() -> int:
    """
    Return the duration of data capture in seconds.

    :return: Duration of data capture.
    """
    return 2


@pytest.fixture(name="receiver_ports", scope="session")
def receiver_ports_fixture() -> list[int]:
    """
    Return the port(s) this daq receiver is watching.

    :return: the port(s) this daq receiver is watching.
    """
    return [4660]


@pytest.fixture()
def default_consumers_to_start() -> str:
    """
    Return an empty string.

    :return: An empty string.
    """
    return ""


@pytest.fixture(name="true_context", scope="session")
def true_context_fixture(request: pytest.FixtureRequest) -> bool:
    """
    Return whether to test against an existing Tango deployment.

    If True, then Tango is already deployed, and the tests will be run
    against that deployment.

    If False, then Tango is not deployed, so the test harness will stand
    up a test context and run the tests against that.

    :param request: A pytest object giving access to the requesting test
        context.

    :return: whether to test against an existing Tango deployment
    """
    if request.config.getoption("--true-context"):
        return True
    if os.getenv("TRUE_TANGO_CONTEXT", None):
        return True
    return False


@pytest.fixture(name="test_context", scope="session")
def test_context_fixture(
    true_context: bool,
    daq_id: int,
    receiver_interface: str,
    receiver_ip: str,
    receiver_ports: list[int],
) -> Iterator[DaqTangoTestHarnessContext]:
    """
    Return a tango harness against which to run tests of the deployment.

    :param true_context: Whether to test against an existing Tango
        deployment
    :param daq_id: the ID of the daq receiver
    :param receiver_interface: network interface on which the DAQ
        receiver receives packets
    :param receiver_ip: IP address on which the DAQ receiver receives
        packets
    :param receiver_ports: port on which the DAQ receiver receives
        packets.

    :yields: a test harness context.
    """
    test_harness = DaqTangoTestHarness()
    if not true_context:
        from ska_low_mccs_daq.gRPC_server.daq_grpc_server import MccsDaqServer

        test_harness.add_daq_instance(daq_id, MccsDaqServer())
        test_harness.add_daq_device(
            daq_id,
            address=None,  # dynamically get address of DAQ instance
            receiver_interface=receiver_interface,
            receiver_ip=receiver_ip,
            receiver_ports=receiver_ports,
            consumers_to_start=["DaqModes.INTEGRATED_CHANNEL_DATA"],
        )

    with test_harness as test_context:
        yield test_context


@pytest.fixture(name="change_event_callbacks", scope="module")
def change_event_callbacks_fixture() -> MockTangoEventCallbackGroup:
    """
    Return a dictionary of change event callbacks with asynchrony support.

    :returns: a callback group.
    """
    return MockTangoEventCallbackGroup(
        "state",
        timeout=30.0,  # TPM takes a long time to initialise
    )
