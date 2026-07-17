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
import time
from threading import Event
from typing import Any

import pytest
import pytest_mock
from scapy.arch import get_if_list
from scapy.layers.inet import IP, UDP, Ether
from scapy.plist import PacketList
from scapy.sendrecv import AsyncSniffer
from scapy.utils import rdpcap

from ska_low_mccs_daq.pydaq.utils.pcap_replayer import PCAPReplayer


@pytest.fixture(name="pcap_filename")
def pcap_filename_fixture() -> str:
    """
    Get the PCAP filename.

    :returns: The PCAP filename

    """
    return "tests/data/pcap-data/channel_integ_96_192.pcap"


@pytest.fixture(name="interface")
def interface_fixture() -> str:
    """
    Get the network interface.

    :returns: The network interface

    """
    # Sniffing on loopback results in 2x number of packets being detected and
    # filtering in CI seems to cause issues so let's ensure we use "eth0" or
    # whatever the physical network interface is
    for iface in get_if_list():
        if iface not in ["lo"]:
            return iface
    pytest.fail("No physical network interface found")
    return "lo"


@pytest.fixture(name="ip_address")
def ip_address_fixture() -> str:
    """
    Get the destination IP address.

    :returns: The destination ip address.

    """
    return "127.0.0.1"


@pytest.fixture(name="mock_mac_address")
def mock_mac_address_fixture(
    mocker: pytest_mock.MockerFixture, ip_address: str, interface: str
) -> str:
    """
    Get the destination mac address.

    :param mocker: The pytest mocker.
    :param ip_address: The IP address.
    :param interface: The network interface.

    :returns: The mac address.

    """
    # Use a fixed MAC address for consistent testing
    mac_address = "00:00:00:00:00:00"

    # Replace get_mac_address with a mock
    mock_get_mac_address = mocker.patch(
        "ska_low_mccs_daq.pydaq.utils.pcap_replayer.get_mac_address"
    )

    # Set the mock's return value
    mock_get_mac_address.return_value = mac_address

    # Return the mac address
    return mac_address


@pytest.fixture(name="pcap_replayer")
def pcap_replayer_fixture(
    pcap_filename: str, interface: str, ip_address: str, mock_mac_address: str
) -> PCAPReplayer:
    """
    Get the PCAPReplayer object.

    :param pcap_filename: The PCAP filename.
    :param interface: The network interface.
    :param ip_address: The IP address.
    :param mock_mac_address: The mock mac address

    :returns: The PCAPReplayer object.

    """
    return PCAPReplayer(pcap_filename, interface, ip_address)


def test_pcap_replayer(pcap_replayer: PCAPReplayer) -> None:
    """
    Test the PCAPReplayer.

    :param pcap_replayer: The PCAP Replayer object.

    """
    # Get some attributes from the pcap_replayer
    pcap_filename = pcap_replayer._filename
    cached_pcap_filename = pcap_replayer._cached_filename
    interface = pcap_replayer._interface

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
            # set the event to trigger the replay.
            self.num_packets = 0
            self.ready = Event()
            self.sniffer = AsyncSniffer(
                iface=interface,
                started_callback=self.ready.set,
                prn=self.handle_packet,
                lfilter=lambda packet: UDP in packet,
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
        assert a[Ether].dst == b[Ether].dst
        assert a[IP].dst == b[IP].dst
        assert a[IP].proto == b[IP].proto

    # Check the number of packets
    assert len(captured) == num_packets
