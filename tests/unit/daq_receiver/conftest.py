# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module defined a pytest harness for testing the MCCS daq_receiver module."""
from __future__ import annotations

import logging
import time
import unittest.mock
from concurrent import futures

import grpc
import pytest
import pytest_mock
from ska_control_model import ResultCode
from ska_tango_testing.mock import MockCallableGroup

from ska_low_mccs_daq.daq_receiver import DaqComponentManager
from ska_low_mccs_daq.gRPC_server.daq_grpc_server import MccsDaqServer
from ska_low_mccs_daq.gRPC_server.generated_code import daq_pb2_grpc


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
    daq_grpc_server: grpc.Server,
) -> DaqComponentManager:
    """
    Return a daq receiver component manager.

    :param daq_id: the daq id of the daq receiver
    :param receiver_interface: The interface this DaqReceiver is to watch.
    :param receiver_ip: The IP address of this DaqReceiver.
    :param receiver_ports: The ports this DaqReceiver is to watch.
    :param grpc_port: The port number to use for gRPC calls.
    :param grpc_host: The hostname of the gRPC server to use.
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
    :param grpc_port: The port number to use for gRPC calls.
    :param grpc_host: The hostname of the gRPC server to use.
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
