#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq pcap bandpass."""

import json
import os.path
import time
from typing import Generator

import pytest
import tango
from pytest_bdd import given, scenario, then, when

from ..test_tools import assert_against_lrc_finished, wait_for_condition
from ..utils.pcap_replayer import PCAPReplayer

PCAP_NAME = "channel_integ_96_192.pcap"

# In CI the PCAP is injected into the job pod from the BAR "runner-artefacts"
# repository, via the KUBERNETES_POD_ANNOTATIONS_* variables on the
# python-test job in .gitlab-ci.yml. The injector unpacks the artefact's
# assets into this directory.
INJECTED_PCAP_DIR = "/mnt/artefact"

# Local runs use a copy of the PCAP that the developer has fetched from BAR.
LOCAL_PCAP_DIR = "tests/data/pcap-data"


@pytest.fixture(name="bandpass_test_pcap_filename")
def bandpass_test_pcap_filename_fixture() -> str | None:
    """
    Get the bandpass test pcap filename.

    :returns: The filename.

    """
    for directory in (INJECTED_PCAP_DIR, LOCAL_PCAP_DIR):
        pcap_path = os.path.join(directory, PCAP_NAME)
        if os.path.exists(pcap_path):
            return pcap_path
    return None


@pytest.fixture(name="ip_address")
def ip_address_fixture() -> str:
    """
    Get the destination IP address.

    :returns: The destination ip address.

    """
    return "127.0.0.1"


@pytest.fixture(name="port")
def port_fixture() -> int:
    """
    Get the destination port.

    :returns: The destination port.

    """
    return 4660


@pytest.fixture(name="pcap_replayer")
def pcap_replayer_fixture(
    bandpass_test_pcap_filename: str,
    ip_address: str,
    port: int,
) -> PCAPReplayer:
    """
    Get the PCAPReplayer object.

    :param bandpass_test_pcap_filename: The PCAP filename.
    :param ip_address: The IP address.
    :param port: The port.

    :returns: The PCAPReplayer object.

    """
    return PCAPReplayer(bandpass_test_pcap_filename, ip_address, port, delay=1e-3)


@given("the bandpass test PCAP file is available")
def check_bandpass_test_pcap_file_is_available(
    bandpass_test_pcap_filename: str,
) -> None:
    """
    Check that the bandpass test pcap file is available.

    :param bandpass_test_pcap_filename: The filename.

    """
    if bandpass_test_pcap_filename is None or not os.path.exists(
        bandpass_test_pcap_filename
    ):
        pytest.skip("Test requires PCAP files from BAR")


@given("the DAQ ParentConnectionTimeout is disabled")
def disable_daq_parent_connection_timeout(
    daq_receiver: tango.DeviceProxy,
) -> Generator:
    """
    Disable the DAQ parent connection timeout.

    We do this because if the parent connection timesout then the device will
    go into an alarm state and when running the tests the parent device
    SpsStation may not be available.

    :param daq_receiver: The daq receiver device proxy

    :yields: Control

    """
    # Get the admin device
    admin_device = tango.DeviceProxy(daq_receiver.adm_name())

    # Get current attribute configuration
    attr_config = daq_receiver.get_attribute_config("parentConnectionFailed")

    # Get the initial value
    max_alarm = attr_config.max_alarm

    try:

        # Update max_alarm
        attr_config.max_alarm = "2"

        # Write back the configuration
        daq_receiver.set_attribute_config(attr_config)

        # Restart the server
        admin_device.RestartServer()

        # Wait for the device to be available
        wait_for_condition(lambda: (daq_receiver.ping(), True)[1])

        yield

    finally:

        # Frequently get "Failed to connect to device... The last connection
        # request was done less than 1000 ms ago". Therefore add a sleep for
        # 1000 ms to ensure this doesn't happen
        time.sleep(1)

        # Get current attribute configuration
        attr_config = daq_receiver.get_attribute_config("parentConnectionFailed")

        # Reset the max_alarm
        attr_config.max_alarm = max_alarm

        # Write back the configuration
        daq_receiver.set_attribute_config(attr_config)

        # Restart the server
        admin_device.RestartServer()

        # Wait for the device to be available
        wait_for_condition(lambda: (daq_receiver.ping(), True)[1])


@given("the DAQ NumberOfTiles is set to 8")
def set_daq_number_of_tiles_to_8(
    daq_receiver_device: tango.DeviceProxy,
) -> None:
    """
    Set the number of tiles to 8 in the DAQ receiver.

    :param daq_receiver_device: The DAQ receiver device.

    """
    daq_receiver_device.put_property({"NumberOfTiles": 8})


@given("the DAQ has been restarted")
def restart_the_daq_device(daq_receiver: tango.DeviceProxy) -> None:
    """
    Restart the DAQ receiver device.

    :param daq_receiver: The DAQ receiver device.

    """
    # Get the admin device
    admin_device = tango.DeviceProxy(daq_receiver.adm_name())

    # Restart the server
    admin_device.RestartServer()

    # Wait for the device to be available
    wait_for_condition(lambda: (daq_receiver.ping(), True)[1])


@given("the DAQ is configured to receive channelised data")
def check_daq_is_configured_to_receive_channelised_data(
    daq_receiver_device: tango.DeviceProxy,
) -> Generator:
    """
    Check that the DAQ is configured to receive channelised data.

    :param daq_receiver_device: The daq device proxy

    :yields: Control

    """
    # Start, Yield, Stop. Do this inside a try / finally block to ensure that
    # if something goes wrong we still stop the DAQ receiver
    try:

        # If there are any running consumers then stop befoe doing anything else
        if len(daq_receiver_device.runningConsumers) > 0:
            _, [command_id] = daq_receiver_device.Stop()
            assert_against_lrc_finished(
                daq_receiver_device, command_id, "COMPLETED", 60
            )

        # Start the DAQ receiver to receive channelised data
        _, [command_id] = daq_receiver_device.Start(
            json.dumps({"modes_to_start": "INTEGRATED_CHANNEL_DATA"})
        )
        assert_against_lrc_finished(daq_receiver_device, command_id, "COMPLETED", 60)

        # Yield control
        yield

    finally:

        # Once we get back control stop the DAQ receiver
        _, [command_id] = daq_receiver_device.Stop()
        assert_against_lrc_finished(daq_receiver_device, command_id, "COMPLETED", 60)

        # Check we have no more running consumers
        assert len(daq_receiver_device.runningConsumers) == 0


@when("we replay the bandpass PCAP file to the DAQ")
def replay_the_bandpass_pcap_file_to_the_daq(pcap_replayer: PCAPReplayer) -> None:
    """
    Start the PCAP replay.

    :param pcap_replayer: The PCAP replayer

    """
    pcap_replayer()


@then("the DAQ should receive the bandpass data")
def check_daq_received_the_bandpass_data(
    daq_receiver_device: tango.DeviceProxy,
) -> None:
    """
    Check the DAQ received the data.

    :param daq_receiver_device: The DAQ receiver device.

    """


@scenario(
    "features/daq_pcap_bandpass.feature",
    "Validate bandpass test using PCAP replay",
)
def test_validate_bandpass_using_pcap_replay() -> None:
    """Validate the bandpass using PCAP replay."""
