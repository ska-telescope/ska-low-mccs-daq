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
from functools import lru_cache
from typing import Any, Callable, Iterator

import pytest
import tango
from ska_tango_testing.harness import TangoTestHarnessContext
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from tests.harness import DaqTangoTestHarness

DeviceMappingType = dict[str, dict[str, Any]]


def pytest_itemcollected(item: pytest.Item) -> None:
    """
    Modify a test after it has been collected by pytest.

    This pytest hook implementation adds the "forked" custom mark to all
    tests that use the ``tango_harness`` fixture, causing them to be
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
) -> Iterator[TangoTestHarnessContext]:
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
def change_event_callbacks_fixture(
    device_mapping: DeviceMappingType,
) -> MockTangoEventCallbackGroup:
    """
    Return a dictionary of change event callbacks with asynchrony support.

    :param device_mapping: a map from short to canonical device names

    :returns: a callback group.
    """
    keys = [
        f"{info['name']}/{attr}"
        for info in device_mapping.values()
        for attr in info["subscriptions"]
    ]
    return MockTangoEventCallbackGroup(
        *keys,
        timeout=30.0,  # TPM takes a long time to initialise
    )


@pytest.fixture(name="device_mapping", scope="module")
def device_mapping_fixture() -> DeviceMappingType:
    """
    Return a mapping from short to canonical Tango device names.

    :return: a map of short names to full Tango device names of the form
        "<domain>/<class>/<instance>", as well as attributes to subscribe to change
        events of
    """
    return {
        "daq": {
            "name": "low-mccs-daq/daqreceiver/001",
            "subscriptions": [
                "adminMode",
                "state",
                "longRunningCommandResult",
                "dataReceivedResult",
            ],
        },
    }


@pytest.fixture(name="get_device", scope="module")
def get_device_fixture(
    tango_context: TangoTestHarnessContext,
    device_mapping: DeviceMappingType,
    change_event_callbacks: MockTangoEventCallbackGroup,
) -> Callable[[str], tango.DeviceProxy]:
    """
    Return a memoized function that returns a DeviceProxy for a given name.

    :param tango_context: a TangoContextProtocol to instantiate DeviceProxys
    :param device_mapping: a map from short to canonical device names
    :param change_event_callbacks: dictionary of mock change event
        callbacks with asynchrony support

    :return: a memoized function that takes a name and returns a DeviceProxy
    """

    @lru_cache
    def _get_device(short_name: str) -> tango.DeviceProxy:
        device_data = device_mapping[short_name]
        name: str = device_data["name"]
        tango_device = tango_context.get_device(name)
        device_info = tango_device.info()
        dev_class = device_info.dev_class
        print(f"Created DeviceProxy for {short_name} - {dev_class} {name}")
        for attr in device_data.get("subscriptions", []):
            attr_value = tango_device.read_attribute(attr).value
            attr_event = change_event_callbacks[f"{name}/{attr}"]
            tango_device.subscribe_event(
                attr,
                tango.EventType.CHANGE_EVENT,
                attr_event,
            )
            print(f"Subscribed to {name}/{attr}")
            attr_event.assert_change_event(attr_value)
            print(f"Received initial value for {name}/{attr}: {attr_value}")

        return tango_device

    return _get_device


# @pytest.fixture(name="daq_grpc_server", scope="session")
# def daq_grpc_server_fixture(grpc_port: str) -> grpc.Server:
#     """
#     Stand up a local gRPC server.

#     Include this fixture in tests that require a gRPC DaqServer.

#     :param grpc_port: The port number to use for gRPC calls.

#     :yield: A gRPC server.
#     """
#     server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
#     daq_pb2_grpc.add_DaqServicer_to_server(MccsDaqServer(), server)
#     server.add_insecure_port("[::]:" + grpc_port)
#     print("Starting gRPC server...")
#     server.start()
#     time.sleep(1)
#     yield server
#     server.stop(grace=5)
