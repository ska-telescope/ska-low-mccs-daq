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
def feed_daq_configuration_file(
    daq_receiver_bdd: MccsDeviceProxy, configuration: str
) -> None:
    """
    Feed the configuration into the daq_receiver.

    :param daq_receiver_bdd: The daq_receiver fixture to use.
    :param configuration: A string representation of a dictionary for configuration.
    """
    # MccsDaqReceiver expects a string as input, this will be a string representation of a dictionary.
    daq_receiver_bdd.Configure(configuration)


@then(
    parsers.cfparse(
        "The DAQ_reciever interface has that {configuration:Dict}",
        extra_types=EXTRA_TYPES,
    )
)
def assert_daq_instance_is_configuration_correctly(
    daq_receiver_bdd: MccsDeviceProxy, configuration: str
) -> None:
    """
    Assert daq_instance has the same configuration that we sent to the daq_receiver.

    :param daq_receiver_bdd: The daq_receiver fixture to use.
    :param configuration: A string representation of a dictionary for configuration.

    Notes: we may only send a subset of the configuration to the DaqInstance.
    -The DaqInstance has some type casting therefore this is performed in the test.
    -There are certain configuration parameters that can be overriden internally by the daq_receiver_interface.
    These are not tested here and assert failure if passed to test
    """
    # first convert to a dictionary
    configuration_dict = json.loads(configuration)

    # The daq_receiver_interface.py performes type casting in some cases, this is mimicked here (not ideal) for testing purposes.
    if (
        "receiver_ports" in configuration_dict
        and configuration_dict["receiver_ports"] is not list
    ):
        value = [int(x) for x in configuration_dict["receiver_ports"].split(",")]
        configuration_dict["receiver_ports"] = value

    # This is a edge case scenario with another test
    if "receiver_ip" in configuration_dict and configuration_dict["receiver_ip"] == "":
        assert False

    if "observation_metadata" in configuration_dict:
        assert False

    # daq_receiver_bdd.configuration().items() will fail in the current state.
    # todo: create a method on the MccsDaqReceiver to get configuration, or,
    # use a patch in device_to_load to get the configuration from component manager
    # note: daq_receiver_bdd.configuration() does not exist atm!
    assert configuration_dict.items() <= daq_receiver_bdd.configuration().items()


@when(
    parsers.cfparse(
        "We pass an {configuration_param:w} of {value:w} {type_cast:w} to the MccsDaqReceiver",
        extra_types=EXTRA_TYPES,
    )
)
def pass_key_value_to_daq(
    daq_receiver_bdd: MccsDeviceProxy,
    configuration_param: str,
    value: str,
    type_cast: str,
) -> None:
    """
    Pass a string representation of a dictionary to MccsDaqReceiver.

    :param daq_receiver_bdd: The daq_receiver fixture to use.
    :param configuration_param: The parameter of interest
    :param value: The value of that parameter
    :param type_cast: type to cast

    Some nasty string hacking going on here. This can probably be done in a neater
    way using the pytest_bdd.parsers
    """
    # could not find a way to pass in "" so i have passed "None" and converted it here.
    if value == "None":
        value = ""

    # create a string representation of a dictionary (nasty hack)
    if type_cast == "int":
        configuration = f'{{"{configuration_param}":{int(value)}}}'
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
def check_response_as_expected(
    daq_receiver_bdd: MccsDeviceProxy, configuration_param: str, value: str
) -> None:
    """
    Specific parameters passed to the daq_receiver_interface are overridden.

    :param daq_receiver_bdd: The daq_receiver fixture to use.
    :param configuration_param: The parameter of interest
    :param value: The value of that parameter

    This overriding is a method internal to the daq_receiver_interface.
    This can occur for:
    -receiver_ports if it is not a list
    The ports should be converted to a list of integers (in accordance to daq_receiver_interface)
    -receiver_ip if its value is ''
    The ip if assigned a value which depends on the value of the 'receiver_interface',
    here we are not testing the internal functionality of _get_ip_address()
    only testing that the value has changed (i.e proving that it has been overridden!)
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
        assert False
