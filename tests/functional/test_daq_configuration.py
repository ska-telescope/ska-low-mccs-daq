# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq configuration."""
from __future__ import annotations

import gc
import json
from typing import Iterator

import pytest
import tango
from pytest_bdd import given, parsers, scenario, then, when
from ska_control_model import AdminMode, ResultCode
from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

from tests.harness import SpsTangoTestHarnessContext

gc.disable()

EXTRA_TYPES = {
    "Dict": str,
}


@scenario(
    "features/daq_configuration.feature",
    "Check that DAQ can be configured",
)
def test_daq_configuration() -> None:
    """
    Test DAQ configuration handling.

    Check that when a configuration is sent to the MccsDaqReceiver,
    the DAQ_receiver interface is configured correctly.

    Any code in this scenario method is run at the *end* of the
    scenario.
    """


@pytest.fixture(name="configuration")
def daq_configuration_fixture() -> str:
    """
    Provide a DAQ configuration.

    :return: A DAQ configuration
    """
    config = '{"nof_tiles": 16, "nof_antennas": 256, "description": "This is a test."}'
    return config


@given("A MccsDaqReceiver is available", target_fixture="daq_receiver")
def given_a_daq_receiver(
    functional_test_context: SpsTangoTestHarnessContext,
    change_event_callbacks: MockTangoEventCallbackGroup,
) -> Iterator[tango.DeviceProxy]:
    """
    Yield the DAQ receiver device under test.

    :param functional_test_context: the context in which the test is running.
    :param change_event_callbacks: A change event callback group.

    :yield: the DAQ receiver device
    """
    daq_receiver = functional_test_context.get_daq_device()

    daq_receiver.subscribe_event(
        "state",
        tango.EventType.CHANGE_EVENT,
        change_event_callbacks["daq_state"],
    )

    admin_mode = daq_receiver.adminMode
    if admin_mode == AdminMode.OFFLINE:
        change_event_callbacks.assert_change_event("daq_state", tango.DevState.DISABLE)

        daq_receiver.adminMode = AdminMode.ONLINE
        # For some reason the UNKNOWN change events aren't coming through...
        # change_event_callbacks.assert_change_event(
        #     "daq_state", tango.DevState.UNKNOWN
        #     )
        change_event_callbacks.assert_change_event(
            "daq_state", tango.DevState.ON, lookahead=2
        )

    yield daq_receiver


@when("We pass a configuration to the MccsDaqReceiver")
def feed_daq_configuration_file(
    daq_receiver: tango.DeviceProxy, configuration: str
) -> None:
    """
    Feed the configuration into the daq_receiver.

    :param daq_receiver: The daq_receiver fixture to use.
    :param configuration: The DAQ configuration to apply.
    """
    # MccsDaqReceiver expects a string as input, this will be a string representation
    # of a dictionary.
    assert [
        [ResultCode.OK.value],
        ["Configure command completed OK"],
    ] == daq_receiver.Configure(configuration)


@then("The DAQ_receiver interface has the expected configuration")
def assert_daq_instance_is_configured_correctly(
    daq_receiver: tango.DeviceProxy,
    configuration: str,
) -> None:
    """
    Assert daq_instance has the same configuration that we sent to the daq_receiver.

    :param daq_receiver: The daq_receiver fixture to use.
    :param configuration: The expected DAQ configuration.

    Notes: we may only send a subset of the configuration to the DaqInstance.
    """
    expected_config: dict = json.loads(configuration)
    retrieved_daq_config: dict = json.loads(daq_receiver.GetConfiguration())
    for k in expected_config.keys():
        assert retrieved_daq_config[k] == expected_config[k]


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
    daq_receiver: tango.DeviceProxy, configuration_param: str, value: str
) -> None:
    """
    Pass a string representation of a dictionary to MccsDaqReceiver.

    :param daq_receiver: The daq_receiver fixture to use.
    :param configuration_param: The parameter of interest
    :param value: The value of that parameter
    """
    pytest.xfail(reason="Not ready")
    # # could not find a way to pass in ""
    # so i have passed "None" and converted it here.
    # if value == "None":
    #     value = ""
    # configuration = json.dumps({configuration_param: value})
    # configure DAQ using the string representation of a dictionary
    # daq_receiver.Configure(configuration)


@then(
    parsers.cfparse(
        "The DAQ receiver interface has a valid {configuration_param:w}",
        extra_types=EXTRA_TYPES,
    )
)
def check_response_as_expected(
    daq_receiver: tango.DeviceProxy, configuration_param: str
) -> None:
    """
    Specific parameters passed to the daq_receiver_interface are overridden.

    :param daq_receiver: The daq_receiver fixture to use.
    :param configuration_param: The parameter of interest

    If the ip is not assigned it is assigned the IP address of a specified interface
    'receiver_interface'. This tests that the value has changed.
    TODO: determine what other values are allowed
    """
    pytest.xfail(reason="Not ready")
    # retrieved_daq_config = json.loads(daq_receiver.GetConfiguration())
    # receiver_port = retrieved_daq_config[configuration_param]

    # try:
    #     socket.inet_aton(receiver_port)
    # except IOError:
    #     # the ip address is not valid
    #     pytest.fail("Invalid IP address causes IOError")
