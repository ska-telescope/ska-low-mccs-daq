# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq configuration."""
# from __future__ import annotations

# import json
# import socket

# import pytest
# import tango
# from pytest_bdd import given, parsers, scenarios, then, when
# from ska_tango_testing.context import TangoContextProtocol

# EXTRA_TYPES = {
#     "Dict": str,
# }

# scenarios("./features/daq_configuration.feature")


# @given("A MccsDaqReceiver is available", target_fixture="daq_receiver")
# def daq_receiver_fixture(
#     tango_harness: TangoContextProtocol,
#     daq_name: str,
# ) -> tango.DeviceProxy:
#     """
#     Return the daq_receiver device.

#     :param tango_harness: a test harness for tango devices
#     :param daq_name: name of the DAQ receiver Tango device

#     :return: the daq_receiver device
#     """
#     return tango_harness.get_device(daq_name)


# @when(
#     parsers.cfparse(
#         "We pass a {configuration:Dict} to the MccsDaqReceiver", extra_types=EXTRA_TYPES
#     )
# )
# def feed_daq_configuration_file(
#     daq_receiver: tango.DeviceProxy, configuration: str
# ) -> None:
#     """
#     Feed the configuration into the daq_receiver.

#     :param daq_receiver: The daq_receiver fixture to use.
#     :param configuration: A string representation of a dictionary for configuration.
#     """
#     # MccsDaqReceiver expects a string as input, this will be a string representation
#     # of a dictionary.
#     daq_receiver.Configure(configuration)


# @then(
#     parsers.cfparse(
#         "The DAQ_receiver interface has a {configuration_expected:Dict}",
#         extra_types=EXTRA_TYPES,
#     )
# )
# def assert_daq_instance_is_configuration_correctly(
#     daq_receiver: tango.DeviceProxy, configuration_expected: str
# ) -> None:
#     """
#     Assert daq_instance has the same configuration that we sent to the daq_receiver.

#     :param daq_receiver: The daq_receiver fixture to use.
#     :param configuration_expected: A string representing the expected configuration

#     Notes: we may only send a subset of the configuration to the DaqInstance.
#     """
#     configuration_dict = json.loads(configuration_expected)

#     config_jstr = daq_receiver.GetConfiguration()
#     retrieved_daq_config = json.loads(config_jstr)

#     assert configuration_dict.items() <= retrieved_daq_config.items()


# @when(
#     parsers.cfparse(
#         (
#             "We pass parameter {configuration_param:w} of value {value:w} "
#             "to the MccsDaqReceiver"
#         ),
#         extra_types=EXTRA_TYPES,
#     )
# )
# def pass_key_value_to_daq(
#     daq_receiver: tango.DeviceProxy, configuration_param: str, value: str
# ) -> None:
#     """
#     Pass a string representation of a dictionary to MccsDaqReceiver.

#     :param daq_receiver: The daq_receiver fixture to use.
#     :param configuration_param: The parameter of interest
#     :param value: The value of that parameter
#     """
#     # could not find a way to pass in "" so i have passed "None" and converted it here.
#     if value == "None":
#         value = ""

#     configuration = f'{{"{configuration_param}":{value}}}'

#     # configure DAQ using the string representation of a dictionary
#     daq_receiver.Configure(configuration)


# @then(
#     parsers.cfparse(
#         "The DAQ receiver interface has a valid {receiver_ip:w}",
#         extra_types=EXTRA_TYPES,
#     )
# )
# def check_response_as_expected(
#     daq_receiver: tango.DeviceProxy, receiver_ip: str
# ) -> None:
#     """
#     Specific parameters passed to the daq_receiver_interface are overridden.

#     :param daq_receiver: The daq_receiver fixture to use.
#     :param receiver_ip: The parameter of interest

#     If the ip is not assigned it is assigned the IP address of a specified interface
#     'receiver_interface'. This tests that the value has changed.
#     TODO: determine what other values are allowed
#     """
#     daq_config_jstr = daq_receiver.GetConfiguration()
#     retrieved_daq_config = json.loads(daq_config_jstr)
#     receiver_port = retrieved_daq_config[receiver_ip]

#     try:
#         socket.inet_aton(receiver_port)
#     except IOError:
#         # the ip address is not valid
#         pytest.fail("Invalid IP address causes IOError")
