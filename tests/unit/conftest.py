# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains pytest-specific test harness for MCCS unit tests."""
import time
from concurrent import futures

import grpc
import pytest
from ska_tango_testing.mock import MockCallableGroup
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from ska_low_mccs_daq.gRPC_server import MccsDaqServer
from ska_low_mccs_daq.gRPC_server.generated_code import daq_pb2_grpc


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
def daq_id_fixture() -> str:
    """
    Return the daq id of this daq receiver.

    :return: the daq id of this daq receiver.
    """
    return "1"


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
def receiver_ports_fixture() -> str:
    """
    Return the port(s) this daq receiver is watching.

    :return: the port(s) this daq receiver is watching.
    """
    return "4660"


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


@pytest.fixture(name="grpc_port", scope="session")
def grpc_port_fixture() -> str:
    """
    Return the port on which the gRPC server is to communicate.

    :return: the gRPC port number.
    """
    return "50051"


@pytest.fixture(name="grpc_host", scope="session")
def grpc_host_fixture() -> str:
    """
    Return the host on which the gRPC server is available.

    :return: the gRPC host.
    """
    return "localhost"


@pytest.fixture(name="grpc_channel", scope="session")
def grpc_channel_fixture(grpc_host: str, grpc_port: str) -> str:
    """
    Return the channel on which the gRPC server is available.

    The channel is a combination of hostname and port.

    :param grpc_host: The gRPC host to use.
    :param grpc_port: The gRPC port to use.

    :return: the gRPC channel.
    """
    return f"{grpc_host}:{grpc_port}"


@pytest.fixture(name="daq_grpc_server", scope="session")
def daq_grpc_server_fixture(grpc_port: str) -> grpc.Server:
    """
    Stand up a local gRPC server.

    Include this fixture in tests that require a gRPC DaqServer.

    :param grpc_port: The port number to use for gRPC calls.

    :yield: A gRPC server.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    daq_pb2_grpc.add_DaqServicer_to_server(MccsDaqServer(), server)
    server.add_insecure_port("[::]:" + grpc_port)
    print("Starting gRPC server...")
    server.start()
    time.sleep(0.1)
    yield server
    server.stop(grace=3)
