# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module implements a replay mechanism for PCAP files using Scapy."""
from __future__ import annotations

import fcntl
import socket
import struct
from logging import Logger
from pathlib import Path
from threading import Thread

from scapy.layers.inet import IP, UDP, Ether
from scapy.sendrecv import sendp
from scapy.utils import rdpcap, wrpcap


class PcapReplayer:
    """A class for replaying pcap files to the DAQ."""

    def __init__(self, logger: Logger) -> None:
        """
        Initialize the PcapReplayer.

        :param logger: the logger to be used by this object.
        """
        self._logger = logger
        self.interface: str | None = None
        self.dst_ip: str | None = None
        self._mac_address: str | None = None
        self._integrated_channel_file = str(
            Path(__file__).parent / "replay_data" / "channel_integ_96_192.pcap"
        )
        self._files = [self._integrated_channel_file]
        self._reroute_thread: Thread | None = None

    def _get_mac_address(self: PcapReplayer) -> str:
        assert self.interface is not None
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            info = fcntl.ioctl(
                s.fileno(),
                0x8927,  # SIOCGIFHWADDR
                struct.pack("256s", self.interface.encode("utf-8")[:15]),
            )
            return ":".join(f"{b:02x}" for b in info[18:24])

    def reroute_packets(self: PcapReplayer) -> None:
        """Spin up the task to reroute packets to this DaqReceiver."""
        self._reroute_thread = Thread(target=self._reroute_task, name="ReroutePcaps")
        self._reroute_thread.start()

    def _reroute_task(self: PcapReplayer) -> None:
        """Reroute packets to this DaqReceiver."""
        if self.dst_ip is None:
            self._logger.error(
                f"Cannot reroute packets, unknown destination IP: {self.dst_ip}"
            )
            return
        self._mac_address = self._get_mac_address()
        for file in self._files:
            packets = rdpcap(file)
            for packet in packets:
                if IP in packet:
                    packet[IP].dst = self.dst_ip
                    del packet[IP].chksum
                if UDP in packet:
                    del packet[UDP].chksum
                if Ether in packet:
                    packet[Ether].dst = self._mac_address
            wrpcap(file, packets)

    def _replay(self: PcapReplayer, pcap_file: str) -> None:
        """
        Replay packets from a PCAP file on the specified network interface.

        :param pcap_file: The path to the PCAP file to replay.
        """
        if self.interface is None or self.dst_ip is None:
            self._logger.error(
                "Cannot send data, unknown interface or dst_ip: "
                f"{self.interface=}, {self.dst_ip=}"
            )
            return
        # Wait for reroute to finish if it's running
        if self._reroute_thread and self._reroute_thread.is_alive():
            self._logger.info("Waiting for reroute thread to finish...")
            self._reroute_thread.join()
        try:
            for packet in rdpcap(pcap_file):
                sendp(packet, iface=self.interface, verbose=False)
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error(f"Error replaying PCAP file {pcap_file}: {e}")

    def replay_integrated_channel(self: PcapReplayer) -> None:
        """Replay the stored integrated channel data pcap file."""
        self._replay(self._integrated_channel_file)
