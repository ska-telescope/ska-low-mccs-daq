import sys
import socket
import numpy as np
from struct import *
from builtins import input
from time import perf_counter
from optparse import OptionParser
from multiprocessing import Process, Pool

realtime_nof_processes = 8
realtime_pkt_buff = bytearray(16384 * 16384)
realtime_max_packets = 4096
realtime_pattern = [0]*1024

@dataclass
class CspSpeadHeaderDecoded:
    is_spead            : bool
    is_csp_packet       : bool
    packet_counter      : int
    logical_channel_id  : int
    payload_length: int
    sync_time: int
    timestamp: int
    center_frequency: int
    csp_channel_info: int
    physical_channel_id: int
    csp_antenna_info: int
    offset: int

class SpeadRxBeamPatternCheck(Process):
    def __init__(self, port, eth_if="eth2", *args, **kwargs):
        self.port = port
        self.raw_socket = True

        if not self.raw_socket:
            self.sock = socket.socket(socket.AF_INET,      # Internet
                                socket.SOCK_DGRAM)   # UDP
            self.sock.settimeout(1)
            self.sock.bind(("0.0.0.0", self.port))
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32*1024*1024)
            # self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_NO_CHECK, 1)
        else:
            #try:
            ETH_P_ALL = 3
            ETH_P_IP = 0x800
            self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_IP))
            # self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 0)
            # self.sock.bind(("0.0.0.0", 0))
            self.sock.bind((eth_if, 0))
            #except(socket.error):
            #    print('Socket could not be created.')
            #    sys.exit()

        self.data_buff = [0] * 8192
        self.center_frequency = 0
        self.payload_length = 0
        self.sync_time = 0
        self.timestamp = 0
        self.csp_channel_info = 0
        self.csp_antenna_info = 0
        self.tpm_info = 0
        self.fpga_id = 0
        self.offset = 13*8
        self.pkt_cnt = 0
        self.packet_counter = 0
        self.logical_channel_id = 0
        self.exp_pkt_cnt = -1
        self.id = 0
        self.is_spead = False
        self.processed_frame = 0
        self.accu_x = 0
        self.accu_y = 0
        self.nof_processed_samples = 0

    def close_socket(self):
        self.sock.close()

    def recv(self):
        if not self.raw_socket:
            pkt, addr = self.sock.recvfrom(1024 * 10)
            return pkt
        else:
            while True:
                pkt = self.sock.recv(1024 * 10)
                header = unpack('!' + 'H'*20, pkt[:40])
                # for n in range(20):
                #     print(hex(header[n]))
                if header[18] == self.port:
                    return pkt[42:]

    def recv2(self, buffer):
        while True:
            nbytes = self.sock.recv_into(buffer, 1024 * 10)
            if nbytes > 8192:
                header = unpack('!' + 'H'*20, buffer[:40])
                if header[18] == self.port:
                    return nbytes

    def spead_header_decode(self, pkt, first_channel = -1):
        items = unpack('>' + 'Q'*9, pkt[0:8*9])
        self.is_spead = False
        is_csp_packet = False
        # print("--------------------------------")
        for idx in range(len(items)):
            item = items[idx]
            # print(hex(item))
            id = item >> 48
            val = item & 0x0000FFFFFFFFFFFF
            # print(hex(id) + " " + hex(val))
            if id == 0x5304 and idx == 0:
                self.is_spead = True
            elif id == 0x8001 and idx == 1:
                heap_counter = val
                self.packet_counter = heap_counter & 0xFFFFFFFF
                self.logical_channel_id = heap_counter >> 32
            elif id == 0x8004 and idx == 2:
                self.payload_length = val
            elif id == 0x9027 and idx == 3:
                self.sync_time = val
            elif id == 0x9600 and idx == 4:
                self.timestamp = val
            elif id == 0x9011 and idx == 5:
                if first_channel >= 0:
                    self.center_frequency = val & 0xFFFFFFFF
                    exp_freq = 400e6*(self.logical_channel_id + first_channel) / 512
                    if self.center_frequency != exp_freq:
                        print("Error frequency ID")
                        print("Expected ID " + str(exp_freq) + ", received " + str(self.center_frequency))
                        print(hex(val))
                        print("Received logical channel_id: " + str(self.logical_channel_id))
                        input("Press a key...")
                        # break
            elif id == 0xb000 and idx == 6:
                is_csp_packet = True
                if first_channel >= 0:
                    self.csp_channel_info = val
                    physical_channel_id = val & 0x3FF
                    if physical_channel_id != self.logical_channel_id + first_channel:
                        print("Error physical channel ID")
                        print("Expected ID " + str(self.logical_channel_id + first_channel) + ", received " + str(physical_channel_id))
                        print(hex(val))
                        print("Received logical channel_id: " + str(self.logical_channel_id))
                        input("Press a key...")
                        # break
            elif id == 0xb001 and idx == 7:
                self.csp_antenna_info = val
            elif id == 0x3300 and idx == 8:
                self.offset = 9*8
            else:
                print("Error in header")
                print("Unexpected item " + hex(item) + " at position " + str(idx))
                input("Press a key...")
                break
        return is_csp_packet

    def check_pattern(self, pkt_buffer_idx, channel_id):
        global realtime_pattern
        global realtime_pkt_buff

        errors = 0

        pkt_reassembled = unpack('b' * 8192, realtime_pkt_buff[pkt_buffer_idx: pkt_buffer_idx + 8192])

        for k in range(0, 8192, 4):
            if pkt_reassembled[k + 0] != realtime_pattern[channel_id][0] or \
               pkt_reassembled[k + 1] != realtime_pattern[channel_id][1] or \
               pkt_reassembled[k + 2] != realtime_pattern[channel_id][2] or \
               pkt_reassembled[k + 3] != realtime_pattern[channel_id][3]:
                errors += 1

        return errors

    def check_buffer(self):
        global realtime_pkt_buff
        global realtime_max_packets

        errors = 0
        pkt_buffer_idx = 0

        for n in range(realtime_max_packets):
            # print(n)
            if self.spead_header_decode(realtime_pkt_buff[pkt_buffer_idx + 42:pkt_buffer_idx + 42 + 72]):
                # print(self.lmc_capture_mode)
                # print(self.lmc_tpm_id)

                pkt_buffer_idx_offset = pkt_buffer_idx + 42 + 72
                errors += self.check_pattern(pkt_buffer_idx_offset, self.logical_channel_id)

            pkt_buffer_idx += 16384

        return errors

    def check_data(self, pattern):
        global realtime_pkt_buff
        global realtime_max_packets
        global realtime_pattern

        realtime_pattern = pattern

        pkt_buff_ptr = memoryview(realtime_pkt_buff)
        pkt_buff_idx = 0
        for n in range(realtime_max_packets):
            self.recv2(pkt_buff_ptr)
            pkt_buff_idx += 16384
            pkt_buff_ptr = pkt_buff_ptr[16384:]
        return self.check_buffer()
