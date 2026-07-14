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

from getmac import get_mac_address  # type: ignore
from scapy.layers.inet import IP, UDP, Ether
from scapy.plist import PacketList
from scapy.sendrecv import sendp
from scapy.utils import PcapWriter, rdpcap


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
        self._mac_address = get_mac_address(interface=interface)

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
        # For each packet, prepare it for DAQ and then re-send it
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
        with NamedTemporaryFile(delete=False) as outfile, PcapWriter(outfile) as writer:
            for packet in self._read_pcap_file(filename):
                writer.write(self._prepare_packet(packet))
            return outfile.name

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
