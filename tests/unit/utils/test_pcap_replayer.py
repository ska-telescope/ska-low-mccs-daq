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
from typing import Any, Generator

import pytest
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


@pytest.fixture(name="mac_address")
def mac_address_fixture(interface: str) -> str:
    """
    Get the destination mac address.

    :param interface: The network interface.

    :returns: The destination mac address.

    """
    return get_mac_address(interface=interface)


@pytest.fixture(name="pcap_replayer")
def pcap_replayer_fixture(
    pcap_filename: str, interface: str, ip_address: str, mac_address: str
) -> Generator[PCAPReplayer, None, None]:
    """
    Get the PCAPReplayer object.

    :param pcap_filename: The PCAP filename.
    :param interface: The network interface.
    :param ip_address: The IP address.
    :param mac_address: The MAC address.

    :yields: The PCAPReplayer object.

    """
    # Construct the PCAPReplayer class
    pcap_replayer = PCAPReplayer(pcap_filename, interface, ip_address)

    # Create a thread pool executor in which to run the PCAP replayer
    with ThreadPoolExecutor(max_workers=1) as executor:

        # Replay the PCAP file in a new thread.
        future = executor.submit(pcap_replayer)

        yield pcap_replayer

        # Wait until the replayer finishes
        future.result()


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

        def __call__(self, packet: Any) -> None:
            """
            Check the packets.

            :param packet: The packet.

            """
            if IP in packet:
                assert packet[IP].dst == ip_address
            if Ether in packet:
                assert packet[Ether].dst == mac_address
            self.num_packets += 1

        def stop(self, packet: Any) -> bool:
            """
            Check if we should stop.

            :param packet: The packet.

            :returns: True/False to stop

            """
            # If we have finished then return True (exits sniff)
            return self.num_packets == num_packets

    # Get the packet handler object
    packet_handler = PacketHandler()

    # Start sniffing at the network traffic
    sniff(
        iface=interface,
        prn=packet_handler,
        stop_filter=packet_handler.stop,
        store=0,
        timeout=2 * 60,
    )

    # Check the number of packets
    assert num_packets == packet_handler.num_packets
