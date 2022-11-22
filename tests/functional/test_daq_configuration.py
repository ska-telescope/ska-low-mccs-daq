# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq configuration."""
from __future__ import annotations

import json
import socket

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from ska_low_mccs_common import MccsDeviceProxy
from ska_low_mccs_common.testing.tango_harness import DevicesToLoadType


@pytest.fixture(scope="module")
def devices_to_load() -> DevicesToLoadType:
    """
    Fixture that specifies the devices to be loaded for testing.

    Here we specify that we want a daq receiver from the ska-low-mccs-daq chart.

    :return: specification of the devices to be loaded
    """
    return {
        "path": "charts/ska-low-mccs-daq/data/configuration.json",
        "package": "ska_low_mccs_daq",
        "devices": [
            {"name": "daqreceiver_001", "proxy": MccsDeviceProxy},
        ],
    }


EXTRA_TYPES = {
    "Dict": str,
}

scenarios("./features/daq_configuration.feature")


@given("A MccsDaqReceiver is available", target_fixture="daq_receiver_bdd")
def daq_receiver_bdd(daq_receiver: MccsDeviceProxy) -> MccsDeviceProxy:
    """
    Return a DeviceProxy to an instance of MccsDaqReceiver.

    :param daq_receiver: The daq_receiver fixture to use.

    :return: A MccsDeviceProxy instance to MccsDaqReceiver stored in the target_fixture
        `daq_receiver_bdd`.
    """
    return daq_receiver


@when(
    parsers.cfparse(
        "We pass a {configuration:Dict} to the MccsDaqReceiver", extra_types=EXTRA_TYPES
    )
)
def feed_daq_configuration_file(
    daq_receiver_bdd: MccsDeviceProxy, configuration: str
) -> None:
    """
    Feed the configuration into the daq_receiver.

    :param daq_receiver_bdd: The daq_receiver fixture to use.
    :param configuration: A string representation of a dictionary for configuration.
    """
    # MccsDaqReceiver expects a string as input, this will be a string representation
    # of a dictionary.
    daq_receiver_bdd.Configure(configuration)


@then(
    parsers.cfparse(
        "The DAQ_receiver interface has a {configuration_expected:Dict}",
        extra_types=EXTRA_TYPES,
    )
)
def assert_daq_instance_is_configuration_correctly(
    daq_receiver_bdd: MccsDeviceProxy, configuration_expected: str
) -> None:
    """
    Assert daq_instance has the same configuration that we sent to the daq_receiver.

    :param daq_receiver_bdd: The daq_receiver fixture to use.
    :param configuration_expected: A string representing the expected configuration

    Notes: we may only send a subset of the configuration to the DaqInstance.
    """
    configuration_dict = json.loads(configuration_expected)

    config_jstr = daq_receiver_bdd.command_inout("GetConfiguration")
    retrieved_daq_config = json.loads(config_jstr)

    # TODO: create a method on the MccsDaqReceiver to get configuration, assumed here daq_receiver_bdd.configuration()
    assert configuration_dict.items() <= retrieved_daq_config.items()


@when(
    parsers.cfparse(
        (
            "We pass parameter {configuration_param:w} of value {value:w} "
            "to the MccsDaqReceiver"
        ),
        extra_types=EXTRA_TYPES,
    )
)
def pass_key_value_to_daq(
    daq_receiver_bdd: MccsDeviceProxy, configuration_param: str, value: str
) -> None:
    """
    Pass a string representation of a dictionary to MccsDaqReceiver.

    :param daq_receiver_bdd: The daq_receiver fixture to use.
    :param configuration_param: The parameter of interest
    :param value: The value of that parameter
    """
    # could not find a way to pass in "" so i have passed "None" and converted it here.
    if value == "None":
        value = ""

    configuration = f'{{"{configuration_param}":{value}}}'

    # configure DAQ using the string representation of a dictionary
    daq_receiver_bdd.Configure(configuration)


@then(
    parsers.cfparse(
        "The DAQ receiver interface has a valid {receiver_ip:w}",
        extra_types=EXTRA_TYPES,
    )
)
def check_response_as_expected(
    daq_receiver_bdd: MccsDeviceProxy, receiver_ip: str
) -> None:
    """
    Specific parameters passed to the daq_receiver_interface are overridden.

    :param daq_receiver_bdd: The daq_receiver fixture to use.
    :param receiver_ip: The parameter of interest

    If the ip is not assigned it is assigned the IP address of a specified interface
    'receiver_interface'. This tests that the value has changed.
    TODO: determine what other values are allowed
    """
    daq_config_jstr = daq_receiver_bdd.command_inout("GetConfiguration")
    retrieved_daq_config = json.loads(daq_config_jstr)
    receiver_port = retrieved_daq_config[receiver_ip]

    if receiver_port == "":
        # the ip address wes unchanged
        assert True
    try:
        socket.inet_aton(receiver_port)
        # the ip address is valid
        assert True
    except IOError:
        # the ip address is not valid
        assert False
