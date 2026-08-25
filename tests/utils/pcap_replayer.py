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
import socket
import time
from tempfile import NamedTemporaryFile

from scapy.all import Packet, Raw, raw
from scapy.layers.inet import IP, UDP, Ether
from scapy.plist import PacketList
from scapy.utils import PcapWriter, rdpcap


class PCAPReplayer:
    """
    PCAP Replayer class.

    This class replays PCAP files for DAQ testing.

    """

    def __init__(
        self,
        filename: str,
        host: str,
        port: int,
        delay: float = 0,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initialise the PCAP Replayer.

        :param filename: The PCAP filename.
        :param host: The IP address to send to
        :param port: The port
        :param delay: The delay between packets
        :param logger: The logger object.

        """
        # Set the input parameters
        self._filename = filename
        self._host = host
        self._port = port
        self._delay = delay
        self._logger = logger or logging.getLogger()

        # Prepare the packets and set the cached filename
        self._cached_filename = self._prepare_cached_pcap_file(self._filename)

    def __call__(self) -> None:
        """Replay the PCAP file."""
        # For each packet, prepare it for DAQ and then re-send it. NOTE We set
        # a small delay to be careful about missing packets.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for packet in self._read_pcap_file(self._cached_filename):
            sock.sendto(raw(self._extract_payload(packet)), (self._host, self._port))
            if self._delay > 0:
                time.sleep(self._delay)

    def _extract_payload(self, packet: Packet) -> Raw:
        """
        Extract the payload from the packet.

        :param packet: The packet.

        :returns: The payload.

        """
        if UDP in packet:
            payload = packet[UDP].payload
        elif IP in packet:
            payload = packet[IP].payload
        elif Ether in packet:
            payload = packet[Ether].payload
        else:
            payload = packet
        return payload

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

    def _prepare_packet(self, packet: Packet) -> Packet:
        """
        Prepare the packet to be resent.

        :param packet: The PCAP packet.

        :returns: The modified PCAP packet.

        """
        # Output some debug info
        self._logger.debug(f"Preparing packet with destination IP={self._host}")

        # Modify the destination IP and MAC address of the the packet
        if IP in packet:
            packet[IP].dst = self._host
            del packet[IP].chksum
        if UDP in packet:
            del packet[UDP].chksum

        # Return the modifed packet
        return packet
