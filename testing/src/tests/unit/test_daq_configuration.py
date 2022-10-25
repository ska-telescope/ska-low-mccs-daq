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

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from ska_low_mccs_common import MccsDeviceProxy
from ska_low_mccs_common.testing.tango_harness import DevicesToLoadType

from ska_low_mccs_daq.daq_receiver import MccsDaqReceiver


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

scenarios("daq_configuration.feature")


@given("A MccsDaqReceiver is available", target_fixture="daq_receiver_bdd")
def daq_receiver_bdd(daq_receiver: MccsDeviceProxy) -> MccsDeviceProxy:
    """
    Return a DeviceProxy to an instance of MccsDaqReceiver.

    :param daq_receiver: The daq_receiver fixture to use.

    :return: A MccsDeviceProxy instance to MccsDaqReceiver stored in the target_fixture `daq_receiver_bdd`.
    """
    return daq_receiver


@when(
    parsers.cfparse(
        "We pass a {configuration:Dict} to the MccsDaqReceiver", extra_types=EXTRA_TYPES
    )
)
def feed_daq_configuration_file(daq_receiver_bdd, configuration):
    """Feed the configuration into the daq_receiver, this expects a string
    representation of a dictionary."""
    # MccsDaqReceiver expects a string as input, this will be a string representation of a dictionary.
    daq_receiver_bdd.Configure(configuration)


@then(
    parsers.cfparse(
        "The DAQ_reciever interface has that {configuration:Dict}",
        extra_types=EXTRA_TYPES,
    )
)
def assert_daq_instance_is_configuration_correctly(daq_receiver_bdd, configuration):
    """
    Check whether the daq_instance has the same configuration that we sent to the
    daq_receiver.

    notes: we may only send a subset of the configuration to the DaqInstance.
    - The DaqInstance has some type casting therefore this is performed in the test (does not seem ideal as means the test is duplicating code in the daq_receiver_interface.
    Could we assume the populate_configuration is passed the correct types? (type check before we call it?)).
    - There are certain configuration parameters that can be overriden internally by the daq_receiver_interface.
    These are considered in scenario 'Check that when we configure the MccsDaqReciever with values we expect to be overridden, they are!'"
    """
    # first convert to a dictionary
    configuration = json.loads(configuration)

    # The daq_receiver_interface.py performes type casting in some cases, this is mimicked here (not ideal) for testing purposes.
    if (
        "receiver_ports" in configuration
        and configuration["receiver_ports"] is not list
    ):
        value = [int(x) for x in value.split(",")]
        configuration["receiver_ports"] == value

    # This is a edge case scenario with another test
    if "receiver_ip" in configuration and configuration["receiver_ip"] == "":
        raise ValueError(
            "There is a seperate test scenario for this 'Check receiver_ip is assigned address if not defined'"
        )

    if "observation_metadata" in configuration:
        raise ValueError("This is not a parameter tested here")

    # daq_receiver_bdd.configuration().items() will fail in the current state.
    # todo: create a method on the MccsDaqReceiver to get configuration, or,
    # use a patch in device_to_load to get the configuration from component manager
    # note: daq_receiver_bdd.configuration() does not exist atm!
    assert configuration.items() <= daq_receiver_bdd.configuration().items()


@when(
    parsers.cfparse(
        "We pass an {configuration_param:w} of {value:w} {type_cast:w} to the MccsDaqReceiver",
        extra_types=EXTRA_TYPES,
    )
)
def pass_key_value_to_daq(daq_receiver_bdd, configuration_param, value, type_cast):
    """
    MccsDaqReceiver expects a string representation of a dictionary.

    Some nasty string hacking going on here. Reason for the string
    hacking is it was a easy win. This can probably be done in a neater
    way using the pytest_bdd.parsers
    """
    # could not find a way to pass in "" so i have passed "None" and converted it here.
    if value == "None":
        value = ""

    # create a string representation of a dictionary (nasty hack)
    if type_cast == "int":
        value = int(value)
        configuration = f'{{"{configuration_param}":{value}}}'
    else:
        configuration = f'{{"{configuration_param}":"{value}"}}'

    # configure DAQ using the string representation of a dictionary
    daq_receiver_bdd.Configure(configuration)


@then(
    parsers.cfparse(
        "The DAQ_reciever interface overrides the value when passed {configuration_param:w} of {value:w}",
        extra_types=EXTRA_TYPES,
    )
)
def check_response_as_expected(daq_receiver_bdd, configuration_param, value):
    """
    Specific parameters passed to the daq_receiver_interface are overridden.

    This overriding is a method internal to the daq_receiver_interface This
    CAN occur for:
    -receiver_ports if it is not a list
    The ports should be converted to a list of integers (in accordance to daq_receiver_interface)
    -receiver_ip if its value is ''
    The ip if assigned a value which depends on the value of the 'receiver_interface',
    here we are not testing the internal functionality of _get_ip_address()
    only testing that the value hass changed (i.e proving that it has been overridden!)
    """
    if configuration_param == "receiver_ip" and value == "None":
        # note: daq_receiver_bdd.configuration() does not exist atm!
        assert daq_receiver_bdd.configuration()["receiver_ip"] != ""
    elif configuration_param == "receiver_ports" and type(value) is not list:
        # note: daq_receiver_bdd.configuration() does not exist atm!
        assert daq_receiver_bdd.configuration()["receiver_ports"] == [
            int(x) for x in value.split(",")
        ]
    else:
        raise ValueError("The BDD test was not expecting this configuration parameter")
