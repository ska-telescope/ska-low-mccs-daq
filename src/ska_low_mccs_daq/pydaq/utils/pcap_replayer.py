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


from typing import Any
from getmac import get_mac_address # type: ignore
from concurrent.futures import ThreadPoolExecutor
import os
import asyncio
import logging
import scapy.utils
import scapy.sendrecv
import time
from scapy.layers.inet import IP, UDP, Ether
from scapy.sendrecv import sendp, sniff
from scapy.utils import rdpcap, wrpcap


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
            logger: logging.Logger | None = None) -> None:
        """
        Initialise the PCAP Replayer.

        :param filename: The PCAP filename.
        :param interface: The interface to send to
        :param ip_address: The IP address to send to
        :param logger: The logger object.

        """
        # Set the input parameters
        self._filename = filename
        self._interface = interface
        self._ip_address = ip_address
        self._logger = logger or logging.getLogger()

        # Get the mac address
        self._mac_address = get_mac_address(interface=interface)

    def __call__(self) -> None:
        """ Replay the PCAP file. """
        # For each packet, prepare it for DAQ and then re-send it
        for packet in self._read_pcap_file():
            self._send_packet(self._prepare_packet(packet))

    def _read_pcap_file(self) -> Any:
        """
        Read the PCAP file.

        :returns: The packets from the PCAP file.

        """
        # Check if the file exists
        if not os.path.exists(self._filename):
            raise FileNotFoundError(f"PCAP file not found: {self._filename}")

        # Output some debug info
        self._logger.debug(f"Reading PCAP file {self._filename}")
        
        # Return the packets from the PCAP file
        return rdpcap(self._filename)

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

    def _send_packet(self, packet: Any):
        """
        Resent the PCAP packet.

        :param packet: The PCAP packet.

        """
        self._logger.debug(f"Sending packet {packet}")
        sendp(packet, iface=self._interface, verbose=False)



if __name__ == '__main__':

    logger = logging.getLogger()
    # logger.setLevel(logging.DEBUG)

    interface = "eth0"  # Replace with your interface name

    pcap_replayer = PCAPReplayer(
        "tests/data/pcap-data/channel_integ_96_192.pcap",
        interface=interface,
        ip_address="0.0.0.0",
        logger=logger)

    with ThreadPoolExecutor(max_workers=1) as executor:

        print("Starting")
        
        future = executor.submit(pcap_replayer)

        print("Doing other stuff")

        def packet_handler(packet):
            print(packet)

        sniff(iface=interface, prn=packet_handler, store=0)

        print(future.result())

        print("Finish")




