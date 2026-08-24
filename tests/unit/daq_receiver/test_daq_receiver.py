"""Test the DaqReceiver class."""
import logging
import os
import socket
import struct
import tempfile
import time
from typing import Any

import h5py
import numpy as np

from ska_low_mccs_daq.pydaq.daq_receiver import get_conf
from ska_low_mccs_daq.pydaq.daq_receiver_interface import DaqModes, DaqReceiver


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


def send_test_packets(host: str = "127.0.0.1", port: int = 4660) -> tuple:
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

    # Generate some random values
    payloads = np.random.randint(0, 65535, size=(2, 256, 16, 2), dtype=np.uint16)

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
                # For 1 antenna, 256 channels, 2 pols = 1*256*2 = 512 values,
                # 16-bit each = 1024 bytes
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

    # Return the packets sent and expected payloads
    return packets_sent, payloads


def launch_daq_receiver() -> tuple:
    """
    Launch a DAQ receiver.

    :returns: The daq receiver, temp directory and received packets

    """
    # The callback will append packets to this list
    received_packets = []

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
            "nof_tiles": 1,  # Match receiver default
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

    # Print some info
    logger.info("DAQ receiver started.")
    logger.info(f"Listening on {config['receiver_ip']}:{config['receiver_ports'][0]}")
    logger.info(f"Output directory: {temp_dir}")

    # Return the daq and temp dir
    return daq, temp_dir, received_packets


def test_daq_receiver() -> None:
    """Test the DAQ receiver."""
    # Configure some logging to aid debugging
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    # Start DAQ Receiver
    daq, temp_dir, received_packets = launch_daq_receiver()

    # Give DAQ time to start
    time.sleep(2)

    # Send test packets
    packets_sent, expected_channel_data = send_test_packets()

    # Give some time for packets to be processed
    time.sleep(2)

    # Clean up
    daq.stop_daq()

    # Ensure that we have 32 sent packets
    assert packets_sent == 32, f"Expected 32 sent packets, got {packets_sent}"
    assert (
        len(received_packets) == 1
    ), f"Expected 1 set of packets recieved via callback, got {(received_packets)}"
    assert received_packets[0]["nof_packets"] == 32
    assert received_packets[0]["mode"] == "integrated_channel"
    assert received_packets[0]["tile"] == 0

    # Get the filename
    filename = received_packets[0]["filename"]

    # Check if any files were created in the output directory
    assert os.path.exists(temp_dir), f"Directory {temp_dir} does not exist"
    files_created = os.listdir(temp_dir)
    assert len(files_created) == 1, f"Expected 1 file created, got {files_created}"
    assert filename == os.path.join(temp_dir, files_created[0])

    # Get the filename and read the channel data
    handle = h5py.File(filename)
    observed_channel_data = handle["chan_"]["data"][:].flatten().tolist()

    # Ensure that the data is in the expected order
    expected_channel_data = expected_channel_data.flatten().tolist()
    assert len(observed_channel_data) == len(expected_channel_data)
    assert all(a == b for a, b in zip(observed_channel_data, expected_channel_data))
