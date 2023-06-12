# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the DAQ interface."""
from __future__ import annotations

import json
import unittest.mock
from typing import Iterator

import pytest
from ska_control_model import ResultCode, TaskStatus

from ska_low_mccs_daq.interface import DaqClient, server_context


@pytest.fixture()
def mock_backend() -> unittest.mock.Mock:
    """
    Return a mock to act as backend to the DAQ server.

    :return: a mock to act as a backend to the DAQ server.
    """
    return unittest.mock.Mock()


@pytest.fixture()
def daq_server_address(mock_backend: unittest.mock.Mock) -> Iterator[str]:
    """
    Return the address of a running DAQ server with backend as provided.

    :param mock_backend: a mock to act as backend to the DAQ server.

    :yield: the address of a running DAQ server
    """
    with server_context(mock_backend, 0) as port:
        yield f"localhost:{port}"


@pytest.fixture()
def daq_client(daq_server_address: str) -> Iterator[DaqClient]:
    """
    Return a client to the DAQ server.

    :param daq_server_address: the address of a running DAQ server.

    :yield: a DAQ client.
    """
    yield DaqClient(daq_server_address)


def test_initialise(daq_client: DaqClient, mock_backend: unittest.mock.Mock) -> None:
    """
    Test that an ``initialise`` client call results in the expected backend call.

    :param daq_client: the DAQ client object
    :param mock_backend: a mock backend for the DAQ server.
    """
    mock_backend.initialise.return_value = (ResultCode.OK, "Okey dokey")

    configuration = {"foo": "bah"}
    response = daq_client.initialise(json.dumps(configuration))
    assert response == {"message": "Okey dokey"}
    mock_backend.initialise.assert_called_once_with(configuration)


def test_get_configuration(
    daq_client: DaqClient, mock_backend: unittest.mock.Mock
) -> None:
    """
    Test that a ``get_configuration`` client call results in the expected backend call.

    :param daq_client: the DAQ client object
    :param mock_backend: a mock backend for the DAQ server.
    """
    backend_configuration = {"observation_metadata": "foo", "receiver_ports": "bah"}
    mock_backend.get_configuration.return_value = backend_configuration
    response = daq_client.get_configuration()
    assert response == backend_configuration
    mock_backend.get_configuration.assert_called_once_with()


def test_configure_daq(daq_client: DaqClient, mock_backend: unittest.mock.Mock) -> None:
    """
    Test that a ``configure_daq`` client call results in the expected backend call.

    :param daq_client: the DAQ client object
    :param mock_backend: a mock backend for the DAQ server.
    """
    expected_return = (ResultCode.OK, "Okey dokey")
    mock_backend.configure.return_value = expected_return

    configuration = {"foo": "bah"}
    response = daq_client.configure_daq(json.dumps(configuration))
    assert response == expected_return
    mock_backend.configure.assert_called_once_with(configuration)


def test_get_status(daq_client: DaqClient, mock_backend: unittest.mock.Mock) -> None:
    """
    Test that a ``get_status`` client call results in the expected backend call.

    :param daq_client: the DAQ client object
    :param mock_backend: a mock backend for the DAQ server.
    """
    backend_status = {"foo": "bah"}
    mock_backend.get_status.return_value = backend_status
    response = daq_client.get_status()
    assert response == json.dumps(backend_status)
    mock_backend.get_status.assert_called_once_with()


def test_start_daq(daq_client: DaqClient, mock_backend: unittest.mock.Mock) -> None:
    """
    Test that a ``start_daq`` client call results in the expected backend call.

    :param daq_client: the DAQ client object
    :param mock_backend: a mock backend for the DAQ server.
    """
    mock_backend.start.return_value = iter(
        ["LISTENING", ("foo", "foo.hdf5"), ("bah", "bah.hdf5"), "STOPPED"]
    )

    modes_to_start = "foo, bah"
    responses = daq_client.start_daq(modes_to_start)

    assert next(responses) == {
        "status": TaskStatus.IN_PROGRESS,
        "message": "Start Command issued to gRPC stub",
    }
    assert next(responses) == {
        "status": TaskStatus.COMPLETED,
        "message": "Daq has been started and is listening",
    }
    assert next(responses) == {"types": "foo", "files": "foo.hdf5"}
    assert next(responses) == {"types": "bah", "files": "bah.hdf5"}

    with pytest.raises(StopIteration):
        _ = next(responses)

    mock_backend.start.assert_called_once_with(modes_to_start)


def test_stop_daq(daq_client: DaqClient, mock_backend: unittest.mock.Mock) -> None:
    """
    Test that a ``stop_daq`` client call results in the expected backend call.

    :param daq_client: the DAQ client object
    :param mock_backend: a mock backend for the DAQ server.
    """
    expected_return = (ResultCode.OK, "Okey dokey")
    mock_backend.stop.return_value = expected_return

    response = daq_client.stop_daq()
    assert response == expected_return
    mock_backend.stop.assert_called_once_with()
