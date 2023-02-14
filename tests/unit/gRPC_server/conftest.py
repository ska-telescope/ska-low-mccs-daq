# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module defined a pytest harness for testing the MCCS station module."""
from __future__ import annotations

import time
from concurrent import futures

import grpc
import pytest

from ska_low_mccs_daq.gRPC_server import MccsDaqServer
from ska_low_mccs_daq.gRPC_server.generated_code import daq_pb2_grpc


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
