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

import pytest
from ska_tango_testing.mock import MockCallableGroup

from ska_low_mccs_daq.daq_receiver import DaqComponentManager
from tests.harness import DaqTangoTestHarnessContext


# pylint: disable=too-many-arguments
@pytest.fixture(name="daq_component_manager")
def daq_component_manager_fixture(
    test_context: DaqTangoTestHarnessContext,
    daq_id: int,
    daq_address: str,
    receiver_interface: str,
    receiver_ip: str,
    receiver_ports: str,
    empty_consumer_list_to_start: str,
    logger: logging.Logger,
    max_workers: int,
    callbacks: MockCallableGroup,
) -> DaqComponentManager:
    """
    Return a daq receiver component manager.

    :param test_context: the context in which the tests are running.
    :param daq_id: the ID of the daq receiver
    :param daq_address: the address of the DAQ server
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
        daq_address,
        empty_consumer_list_to_start,
        logger,
        max_workers,
        callbacks["communication_state"],
        callbacks["component_state"],
        callbacks["received_data"],
    )
