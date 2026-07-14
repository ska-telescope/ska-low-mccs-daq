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
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import pytest
import pytest_mock
from getmac import get_mac_address  # type: ignore
from scapy.layers.inet import IP, Ether
from scapy.sendrecv import sniff
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
    return "lo"


@pytest.fixture(name="ip_address")
def ip_address_fixture() -> str:
    """
    Get the destination IP address.

    :returns: The destination ip address.

    """
    return "127.0.0.1"


@pytest.fixture(name="mock_mac_address")
def mock_mac_address_fixture(mocker: pytest_mock.MockerFixture, interface: str) -> str:
    """
    Get the destination mac address.

    :param mocker: The pytest mocker.
    :param interface: The network interface.

    :returns: The mac address.

    """
    # Get the mac address
    mac_address = get_mac_address(interface=interface) or "00:00:00:00:00:00"

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
    interface = pcap_replayer._interface
    ip_address = pcap_replayer._ip_address
    mac_address = pcap_replayer._mac_address

    # Get the expected number of packets
    num_packets = len(rdpcap(pcap_filename))

    # Handle the packets as they arrive. Count them and check the destination
    # IP and MAC address are the ones we expect.
    class PacketHandler:
        """Count and handle the packets."""

        def __init__(self) -> None:
            """Initialse the counter."""
            self.num_packets = 0
            self.ready = Event()

        def __call__(self) -> None:
            """Start sniffing for packets."""
            # Start sniffing at the network traffic. When sniffing is started
            # set the event to trigger the replay. When the number of packets
            # received is as expected then exit the sniffer. Also timeout after
            # 2 minutes if we don't receive the expected packets.
            sniff(
                iface=interface,
                started_callback=self.ready.set,
                prn=self.handle_packet,
                stop_filter=lambda p: self.num_packets == num_packets,
                store=0,
                timeout=2 * 60,
            )

        def handle_packet(self, packet: Any) -> None:
            """
            Check the packets.

            :param packet: The packet.

            """
            if IP in packet:
                assert packet[IP].dst == ip_address
            if Ether in packet:
                assert packet[Ether].dst == mac_address
            self.num_packets += 1

        def wait(self) -> None:
            """Wait until the packet handler has started."""
            self.ready.wait()

    # Get the packet handler object
    packet_handler = PacketHandler()

    # Create a thread pool executor in which to run the PCAP replayer
    with ThreadPoolExecutor(max_workers=2) as executor:

        # Start sniffing at the network traffic
        executor.submit(packet_handler)

        # Wait until the packet handler is ready
        packet_handler.wait()

        # Replay the PCAP file in a new thread.
        executor.submit(pcap_replayer)

    # Check the number of packets
    assert num_packets == packet_handler.num_packets
