#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""
Test the PCAP Replayer Utility.

This module provides tests for replaying PCAP files.

"""

import os
import time
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from scapy.layers.inet import IP, UDP
from scapy.plist import PacketList
from scapy.sendrecv import AsyncSniffer
from scapy.utils import rdpcap

from ska_low_mccs_daq.pydaq.utils.pcap_replayer import PCAPReplayer

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
    pcap_filename: str, ip_address: str, port: int
) -> PCAPReplayer:
    """
    Get the PCAPReplayer object.

    :param pcap_filename: The PCAP filename.
    :param ip_address: The IP address.
    :param port: The destination port.

    :returns: The PCAPReplayer object.

    """
    return PCAPReplayer(pcap_filename, ip_address, port, delay=1e-4)


def test_pcap_replayer(pcap_replayer: PCAPReplayer) -> None:
    """
    Test the PCAPReplayer.

    :param pcap_replayer: The PCAP Replayer object.

    """
    # Get some attributes from the pcap_replayer
    pcap_filename = pcap_replayer._filename
    ip_address = pcap_replayer._host
    port = pcap_replayer._port
    cached_pcap_filename = pcap_replayer._cached_filename

    # Read the packets
    packets = rdpcap(cached_pcap_filename)

    # Get the expected number of packets for both files
    num_packets = len(rdpcap(pcap_filename))
    num_packets_cached = len(packets)

    # Ensure number of packets is the same in cached file
    assert num_packets == num_packets_cached

    # Handle the packets as they arrive. Count them and check the destination
    # IP and MAC address are the ones we expect.
    class PacketHandler:
        """Count and handle the packets."""

        def __init__(self) -> None:
            """Initialse the counter."""
            # Start sniffing at the network traffic. When sniffing is started
            # set the event to trigger the replay. Filter the packets by the
            # destination IP and port to ensure we only get the packets we
            # are interested in (since we're using loopback now).
            self.num_packets = 0
            self.ready = Event()
            self.sniffer = AsyncSniffer(
                iface="lo",
                started_callback=self.ready.set,
                prn=self.handle_packet,
                lfilter=lambda packet: (
                    packet.haslayer(UDP)
                    and packet[UDP].dport == port
                    and packet[IP].dst == ip_address
                ),
            )
            self.sniffer.start()

        def handle_packet(self, packet: Any) -> None:
            """
            Handle the sniffed packets.

            :param packet: The packet to handle

            """
            self.num_packets += 1

        def stop(self) -> PacketList | None:
            """
            Stop the sniffing.

            :returns: The captured packets.

            """
            # Wait for 5 seconds and check for number of packets. This is to ensure
            # that we give enough time to wait for the expected number of packets
            # before stopping sniffing
            start_time = time.time()
            while time.time() - start_time < 2 * 60:
                if packet_handler.num_packets >= num_packets:
                    break
                time.sleep(0.1)

            # Now stop sniffing
            return self.sniffer.stop()

        def wait(self) -> None:
            """Wait until the packet handler has started."""
            # Wait until sniffing has started
            assert self.ready.wait(timeout=2 * 60)

            # Then just wait for a second for good measure
            time.sleep(1)

    # Get the packet handler object
    packet_handler = PacketHandler()

    # Wait until the packet handler is ready
    packet_handler.wait()

    # Replay the PCAP file in a new thread.
    pcap_replayer()

    # Get the captured packets
    captured = packet_handler.stop()

    # Check we get some captured packets
    assert captured is not None

    # Compare each packet
    for a, b in zip(packets, captured):
        assert a[IP].dst == b[IP].dst
        assert a[IP].proto == b[IP].proto

    # Check the number of packets. Since we use UDP which is inherently
    # unreliable we accept some packet loss (10%) in this test.
    assert len(captured) >= 0.9 * num_packets
