#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the tests of the daq pcap bandpass."""

import json
import os.path
from threading import Event
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


@pytest.fixture(name="test_context_config")
def context_generator_config_override() -> dict:
    """
    Return the test context config.

    :returns: The test context config.

    """
    return {"receiver_interface": "lo", "number_of_tiles": 8, "simulation_mode": False}


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


@pytest.fixture(name="daq_host")
def daq_host_fixture(true_context: bool, daq_receiver_device: tango.DeviceProxy) -> str:
    """
    Get the destination host.

    :param true_context: Is this a true context.
    :param daq_receiver_device: The daq device

    :returns: The destination host.

    """
    # Get the daq name
    name = daq_receiver_device.name().split("/")[2]

    # Return the host
    return (
        f"mccs-daq-daq-{name}-data.ska-low-mccs-daq.svc.cluster.local"
        if true_context
        else "127.0.0.1"
    )


@pytest.fixture(name="daq_port")
def port_fixture() -> int:
    """
    Get the destination port.

    :returns: The destination port.

    """
    return 4660


@pytest.fixture(name="pcap_replayer")
def pcap_replayer_fixture(
    bandpass_test_pcap_filename: str,
    daq_host: str,
    daq_port: int,
) -> PCAPReplayer:
    """
    Get the PCAPReplayer object.

    :param bandpass_test_pcap_filename: The PCAP filename.
    :param daq_host: The DAQ host.
    :param daq_port: The DAQ port.

    :returns: The PCAPReplayer object.

    """
    return PCAPReplayer(bandpass_test_pcap_filename, daq_host, daq_port, delay=1e-3)


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


def restart_the_daq_device(daq_receiver_device: tango.DeviceProxy) -> None:
    """
    Restart the DAQ receiver device.

    :param daq_receiver_device: The DAQ receiver device.

    """
    # Get the admin device
    admin_device = tango.DeviceProxy(daq_receiver_device.adm_name())

    # Restart the server
    admin_device.RestartServer()

    # Wait for the device to be available
    assert wait_for_condition(lambda: (daq_receiver_device.ping(), True)[1])


@given("the DAQ is configured to receive data")
def configure_the_daq(
    true_context: bool,
    daq_receiver_device: tango.DeviceProxy,
) -> Generator:
    """
    Configure the DAQ.

    We do this because if the parent connection timesout then the device will
    go into an alarm state and when running the tests the parent device
    SpsStation may not be available.

    :param true_context: Is this a true context
    :param daq_receiver_device: The daq receiver device proxy

    :yields: Control

    """
    # Only try to reset properties in a true context
    if true_context:

        # Get the current properties
        parent_trl = daq_receiver_device.ParentTRL
        number_of_tiles = daq_receiver_device.get_property("NumberOfTiles")[
            "NumberOfTiles"
        ]
        simulation_mode = daq_receiver_device.get_property("SimulationMode")[
            "SimulationMode"
        ]

        try:
            # Set ParentTRL to empty string to disable parent connection This
            # prevents the ModeInheritor from attempting to connect to a parent and
            # thus prevents parentConnectionFailed from being set to True. Also set
            # the number of tiles to 8 and turn simulation mode off.
            daq_receiver_device.put_property(
                {"ParentTRL": "", "NumberOfTiles": 8, "SimulationMode": False}
            )

            # Restart the daq device
            restart_the_daq_device(daq_receiver_device)

            # Yield control
            yield

        finally:

            # Restore the original ParentTRL value
            daq_receiver_device.put_property(
                {
                    "ParentTRL": parent_trl,
                    "NumberOfTiles": number_of_tiles,
                    "SimulationMode": simulation_mode,
                }
            )

            # Restart the daq device
            restart_the_daq_device(daq_receiver_device)

    else:

        yield


@given("the DAQ start command has been called")
def call_the_daq_start_command(
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


@given(
    "we are subscribed to changes to the received results attribute",
    target_fixture="data_received_results_subscription",
)
def subscribe_to_data_received_results(daq_receiver_device: tango.DeviceProxy) -> tuple:
    """
    Subscribe to the data received results.

    :param daq_receiver_device: The DAQ device.

    :returns: The subscription info.

    """
    # Setup the check
    expected_number_of_files = 32

    # Create an event to check
    received_results_event = Event()

    # Callback for data received events
    received_results = []

    def on_data_received(event: tango.EventData) -> None:
        result = event.attr_value.value

        # If the result is found then increment
        if result[0] == "integrated_channel":
            received_results.append(result)

        # If we have the expected number of results set the event to exit
        if len(received_results) >= expected_number_of_files:
            received_results_event.set()

    # Subscribe to changes
    subscription_id = daq_receiver_device.subscribe_event(
        "dataReceivedResult", tango.EventType.CHANGE_EVENT, on_data_received
    )

    # Return the subscription info
    return (
        subscription_id,
        received_results_event,
        received_results,
        expected_number_of_files,
    )


@when("we replay the bandpass PCAP file to the DAQ")
def replay_the_bandpass_pcap_file_to_the_daq(pcap_replayer: PCAPReplayer) -> None:
    """
    Start the PCAP replay.

    :param pcap_replayer: The PCAP replayer

    """
    pcap_replayer()


@then("the DAQ should receive the bandpass data")
def wait_for_expected_number_of_received_results(
    daq_receiver_device: tango.DeviceProxy, data_received_results_subscription: tuple
) -> None:
    """
    Wait for the DAQ to receive the data.

    :param daq_receiver_device: The DAQ receiver device
    :param data_received_results_subscription: The subscription details

    """
    # Setup the check
    timeout = 30

    # Get the subscription details
    (
        subscription_id,
        received_results_event,
        received_results,
        expected_number_of_files,
    ) = data_received_results_subscription

    # Wait for the event to be set
    assert received_results_event.wait(
        timeout
    ), f"Timed out waiting for results, got {len(received_results)}"

    # Ensure we have the correct number of results
    assert len(received_results) == expected_number_of_files

    # Unsubscribe
    daq_receiver_device.unsubscribe_event(subscription_id)


@scenario(
    "features/daq_pcap_bandpass.feature",
    "Validate bandpass test using PCAP replay",
)
def test_validate_bandpass_using_pcap_replay(global_test_lock: Generator) -> None:
    """
    Validate the bandpass using PCAP replay.

    :param global_test_lock: The global test lock

    """
