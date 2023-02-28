# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the bdd test steps of the daq status reporting."""
from __future__ import annotations

import json
import socket
import struct
import threading
import time
from time import sleep

import numpy as np
import pytest
import tango
from pytest_bdd import given, parsers, scenarios, then, when
from ska_tango_testing.context import TangoContextProtocol


def send_data_thread(data, event):
    """Thread to send data untill told to stop."""
    while True:
        data.send_data(1)
        sleep(1)
        if event.is_set():
            break


class IntegratedChannelDataSimulator(object):
    """A class to send simulated integrated channel data."""

    def __init__(self, ip, port, nof_tiles=1):

        self._ip = ip
        self._port = port

        self._unix_epoch_time = int(time.time())
        self._timestamp = 0
        self._lmc_capture_mode = 0x6
        self._station_id = 0
        self._packet_payload_length = 1024
        self._data_type = np.uint16

        self._nof_tiles = nof_tiles
        self._nof_fpgas = 2
        self._nof_pols = 2
        self._nof_ants_per_fpga = 8
        self._nof_ants_per_packet = 1
        self._nof_channels = 512
        self._nof_channels_per_packet = 256
        self._nof_channel_packets = self._nof_channels // self._nof_channels_per_packet
        self._nof_antenna_packets = self._nof_ants_per_fpga // self._nof_ants_per_packet

        self._timestamp = 0

        # Generate test data
        self._packet_data = np.zeros(
            (
                self._nof_tiles,
                self._nof_fpgas,
                self._nof_ants_per_fpga,
                self._nof_channel_packets,
                self._nof_channels_per_packet * 2,
            ),
            dtype=np.uint16,
        )

        for tpm in range(self._nof_tiles):
            for fpga in range(self._nof_fpgas):
                for antenna in range(self._nof_ants_per_fpga):
                    for channel in range(self._nof_channel_packets):
                        self._packet_data[tpm][fpga][antenna][
                            channel
                        ] = self._generate_data(tpm, fpga, antenna, channel)

        # Create socket
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_data(self, sleep_between_antennas):
        """Generate integrated channel data."""
        for tile in range(self._nof_tiles):

            for ant in range(self._nof_ants_per_fpga):

                for chan in range(
                    int(self._nof_channels / self._nof_channels_per_packet)
                ):
                    for fpga in range(self._nof_fpgas):
                        self._transmit_packet(
                            tile,
                            fpga,
                            self._timestamp,
                            ant + fpga * self._nof_ants_per_fpga,
                            chan * self._nof_channels_per_packet,
                        )

                time.sleep(sleep_between_antennas)

        self._timestamp += 1

    def _transmit_packet(
        self, tpm_id, fpga_id, timestamp, start_antenna, start_channel
    ):
        """Generate a packet."""
        header = 0x53 << 56 | 0x04 << 48 | 0x02 << 40 | 0x06 << 32 | 0x08
        heap_counter = 1 << 63 | 0x0001 << 48 | timestamp
        pkt_len = 1 << 63 | 0x0004 << 48 | self._packet_payload_length
        sync_time = 1 << 63 | 0x1027 << 48 | self._unix_epoch_time
        timestamp = 1 << 63 | 0x1600 << 48 | timestamp & 0xFFFFFFFFFF
        lmc_capture_mode = 1 << 63 | 0x2004 << 48 | self._lmc_capture_mode
        lmc_info = (
            1 << 63
            | 0x2002 << 48
            | start_channel << 24
            | start_antenna << 8
            | self._nof_ants_per_packet & 0xFF
        )
        lmc_tpm_info = 1 << 63 | 0x2001 << 48 | tpm_id << 32 | self._station_id << 16
        sample_offset = 0 << 63 | 0x3300 << 48

        packet = (
            struct.pack(
                ">" + "Q" * 9,
                header,
                heap_counter,
                pkt_len,
                sync_time,
                timestamp,
                lmc_capture_mode,
                lmc_info,
                lmc_tpm_info,
                sample_offset,
            )
            + self._packet_data[tpm_id][fpga_id][
                start_antenna // self._nof_ants_per_fpga
            ][start_channel // self._nof_channels_per_packet].tobytes()
        )

        self._socket.sendto(packet, (self._ip, self._port))

    def _generate_data(self, tpm_id, fpga_id, start_antenna, start_channel):
        """Generate samples data set."""

        start_antenna = (
            tpm_id * self._nof_ants_per_fpga * self._nof_fpgas
            + fpga_id * self._nof_ants_per_fpga
            + start_antenna
        )
        packet_data = np.zeros(self._packet_payload_length // 2, dtype=np.uint16)

        counter = 0
        for c in range(self._nof_channels_per_packet):
            packet_data[counter] = (
                start_antenna * self._nof_channels
                + start_channel * self._nof_channels_per_packet
                + c
            )
            packet_data[counter + 1] = (
                start_antenna * self._nof_channels
                + self._nof_channels
                - (start_channel * self._nof_channels_per_packet + c)
            )
            counter += 2

        return packet_data


scenarios("./features/daq_spead_capture.feature")


@pytest.fixture(name="daq_short_name", scope="module")
def subrack_short_name_fixture() -> str:
    """
    Return the short name of the subrack device.

    :return: the short name of the subrack device
    """
    return "daq"


@given(parsers.cfparse("interface {interface}"), target_fixture="interface")
def daq_interface(
    interface: str,
) -> tango.DeviceProxy:
    """
    A fixture representing the interface to send data to.

    :param interface: The interface to send data to.
    """
    return interface


@given(parsers.cfparse("port {port}"), target_fixture="port")
def daq_port(
    port: str,
) -> tango.DeviceProxy:
    """
    A fixture representing the port to send data to.

    :param port: The port to send data to.
    """
    return port


@given("an MccsDaqReceiver", target_fixture="daq_receiver")
def daq_receiver_fixture(
    daq_short_name,
    get_device,
) -> tango.DeviceProxy:
    """
    Return the daq_receiver device.

    :param daq_short_name: Short name of the DAQ receiver Tango device
    :return: the daq_receiver device
    """
    return get_device(daq_short_name)


@given(parsers.cfparse("Daq is configured to listen on specified interface:port"))
def configure_daq(daq_receiver, interface, port):
    """
    Configure the Daq device.

    :param daq_receiver: the daq_receiver device
    :param interface: The interface to send data to.
    :param port: The port to send data to.
    """
    daq_config = {
        "receiver_ports": [4660],
        "receiver_interface": "127.0.0.1",
    }
    daq_receiver.Configure(json.dumps(daq_config))

    assert daq_config.items() <= json.loads(daq_receiver.GetConfiguration()).items()
    # assert this worked


@given(parsers.cfparse("The daq is started with '{daq_modes_of_interest}'"))
def start_daq(daq_receiver, daq_modes_of_interest):
    """
    Start the daq device.

    :param daq_receiver: the daq_receiver device
    :param daq_modes_of_interest: the modes to listen for.
    """
    print(f"modes : {daq_modes_of_interest}")

    daq_receiver.adminMode = 0
    daq_config = {
        "modes_to_start": daq_modes_of_interest,
        "grpc_polling_period": 1,
    }
    daq_receiver.Start(json.dumps(daq_config))
    ##assert this worked


@when(
    parsers.cfparse(
        "Simulated data from {no_of_tiles} of type '{daq_modes_of_interest}' is sent to a specified interface:port"
    ),
    target_fixture="stop_data_event",
)
def send_simulated_data(
    daq_receiver, no_of_tiles, daq_modes_of_interest, interface, port
):
    """
    Start sending simulated data in a loop.

    :param daq_receiver: the daq_receiver device
    :param no_of_tiles: the number of tiles to simulate
    :param daq_modes_of_interest: the modes to listen for.
    :param interface: The interface to send data to.
    :param port: The port to send data to.

    :return stop_data_event: a event to stop thread.
    """
    # the test runner can utilise the data services of DAQ allowing us to send data to the correct location.
    data = IntegratedChannelDataSimulator("daqreceiver-001-data-svc", 4660, 1)
    stop_data_event = threading.Event()
    thread = threading.Thread(target=send_data_thread, args=[data, stop_data_event])
    thread.start()
    print(f"modes : {daq_modes_of_interest}, {interface}: {port}")
    return stop_data_event


@then(
    parsers.cfparse("Daq reports that is has captured data '{daq_modes_of_interest}'")
)
def check_capture(
    daq_receiver, daq_modes_of_interest, stop_data_event, change_event_callbacks
):
    """ """
    assert "integrated_channel" in daq_receiver.dataReceivedResult

    # change_event_callbacks[
    #     f"{daq_receiver.dev_name()}/dataReceivedResult"
    # ].assert_change_event(
    #     "integrated_channel", lookahead=4
    # )

    stop_data_event.set()


@then("Daq writes to a file.")
def check_writes(daq_receiver):
    # TODO:
    # - set up persistent volume
    # - search for the file written
    # - validate the file content
    print("done")
