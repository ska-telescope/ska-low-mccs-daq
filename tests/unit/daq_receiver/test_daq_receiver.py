"""Test the DaqReceiver class."""
import logging
import os
import socket
import struct
import tempfile
import time
from pathlib import Path
from threading import Event
from typing import Any

import h5py
import numpy as np
import pytest

from ska_low_mccs_daq.pydaq.daq_receiver import get_conf
from ska_low_mccs_daq.pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from tests.utils.pcap_replayer import PCAPReplayer

PCAP_NAME = "channel_integ_96_192.pcap"

# In CI the PCAP is injected into the job pod from the BAR "runner-artefacts"
# repository, via the KUBERNETES_POD_ANNOTATIONS_* variables on the
# python-test job in .gitlab-ci.yml. The injector unpacks the artefact's
# assets into this directory.
INJECTED_PCAP_DIR = Path("/mnt/artefact")

# Local runs use a copy of the PCAP that the developer has fetched from BAR.
LOCAL_PCAP_DIR = Path("tests/data/pcap-data")


def _find_pcap_file() -> Path | None:
    """
    Find the PCAP file, preferring the copy injected by the runner.

    :returns: The path to the PCAP file, or None if it was not found.

    """
    for directory in (INJECTED_PCAP_DIR, LOCAL_PCAP_DIR):
        pcap_path = directory / PCAP_NAME
        if pcap_path.is_file():
            return pcap_path
    return None


@pytest.fixture(name="pcap_filename")
def pcap_filename_fixture() -> str:
    """
    Get the PCAP filename.

    :returns: The PCAP filename

    """
    pcap_path = _find_pcap_file()

    if pcap_path is None:
        searched = ", ".join(
            str(directory / PCAP_NAME)
            for directory in (INJECTED_PCAP_DIR, LOCAL_PCAP_DIR)
        )
        message = (
            f"PCAP test data not found. Searched: {searched}. "
            f"Download {PCAP_NAME} from the BAR runner-artefacts repository "
            "and place it in tests/data/pcap-data."
        )
        # Under CI the PCAP should have been injected into the pod, so a
        # missing file means injection is broken.
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)

    return str(pcap_path)


# pylint: disable=too-many-arguments, too-many-locals
def create_spead_packet(
    timestamp: int = 0,
    start_channel: int = 0,
    start_antenna: int = 0,
    tpm_id: int = 0,
    station_id: int = 0,
    unix_epoch_time: int = 0,
) -> bytes:
    """
    Create a SPEAD packet for integrated channel data.

    Based on the format used in ska-low-mccs-spshw's SpeadDataSimulator.

    :param timestamp: Timestamp value
    :param start_channel: Start channel ID
    :param start_antenna: Start antenna ID
    :param tpm_id: TPM (tile) ID
    :param station_id: Station ID
    :param unix_epoch_time: Unix epoch time for sync_time (defaults to current time)
    :return: Raw packet bytes

    """
    # LMC capture mode: 0x6 = integrated channel data
    lmc_capture_mode = 0x6

    # Number of antennas per packet (from  default)
    nof_ants_per_packet = 1

    # Packet payload length (from simulator default)
    packet_payload_length = 1024

    # SPEAD header:
    #   magic(8) |
    #   version(8) |
    #   item_ptr_bits(8) |
    #   heap_addr_bits(8) |
    #   nitems(32)
    # Using SPEAD version 4, 32-bit item pointers, 48-bit heap addresses, 8 items
    # Matching the format from spead_data_simulator.py
    header = 0x53 << 56 | 0x04 << 48 | 0x02 << 40 | 0x06 << 32 | 0x08

    # Heap counter: present(1) | id(16) | timestamp(48)
    # Note: The simulator uses timestamp here, not a separate packet counter
    heap_counter = 1 << 63 | 0x0001 << 48 | timestamp

    # Payload length: present(1) | id(16) | length(48)
    pkt_len = 1 << 63 | 0x0004 << 48 | packet_payload_length

    # Sync time: present(1) | id(16) | sync_time(48)
    sync_time = 1 << 63 | 0x1027 << 48 | unix_epoch_time

    # Timestamp: present(1) | id(16) | timestamp(48)
    spead_timestamp = 1 << 63 | 0x1600 << 48 | (timestamp & 0xFFFFFFFFFF)

    # LMC capture mode: present(1) | id(16) | mode(48)
    lmc_capture_mode_item = 1 << 63 | 0x2004 << 48 | lmc_capture_mode

    # LMC info:
    #   present(1) |
    #   id(16) |
    #   start_channel(24) |
    #   start_antenna(8) |
    #   nof_antennas(8)
    # For integrated channel data, nof_included_channels is not included here
    # because IntegratedChannelisedData recalculates it from payload_length
    # Matching the format from spead_data_simulator.py
    lmc_info = (
        1 << 63
        | 0x2002 << 48
        | start_channel << 24
        | start_antenna << 8
        | nof_ants_per_packet
    )

    # LMC TPM info: present(1) | id(16) | tpm_id(16) | station_id(16)
    lmc_tpm_info = 1 << 63 | 0x2001 << 48 | tpm_id << 32 | station_id << 16

    # Sample offset: present(0) | id(16) | offset(48)
    sample_offset = 0 << 63 | 0x3300 << 48

    # Build the packet with 9 uint64 values (header + 8 items)
    # Matching the format from spead_data_simulator
    packet = struct.pack(
        ">" + "Q" * 9,
        header,
        heap_counter,
        pkt_len,
        sync_time,
        spead_timestamp,
        lmc_capture_mode_item,
        lmc_info,
        lmc_tpm_info,
        sample_offset,
    )

    return packet


def send_test_packets_simulated(host: str = "127.0.0.1", port: int = 4660) -> tuple:
    """Send test SPEAD packets using manual packet creation.

    For integrated channel data, the DAQ expects a complete set of packets:
    - 16 antennas * 2 channel packets (0-255, 256-511) = 32 packets total

    :param host: Destination host
    :param port: Destination port

    :returns: Number of packets successfully sent, expected payload

    """
    # Produce some output to aid debugging
    logger = logging.getLogger(__name__)

    # Create a socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # The expected non zero channels
    expected_non_zero_channels = [0, 96, 160, 192, 224, 288, 352, 480]

    # Generate some random values
    payloads = np.zeros(shape=(512, 16, 2), dtype=np.uint16)
    payloads[expected_non_zero_channels, :, :] = np.random.randint(
        0, 65535, size=(len(expected_non_zero_channels), 16, 2), dtype=np.uint16
    )
    payloads = payloads.reshape((2, 256, 16, 2))

    # Get the current unix time to use as a timestamp
    unix_epoch_time = int(time.time())

    # Send packets for all 16 antennas with 2 channel ranges each
    # This matches the DAQ's expectation of a complete integration
    # All packets in the same integration should have the same timestamp
    num_antennas = 16
    num_channel_ranges = 2
    total_packets = num_antennas * num_channel_ranges
    packets_sent = 0
    logger.info(f"Sending {total_packets} test SPEAD packets to {host}:{port}")
    for antenna in range(num_antennas):
        for channel_range in range(num_channel_ranges):
            start_channel = channel_range * 256
            try:
                # Create packet matching receiver format
                # Use the same timestamp for all packets in this integration
                packet = create_spead_packet(
                    timestamp=0,
                    start_channel=start_channel,
                    start_antenna=antenna,
                    tpm_id=0,
                    station_id=0,
                    unix_epoch_time=unix_epoch_time,
                )

                # Add payload (simulated integrated channel data)
                # For 1 antenna, 256 channels, 2 pols = 512 values
                packet += payloads[channel_range, :, antenna, :].flatten().tobytes()
                sock.sendto(packet, (host, port))
                packets_sent += 1

                # Produce some info about the packets sent
                logger.info(
                    f"  Sent packet {packets_sent}/{total_packets}"
                    f" (antenna={antenna}, channel={start_channel}-{start_channel+255})"
                    f" ({len(packet)} bytes)"
                )

            except Exception:  # pylint: disable=broad-exception-caught

                logger.exception(
                    f"  Error sending packet for antenna {antenna},"
                    f" channel {start_channel}"
                )

            # Small delay between packets
            time.sleep(0.01)

    # Close the socket
    sock.close()
    logger.info(f"Finished sending packets. Total sent: {packets_sent}/{total_packets}")

    # Ensure all packets were sent
    assert packets_sent == total_packets

    # Return the packets sent and expected payloads
    return (
        packets_sent,  # packets_sent
        1,  # num_tiles
        1,  # num_files
        packets_sent,  # num_packets_per_file
        expected_non_zero_channels,
    )


def send_test_packets_pcap_file(host: str = "127.0.0.1", port: int = 4660) -> tuple:
    """Send test SPEAD packets using manual packet creation.

    For integrated channel data, the DAQ expects a complete set of packets:
    - 16 antennas * 2 channel packets (0-255, 256-511) = 32 packets total

    :param host: Destination host
    :param port: Destination port

    :returns: Number of packets successfully sent, expected payload

    """
    pcap_filename = str(LOCAL_PCAP_DIR / PCAP_NAME)
    pcap_replayer = PCAPReplayer(pcap_filename, host, port, delay=1e-4)
    pcap_replayer()
    return (
        1024,  # packets_sent
        8,  # num_tiles
        32,  # num_files
        32,  # num_packets_per_file
        [0, 96, 160, 192, 224, 288, 352, 480],  # expected_non_zero_channels
    )


def send_test_packets(source: str, host: str = "127.0.0.1", port: int = 4660) -> tuple:
    """Send test SPEAD packets using manual packet creation.

    For integrated channel data, the DAQ expects a complete set of packets:
    - 16 antennas * 2 channel packets (0-255, 256-511) = 32 packets total

    :param source: The source of the packets
    :param host: Destination host
    :param port: Destination port

    :returns: Number of packets successfully sent, expected payload

    """
    match source:
        case "simulated":
            return send_test_packets_simulated(host, port)
        case "pcap_file":
            return send_test_packets_pcap_file(host, port)
        case _:
            assert False, f"Unknown source {source}"


def launch_daq_receiver(nof_tiles: int, expected_num_files: int) -> tuple:
    """
    Launch a DAQ receiver.

    :param nof_tiles: The number of tiles
    :param expected_num_files: The expected number of files to wait for

    :returns: The daq receiver, temp directory and received packets

    """
    # The callback will append packets to this list
    received_packets = []
    received_event = Event()

    def packet_received_callback(*args: list, **kwargs: dict) -> None:

        # Ensure the packet contains mode, filename and tile
        assert len(args) == 3
        packet_data: dict[Any, Any] = {
            "mode": args[0],
            "filename": args[1],
            "tile": args[2],
        }

        # Add the kwargs (which include nof_packets)
        packet_data.update(kwargs)
        received_packets.append(packet_data)
        logger.info(f"  Packet received! Total: {len(received_packets)}")

        # Set the received event so we exit the test
        if len(received_packets) == expected_num_files:
            received_event.set()

    logger = logging.getLogger(__name__)

    # Print some information
    logger.info("Launching DAQ receiver...")

    # Create a temporary directory for DAQ output
    temp_dir = tempfile.mkdtemp(prefix="daq_test_")

    # Get default configuration
    config = get_conf()

    # It seems that get_conf() produces a configuration with invalid keys.
    # Therefore, we need to remove tsamp, should this be sampling_time?
    config.pop("tsamp", None)

    # Update configuration for local testing
    config.update(
        {
            "receiver_ip": "127.0.0.1",
            "receiver_ports": [4660],  # Must be a list of integers, not a string
            "receiver_interface": "lo",  # Loopback interface
            "write_to_disk": True,  # Must be True for callbacks to work
            "logging": True,
            "directory": temp_dir,  # Use temporary directory
            "append_integrated": False,  # Create new files for each packet
            "nof_antennas": 16,  # Match receiver default (2 FPGAs * 8 antennas each)
            "nof_channels": 512,  # Match receiver default
            "nof_polarisations": 2,  # Match receiver default
            "station_id": 0,  # Match receiver default
            "nof_tiles": nof_tiles,
            "integration_lookahead_cutoff": 3.0,  # For IntegratedChannelisedData
        }
    )

    # Create DAQ receiver
    daq = DaqReceiver()

    # Apply configuration
    daq.populate_configuration(config)

    # Initialize DAQ
    daq.initialise_daq()

    # Start DAQ in integrated channel mode with callback
    # Note: bandpass_mode=False for normal integrated channel data
    logger.info("Starting DAQ with callback...")
    daq.start_daq(
        DaqModes.INTEGRATED_CHANNEL_DATA,
        callbacks=packet_received_callback,
        bandpass_mode=False,
    )

    # Verify callback is registered
    assert (
        daq._external_callbacks[DaqModes.INTEGRATED_CHANNEL_DATA] is not None
    ), "DAQ callback is not registered"

    # Verify the consumer is running
    assert daq._running_consumers.get(DaqModes.INTEGRATED_CHANNEL_DATA, False)

    # Print some info
    logger.info("DAQ receiver started.")
    logger.info(f"Listening on {config['receiver_ip']}:{config['receiver_ports'][0]}")
    logger.info(f"Output directory: {temp_dir}")

    # Return the daq and temp dir
    return daq, temp_dir, received_packets, received_event


# @pytest.mark.parametrize("source", ["pcap_file"])
@pytest.mark.parametrize("source", ["simulated", "pcap_file"])
def test_daq_receiver(source: str) -> None:
    """
    Test the DAQ receiver.

    :param source: The source of packets

    """
    # Configure some logging to aid debugging
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    match source:
        case "simulated":
            expected_num_files = 1
            num_tiles = 1
        case "pcap_file":
            expected_num_files = 32
            num_tiles = 8
        case _:
            assert False, f"Expected simulated or pcap_file, got {source}"

    # Start DAQ Receiver
    daq, temp_dir, received_sets_of_packets, received_event = launch_daq_receiver(
        num_tiles, expected_num_files
    )

    # Give DAQ time to start. This is a bad sleep that is guaranteed to result
    # in the test being flaky but there is currently no "ready" check we can
    # perform for the daq receiver.
    time.sleep(2)

    # Send test packets
    (
        packets_sent,
        expected_num_tiles,
        expected_num_files,
        expected_packets_per_file,
        expected_non_zero_channels,
    ) = send_test_packets(source)

    # Give some time for packets to be processed
    assert received_event.wait(10)

    # Clean up
    daq.stop_daq()

    # Ensure that we have the expected number of sent packets
    expected_packets = expected_packets_per_file * expected_num_files
    assert (
        packets_sent == expected_packets
    ), f"Expected {expected_packets} sent packets, got {packets_sent}"

    # Ensure that we have the expected number of output files
    assert len(received_sets_of_packets) == expected_num_files, (
        f"Expected {expected_num_files} sets of packets recieved via callback, "
        f"got {len(received_sets_of_packets)}"
    )

    # Ensure we have the correct values in the received packets
    assert all(
        p["nof_packets"] == expected_packets_per_file for p in received_sets_of_packets
    )
    assert all(p["mode"] == "integrated_channel" for p in received_sets_of_packets)
    assert {p["tile"] for p in received_sets_of_packets} == set(
        range(expected_num_tiles)
    )

    # Ensure the directory exists
    assert os.path.exists(temp_dir), f"Directory {temp_dir} does not exist"
    files_created = os.listdir(temp_dir)

    # Ensure that the set of found files is the same as expected
    assert {p["filename"] for p in received_sets_of_packets} == {
        os.path.join(temp_dir, f) for f in files_created
    }

    # Create an array with the expected channels containing non zero elements
    expected_non_zero_data = np.zeros((512, 16, 2), dtype=bool)
    expected_non_zero_data[expected_non_zero_channels, :, :] = True

    # Loop through the files
    for filename in (p["filename"] for p in received_sets_of_packets):

        # Read the channel data
        handle = h5py.File(filename)
        observed_data = handle["chan_"]["data"][:].reshape(512, 16, 2)

        # Check the channels which we expect to be non zero or zero
        assert np.all(
            (observed_data != 0) == expected_non_zero_data
        ), f"File {filename} does not match expected pattern of zeros/non-zeros"
