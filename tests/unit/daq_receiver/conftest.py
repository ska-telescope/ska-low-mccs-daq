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
import time
import unittest.mock
from concurrent import futures

import grpc
import pytest
import pytest_mock
from ska_control_model import ResultCode, TaskStatus
from ska_tango_testing.mock import MockCallableGroup

from ska_low_mccs_daq.daq_receiver import DaqComponentManager
from ska_low_mccs_daq.gRPC_server.daq_grpc_server import MccsDaqServer
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
    The port on which the gRCP server is to communicate.

    :return: the gRCP port number.
    """
    return "50051"


@pytest.fixture(name="grpc_host", scope="session")
def grpc_host_fixture() -> str:
    """
    The host on which the gRCP server is available.

    :return: the gRCP port number.
    """
    return "localhost"


@pytest.fixture(name="daq_grpc_server", scope="session")
def daq_grpc_server_fixture(grpc_port):
    """
    Stand up a local gRPC server.

    Include this fixture in tests that require a gRPC DaqServer.

    :yield: A gRPC server.
    """
    print("Starting daq server...", flush=True)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    daq_pb2_grpc.add_DaqServicer_to_server(MccsDaqServer(), server)
    server.add_insecure_port("[::]:" + grpc_port)
    server.start()
    print("Server started, listening on " + grpc_port, flush=True)
    time.sleep(0.1)
    yield


# pylint: disable=too-many-arguments
@pytest.fixture(name="daq_component_manager")
def daq_component_manager_fixture(
    daq_id: int,
    receiver_interface: str,
    receiver_ip: str,
    receiver_ports: str,
    grpc_port: str,
    grpc_host: str,
    empty_consumer_list_to_start: str,
    logger: logging.Logger,
    max_workers: int,
    callbacks: MockCallableGroup,
    daq_grpc_server,
) -> DaqComponentManager:
    """
    Return a daq receiver component manager.

    :param daq_id: the daq id of the daq receiver
    :param receiver_interface: The interface this DaqReceiver is to watch.
    :param receiver_ip: The IP address of this DaqReceiver.
    :param receiver_ports: The ports this DaqReceiver is to watch.
    :param empty_consumer_list_to_start: The default consumers to be started.
    :param logger: the logger to be used by this object.
    :param max_workers: max number of threads available to run a LRC.
    :param callbacks: a dictionary from which callbacks with asynchrony
        support can be accessed.
    :param daq_grpc_server: A fixture to stand up a local gRPC server for testing.

    :return: a daq component manager
    """
    return DaqComponentManager(
        daq_id,
        receiver_interface,
        receiver_ip,
        receiver_ports,
        grpc_port,
        grpc_host,
        empty_consumer_list_to_start,
        logger,
        max_workers,
        callbacks["communication_state"],
        callbacks["component_state"],
        callbacks["received_data"],
    )


# pylint: disable=too-many-arguments
@pytest.fixture(name="mock_daq_component_manager")
def mock_daq_component_manager_fixture(
    daq_id: int,
    receiver_interface: str,
    receiver_ip: str,
    receiver_ports: str,
    grpc_port: str,
    grpc_host: str,
    empty_consumer_list_to_start: str,
    logger: logging.Logger,
    max_workers: int,
    callbacks: MockCallableGroup,
) -> DaqComponentManager:
    """
    Return a daq component manager.

    :param daq_id: the daq id of the daq receiver
    :param receiver_interface: The interface this DaqReceiver is to watch.
    :param receiver_ip: The IP address of this DaqReceiver.
    :param receiver_ports: The ports this DaqReceiver is to watch.
    :param empty_consumer_list_to_start: The default consumers to be started.
    :param logger: the logger to be used by this object.
    :param max_workers: max number of threads available to run a LRC.
    :param callbacks: a dictionary from which callbacks with asynchrony
        support can be accessed.

    :return: a daq component manager
    """
    return DaqComponentManager(
        daq_id,
        receiver_interface,
        receiver_ip,
        receiver_ports,
        grpc_port,
        grpc_host,
        empty_consumer_list_to_start,
        logger,
        max_workers,
        callbacks["communication_state"],
        callbacks["component_state"],
        callbacks["received_data"],
    )


@pytest.fixture(name="mock_component_manager")
def mock_component_manager_fixture(
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
    configuration = {
        "start_daq.return_value": (ResultCode.OK, "Daq started"),
        "stop_daq.return_value": (ResultCode.OK, "Daq stopped"),
        "_set_consumers_to_start.return_value": (
            ResultCode.OK,
            "SetConsumers command completed OK",
        ),
    }
    mock_component_manager.configure_mock(**configuration)
    return mock_component_manager
