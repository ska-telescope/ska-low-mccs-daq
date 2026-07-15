#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""
PCAP Replayer Utility.

This module provides functionality to replay PCAP files using scapy.

"""


import logging
import os
from tempfile import NamedTemporaryFile
from typing import Any

from scapy.layers.l2 import ARP
from scapy.layers.inet import IP, UDP, Ether
from scapy.plist import PacketList
from scapy.sendrecv import sendp, srp1
from scapy.utils import PcapWriter, rdpcap


def get_mac_address(ip_address: str, interface: str) -> str:
    """
    Get the mac address directly from IP and interface.

    :param ip_address: The destination ip address.
    :param interface: The network interface.

    :returns: The mac address.

    """
    # Construct the request
    request = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=ip_address)

    # Get the answer from the destination
    answered = srp1(request, iface=interface, timeout=1, verbose=False)

    # If we have an answer, get the mac address
    return answered[Ether].src if answered else "00:00:00:00:00:00"


class PCAPReplayer:
    """
    PCAP Replayer class.

    This class replays PCAP files for DAQ testing.

    """

    def __init__(
        self,
        filename: str,
        interface: str,
        ip_address: str,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initialise the PCAP Replayer.

        :param filename: The PCAP filename.
        :param interface: The interface to send to
        :param ip_address: The IP address to send to
        :param logger: The logger object.

        :raises RuntimeError: If mac address of interface is None

        """
        # Set the input parameters
        self._filename = filename
        self._interface = interface
        self._ip_address = ip_address
        self._logger = logger or logging.getLogger()

        # Get the mac address
        self._mac_address = get_mac_address(ip_address, interface)

        # Ensure that the mac address is not None
        if self._mac_address is None:
            raise RuntimeError(
                f"Interface '{interface}' must have valid mac address, "
                f"got '{self._mac_address}'"
            )

        # Prepare the packets and set the cached filename
        self._cached_filename = self._prepare_cached_pcap_file(self._filename)

    def __call__(self) -> None:
        """Replay the PCAP file."""
        # For each packet, prepare it for DAQ and then re-send it. NOTE We may
        # be able to get more performance using conf.L2socket directly but need
        # to be careful about missing packets.
        sendp(
            self._read_pcap_file(self._cached_filename),
            iface=self._interface,
            verbose=False,
            inter=0,
        )

    def _prepare_cached_pcap_file(self, filename: str) -> str:
        """

        Prepare the cached PCAP file.

        :param filename: The PCAP file to read

        :returns: The prepared PCAP filename.

        """
        # Open a temporary file, read the PCAP file and then, for each packet,
        # prepare it for DAQ and save it to the cached file
        cached_filename = ""
        with NamedTemporaryFile(delete=False) as outfile, PcapWriter(outfile) as writer:
            for packet in self._read_pcap_file(filename):
                writer.write(self._prepare_packet(packet))
            cached_filename = outfile.name
        return cached_filename

    def _read_pcap_file(self, filename: str) -> PacketList:
        """
        Read the PCAP file.

        :param filename: The PCAP file to read

        :returns: The packets from the PCAP file.

        :raises FileNotFoundError: If the PCAP file is not found.

        """
        # Check if the file exists
        if not os.path.exists(filename):
            raise FileNotFoundError(f"PCAP file not found: {filename}")

        # Output some debug info
        self._logger.debug(f"Reading PCAP file {filename}")

        # Return the packets from the PCAP file
        return rdpcap(filename)

    def _prepare_packet(self, packet: Any) -> Any:
        """
        Prepare the packet to be resent.

        :param packet: The PCAP packet.

        :returns: The modified PCAP packet.

        """
        # Output some debug info
        self._logger.debug(
            f"Preparing packet with destination IP={self._ip_address} "
            f"and MAC address={self._mac_address}"
        )

        # Modify the destination IP and MAC address of the the packet
        if IP in packet:
            packet[IP].dst = self._ip_address
            del packet[IP].chksum
        if UDP in packet:
            del packet[UDP].chksum
        if Ether in packet:
            packet[Ether].dst = self._mac_address

        # Return the modifed packet
        return packet

    def _send_packet(self, packet: Any) -> None:
        """
        Resent the PCAP packet.

        :param packet: The PCAP packet.

        """
        sendp(packet, iface=self._interface, verbose=False)
