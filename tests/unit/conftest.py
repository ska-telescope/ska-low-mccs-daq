# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains pytest-specific test harness for MCCS unit tests."""
from typing import Iterator

import pytest
from ska_tango_testing.mock import MockCallableGroup
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup
from tango.server import Device

from ska_low_mccs_daq.gRPC_server.daq_grpc_server import MccsDaqServer
from tests.harness import DaqTangoTestHarness, DaqTangoTestHarnessContext


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


@pytest.fixture(name="callbacks")
def callbacks_fixture() -> MockCallableGroup:
    """
    Return a dictionary of callbacks with asynchrony support.

    :return: a collections.defaultdict that returns callbacks by name.
    """
    return MockCallableGroup(
        "communication_state",
        "component_state",
        "received_data",
        "task",
        "extra_daq_mode",
        "task_start_daq",
        timeout=5.0,
    )


@pytest.fixture(name="change_event_callbacks")
def change_event_callbacks_fixture() -> MockTangoEventCallbackGroup:
    """
    Return a dictionary of change event callbacks with asynchrony support.

    :return: a collections.defaultdict that returns change event
        callbacks by name.
    """
    return MockTangoEventCallbackGroup(
        "healthState",
        "dataReceivedResult",
        # TODO: Add more event types here as the tests grow
    )


@pytest.fixture(name="daq_id")
def daq_id_fixture() -> int:
    """
    Return the daq id of this daq receiver.

    :return: the daq id of this daq receiver.
    """
    return 1


@pytest.fixture(name="receiver_interface")
def receiver_interface_fixture() -> str:
    """
    Return the interface this daq receiver is watching.

    :return: the interface this daq receiver is watching.
    """
    return "eth0"


@pytest.fixture(name="receiver_ip")
def receiver_ip_fixture() -> str:
    """
    Return the ip of this daq receiver.

    :return: the ip of this daq receiver.
    """
    return "172.17.0.230"


@pytest.fixture(name="acquisition_duration")
def acquisition_duration_fixture() -> int:
    """
    Return the duration of data capture in seconds.

    :return: Duration of data capture.
    """
    return 2


@pytest.fixture(name="receiver_ports")
def receiver_ports_fixture() -> list[int]:
    """
    Return the port(s) this daq receiver is watching.

    :return: the port(s) this daq receiver is watching.
    """
    return [4660]


@pytest.fixture(name="empty_consumer_list_to_start")
def empty_consumer_list_to_start_fixture() -> str:
    """
    Return an empty string.

    :return: An empty string.
    """
    return ""


@pytest.fixture(name="max_workers")
def max_workers_fixture() -> int:
    """
    Max worker threads available to run a LRC.

    Return an integer specifying the maximum number of worker threads available to
        execute long-running-commands.

    :return: the max number of worker threads.
    """
    return 1


@pytest.fixture(name="device_class_under_test")
def device_class_under_test_fixture() -> type[Device] | str:
    """
    Return the device class under test.

    This will usually be ``ska_low_mccs_daq.MccsDaqReceiver``,
    and is defined as such here.
    However some tests override this with a patched subclass.

    :return: the device class under test.
    """
    return "ska_low_mccs_daq.MccsDaqReceiver"


@pytest.fixture(name="test_context")
def test_context_fixture(
    device_class_under_test: type[Device] | str,
    receiver_interface: str,
    receiver_ip: str,
    receiver_ports: list[int],
) -> Iterator[DaqTangoTestHarnessContext]:
    """
    Yield a tango harness against which to run tests of the deployment.

    :param device_class_under_test:
        the Tango device class to deploy and test.
    :param receiver_interface: network interface on which the DAQ
        receiver receives packets
    :param receiver_ip: IP address on which the DAQ receiver receives
        packets
    :param receiver_ports: port on which the DAQ receiver receives
        packets.

    :yields: a test harness context.
    """
    test_harness = DaqTangoTestHarness()
    test_harness.add_daq_instance(1, MccsDaqServer())
    test_harness.add_daq_device(
        1,
        address=None,  # dynamically get address of DAQ instance
        receiver_interface=receiver_interface,
        receiver_ip=receiver_ip,
        receiver_ports=receiver_ports,
        consumers_to_start=["DaqModes.INTEGRATED_CHANNEL_DATA"],
        device_class=device_class_under_test,
    )

    with test_harness as test_context:
        yield test_context


@pytest.fixture(name="grpc_channel")
def grpc_channel_fixture(
    test_context: DaqTangoTestHarnessContext,
    daq_id: int,
) -> Iterator[str]:
    """
    Yield the channel on which the gRPC server is available.

    :param test_context: the context in which the tests are running.
    :param daq_id: the ID of the daq receiver

    :yield: the gRPC channel.
    """
    grpc_host, grpc_port = test_context.get_grpc_address(daq_id)
    yield f"{grpc_host}:{grpc_port}"
