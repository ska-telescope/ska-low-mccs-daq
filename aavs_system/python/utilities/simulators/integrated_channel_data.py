from time import sleep
import numpy as np
import socket
import struct
import time


class IntegratedChannelDataSimulator(object):
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
        self._packet_data = np.zeros((self._nof_tiles, self._nof_fpgas, self._nof_ants_per_fpga,
                                      self._nof_channel_packets, self._nof_channels_per_packet * 2), dtype=np.uint16)

        for tpm in range(self._nof_tiles):
            for fpga in range(self._nof_fpgas):
                for antenna in range(self._nof_ants_per_fpga):
                    for channel in range(self._nof_channel_packets):
                        self._packet_data[tpm][fpga][antenna][channel] = self._generate_data(tpm, fpga, antenna, channel)

        # Create socket
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_data(self, sleep_between_antennas):
        """ Generate integrated channel data """
        for tile in range(self._nof_tiles):

            for ant in range(self._nof_ants_per_fpga):

                for chan in range(int(self._nof_channels / self._nof_channels_per_packet)):
                    for fpga in range(self._nof_fpgas):
                        self._transmit_packet(tile,
                                              fpga,
                                              self._timestamp,
                                              ant + fpga * self._nof_ants_per_fpga,
                                              chan * self._nof_channels_per_packet)

                time.sleep(sleep_between_antennas)

        self._timestamp += 1

    def _transmit_packet(self, tpm_id, fpga_id, timestamp, start_antenna, start_channel):
        """ Generate a packet """
        header = 0x53 << 56 | 0x04 << 48 | 0x02 << 40 | 0x06 << 32 | 0x08
        heap_counter = 1 << 63 | 0x0001 << 48 | timestamp
        pkt_len = 1 << 63 | 0x0004 << 48 | self._packet_payload_length
        sync_time = 1 << 63 | 0x1027 << 48 | self._unix_epoch_time
        timestamp = 1 << 63 | 0x1600 << 48 | timestamp & 0xFFFFFFFFFF
        lmc_capture_mode = 1 << 63 | 0x2004 << 48 | self._lmc_capture_mode
        lmc_info = 1 << 63 | 0x2002 << 48 | start_channel << 24 | \
                   start_antenna << 8 | self._nof_ants_per_packet & 0xFF
        lmc_tpm_info = 1 << 63 | 0x2001 << 48 | tpm_id << 32 | self._station_id << 16
        sample_offset = 0 << 63 | 0x3300 << 48

        packet = struct.pack('>' + 'Q' * 9, header,
                             heap_counter,
                             pkt_len,
                             sync_time,
                             timestamp,
                             lmc_capture_mode,
                             lmc_info,
                             lmc_tpm_info,
                             sample_offset) + \
                 self._packet_data[tpm_id][fpga_id][start_antenna // self._nof_ants_per_fpga][
                     start_channel // self._nof_channels_per_packet].tobytes()

        self._socket.sendto(packet, (self._ip, self._port))

    def _generate_data(self, tpm_id, fpga_id, start_antenna, start_channel):
        """ Generate samples data set """

        start_antenna = tpm_id * self._nof_ants_per_fpga * self._nof_fpgas + \
                        fpga_id * self._nof_ants_per_fpga + start_antenna
        packet_data = np.zeros(self._packet_payload_length // 2, dtype=np.uint16)

        counter = 0
        for c in range(self._nof_channels_per_packet):
            packet_data[counter] = start_antenna * self._nof_channels + \
                                   start_channel * self._nof_channels_per_packet + c
            packet_data[counter + 1] = start_antenna * self._nof_channels + \
                                   self._nof_channels - (start_channel * self._nof_channels_per_packet + c)
            counter += 2

        return packet_data


if __name__ == "__main__":

    # Use OptionParse to get command-line arguments
    from optparse import OptionParser
    from sys import argv

    parser = OptionParser(usage="usage: %daq_receiver [options]")

    parser.add_option("-t", "--nof_tiles", action="store", dest="nof_tiles",
                      type="int", default=1, help="Number of tiles to simulate [default: 1]")
    parser.add_option("--ip", action="store", dest="ip", default="127.0.0.1",
                      help="IP to send packets to (default: 127.0.0.1)")
    parser.add_option("-p", "--period", action="store", dest="period", default=1, type=int,
                      help="Number of seconds to wait between each full transmission (default: 1 second)")

    (conf, args) = parser.parse_args(argv[1:])

    data = IntegratedChannelDataSimulator(conf.ip, 4660, nof_tiles=conf.nof_tiles)
    while True:
        data.send_data(conf.period)
        sleep(conf.period)
