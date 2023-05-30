# -*- coding: utf-8 -*-
# pylint: skip-file
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains pytest-specific test harness for MCCS unit tests."""
# from __future__ import annotations

# from functools import lru_cache
# from typing import Any, Callable, ContextManager, Generator

# import pytest
# import tango
# from _pytest.fixtures import SubRequest
# from ska_tango_testing.context import (
#     TangoContextProtocol,
#     ThreadedTestTangoContextManager,
#     TrueTangoContextManager,
# )
# from ska_tango_testing.mock.tango import MockTangoEventCallbackGroup

# DeviceMappingType = dict[str, dict[str, Any]]


# def pytest_itemcollected(item: pytest.Item) -> None:
#     """
#     Modify a test after it has been collected by pytest.

#     This pytest hook implementation adds the "forked" custom mark to all
#     tests that use the ``tango_harness`` fixture, causing them to be
#     sandboxed in their own process.

#     :param item: the collected test for which this hook is called
#     """
#     if "tango_harness" in item.fixturenames:  # type: ignore[attr-defined]
#         item.add_marker("forked")


# @pytest.fixture(name="daq_id", scope="session")
# def daq_id_fixture() -> str:
#     """
#     Return the daq id of this daq receiver.

#     :return: the daq id of this daq receiver.
#     """
#     # TODO: This must match the DaqId property of the daq receiver under
#     # test. We should refactor the harness so that we can pull it
#     # straight from the device configuration.
#     return "1"


# @pytest.fixture(name="receiver_interface", scope="session")
# def receiver_interface_fixture() -> str:
#     """
#     Return the interface this daq receiver is watching.

#     :return: the interface this daq receiver is watching.
#     """
#     return "eth0"


# @pytest.fixture(name="receiver_ip", scope="session")
# def receiver_ip_fixture() -> str:
#     """
#     Return the ip of this daq receiver.

#     :return: the ip of this daq receiver.
#     """
#     return "172.17.0.230"


# @pytest.fixture(name="acquisition_duration", scope="session")
# def acquisition_duration_fixture() -> int:
#     """
#     Return the duration of data capture in seconds.

#     :return: Duration of data capture.
#     """
#     return 2


# @pytest.fixture(name="receiver_ports", scope="session")
# def receiver_ports_fixture() -> str:
#     """
#     Return the port(s) this daq receiver is watching.

#     :return: the port(s) this daq receiver is watching.
#     """
#     return "4660"


# @pytest.fixture()
# def default_consumers_to_start() -> str:
#     """
#     Return an empty string.

#     :return: An empty string.
#     """
#     return ""


# @pytest.fixture()
# def max_workers() -> int:
#     """
#     Max worker threads available to run a LRC.

#     Return an integer specifying the maximum number of worker threads available to
#         execute long-running-commands.

#     :return: the max number of worker threads.
#     """
#     return 1


# @pytest.fixture(scope="session", name="testbed")
# def testbed_fixture(request: SubRequest) -> str:
#     """
#     Return the name of the testbed.

#     The testbed is specified by providing the `--testbed` argument to
#     pytest. Information about what testbeds are supported and what tests
#     can be run in each testbed is provided in `testbeds.yaml`

#     :param request: A pytest object giving access to the requesting test
#         context.

#     :return: the name of the testbed.
#     """
#     return request.config.getoption("--testbed")


# @pytest.fixture(name="daq_name", scope="session")
# def daq_name_fixture(daq_id: str) -> str:
#     """
#     Return the name of this daq receiver.

#     :param daq_id: The ID of this daq receiver.

#     :return: the name of this daq receiver.
#     """
#     return f"low-mccs-daq/daqreceiver/{daq_id.zfill(3)}"


# @pytest.fixture(name="grpc_port", scope="session")
# def grpc_port_fixture() -> str:
#     """
#     Return the port on which the gRPC server is to communicate.

#     :return: the gRPC port number.
#     """
#     return "50051"


# @pytest.fixture(name="grpc_host", scope="session")
# def grpc_host_fixture() -> str:
#     """
#     Return the host on which the gRPC server is available.

#     :return: the gRPC port number.
#     """
#     return "localhost"


# @pytest.fixture(name="tango_harness", scope="session")
# def tango_harness_fixture(
#     testbed: str,
#     daq_name: str,
#     daq_id: str,
#     receiver_interface: str,
#     receiver_ip: str,
#     receiver_ports: str,
#     grpc_port: str,
#     grpc_host: str,
# ) -> Generator[TangoContextProtocol, None, None]:
#     """
#     Return a Tango harness against which to run tests of the deployment.

#     :param testbed: the name of the testbed to which these tests are
#         deployed
#     :param daq_name: name of the DAQ receiver Tango device
#     :param daq_id: id of the DAQ receiver
#     :param receiver_interface: network interface on which the DAQ
#         receiver receives packets
#     :param receiver_ip: IP address on which the DAQ receiver receives
#         packets
#     :param receiver_ports: port on which the DAQ receiver receives
#         packets.
#     :param grpc_port: The port number to use for gRPC calls.
#     :param grpc_host: The hostname of the gRPC server to use.

#     :raises ValueError: if the testbed is unknown

#     :yields: a tango context.
#     """
#     context_manager: ContextManager[TangoContextProtocol]
#     if testbed == "local":
#         context_manager = TrueTangoContextManager()
#     elif testbed == "test":
#         context_manager = ThreadedTestTangoContextManager()
#         context_manager.add_device(
#             daq_name,
#             "ska_low_mccs_daq.MccsDaqReceiver",
#             DaqId=daq_id,
#             ReceiverInterface=receiver_interface,
#             ReceiverIp=receiver_ip,
#             ReceiverPorts=receiver_ports,
#             GrpcHost=grpc_host,
#             GrpcPort=grpc_port,
#             ConsumersToStart=["DaqModes.INTEGRATED_CHANNEL_DATA"],
#             LoggingLevelDefault=3,
#         )
#     else:
#         raise ValueError(f"Testbed {testbed} is not supported.")

#     with context_manager as context:
#         yield context


# @pytest.fixture(name="change_event_callbacks", scope="module")
# def change_event_callbacks_fixture(
#     device_mapping: DeviceMappingType,
# ) -> MockTangoEventCallbackGroup:
#     """
#     Return a dictionary of change event callbacks with asynchrony support.

#     :param device_mapping: a map from short to canonical device names

#     :returns: a callback group.
#     """
#     keys = [
#         f"{info['name']}/{attr}"
#         for info in device_mapping.values()
#         for attr in info["subscriptions"]
#     ]
#     return MockTangoEventCallbackGroup(
#         *keys,
#         timeout=30.0,  # TPM takes a long time to initialise
#     )


# @pytest.fixture(name="device_mapping", scope="module")
# def device_mapping_fixture() -> DeviceMappingType:
#     """
#     Return a mapping from short to canonical Tango device names.

#     :return: a map of short names to full Tango device names of the form
#         "<domain>/<class>/<instance>", as well as attributes to subscribe to change
#         events of
#     """
#     return {
#         "daq": {
#             "name": "low-mccs-daq/daqreceiver/001",
#             "subscriptions": [
#                 "adminMode",
#                 "state",
#                 "longRunningCommandResult",
#                 "dataReceivedResult",
#             ],
#         },
#     }


# @pytest.fixture(name="tango_context", scope="module")
# def tango_context_fixture() -> Generator[TangoContextProtocol, None, None]:
#     """
#     Yield a Tango context containing the device/s under test.

#     :yields: a Tango context containing the devices under test
#     """
#     with TrueTangoContextManager() as context:
#         yield context


# @pytest.fixture(name="get_device", scope="module")
# def get_device_fixture(
#     tango_context: TangoContextProtocol,
#     device_mapping: DeviceMappingType,
#     change_event_callbacks: MockTangoEventCallbackGroup,
# ) -> Callable[[str], tango.DeviceProxy]:
#     """
#     Return a memoized function that returns a DeviceProxy for a given name.

#     :param tango_context: a TangoContextProtocol to instantiate DeviceProxys
#     :param device_mapping: a map from short to canonical device names
#     :param change_event_callbacks: dictionary of mock change event
#         callbacks with asynchrony support

#     :return: a memoized function that takes a name and returns a DeviceProxy
#     """

#     @lru_cache
#     def _get_device(short_name: str) -> tango.DeviceProxy:
#         device_data = device_mapping[short_name]
#         name: str = device_data["name"]
#         tango_device = tango_context.get_device(name)
#         device_info = tango_device.info()
#         dev_class = device_info.dev_class
#         print(f"Created DeviceProxy for {short_name} - {dev_class} {name}")
#         for attr in device_data.get("subscriptions", []):
#             attr_value = tango_device.read_attribute(attr).value
#             attr_event = change_event_callbacks[f"{name}/{attr}"]
#             tango_device.subscribe_event(
#                 attr,
#                 tango.EventType.CHANGE_EVENT,
#                 attr_event,
#             )
#             print(f"Subscribed to {name}/{attr}")
#             attr_event.assert_change_event(attr_value)
#             print(f"Received initial value for {name}/{attr}: {attr_value}")

#         return tango_device

#     return _get_device
