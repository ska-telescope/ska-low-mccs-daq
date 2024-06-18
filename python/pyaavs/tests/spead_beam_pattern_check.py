import sys
import socket
import numpy as np
from struct import *
from builtins import input
from time import perf_counter
from optparse import OptionParser
from multiprocessing import Process, Pool

realtime_nof_processes = 16
realtime_pkt_buff = bytearray(16384 * 16384)
realtime_max_packets = 4096
realtime_pattern = [0]*1024
realtime_pattern_type = 1


def check_pattern(pkt_buffer_idx, channel_id):
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


def extract_sample(sample):
    channel_id = sample[0] + ((sample[1] & 0x3) << 7)
    counter = (sample[1] >> 2) + (sample[2] << 5) + (sample[3] << 12)
    return channel_id, counter


def check_pattern2(pkt_buffer_idx, channel_id, timestamp, timestamp_scale):
    global realtime_pattern
    global realtime_pkt_buff

    errors = 0

    pkt_reassembled = unpack('b' * 8192, realtime_pkt_buff[pkt_buffer_idx: pkt_buffer_idx + 8192])

    exp_counter = int((timestamp / timestamp_scale)) % (2**19)
    exp_channel_id = channel_id

    for k in range(0, 8192, 4):
        channel_id, counter = extract_sample(pkt_reassembled[k: k + 4])
        if exp_channel_id != channel_id or exp_counter != counter:
            print("Error at position " + str(k))
            print("Timestamp: " + str(timestamp))
            print("Timestamp: " + hex(timestamp))
            print("channel id     : expected %s, received %s" % (exp_channel_id, channel_id))
            print("packet counter : expected %s, received %s" % (exp_counter, counter))

            exp_channel_id = channel_id
            exp_counter = counter

            errors += 1
        exp_counter += 1

        if errors > 0:
            input()

    return errors


def check_buffer(id):
    global realtime_pkt_buff
    global realtime_max_packets
    global realtime_nof_processes
    global realtime_pattern_type

    spead_header_decoder = CspSpeadHeaderDecoder()

    errors = 0
    pkt_buffer_idx = 16384 * id

    for n in list(range(id, realtime_max_packets, realtime_nof_processes)):
        spead_header = spead_header_decoder.decode_header(realtime_pkt_buff[pkt_buffer_idx + 42: pkt_buffer_idx + 42 + 72])

        if spead_header.is_csp_packet and not spead_header.is_ska_spead:
            if spead_header.is_ska_spead: 
                pkt_buffer_idx_offset = pkt_buffer_idx + 42 + 56
            else:
                pkt_buffer_idx_offset = pkt_buffer_idx + 42 + 72
                
            if realtime_pattern_type == 0:
                errors += check_pattern(pkt_buffer_idx_offset,
                                        spead_header.logical_channel_id)
            else:
                errors += check_pattern2(pkt_buffer_idx_offset,
                                         spead_header.logical_channel_id,
                                         spead_header.timestamp,
                                         spead_header.timestamp_scale)

        pkt_buffer_idx += 16384 * realtime_nof_processes

    return errors


class CspSpeadHeaderDecoded:
    is_spead            : bool
    is_ska_spead        : bool
    is_csp_packet       : bool
    packet_counter      : int
    logical_channel_id  : int
    payload_length      : int
    sync_time           : int
    timestamp           : int
    center_frequency    : int
    csp_channel_info    : int
    physical_channel_id : int
    csp_antenna_info    : int
    offset              : int
    timestamp_scale     : int


class CspSpeadHeaderDecoder(Process):
    def __init__(self):
        self.spead_header = CspSpeadHeaderDecoded
        self.clear_header()

    def clear_header(self):
        self.spead_header.is_spead              = False
        self.spead_header.is_ska_spead          = False
        self.spead_header.is_csp_packet         = False
        self.spead_header.packet_counter        = 0
        self.spead_header.logical_channel_id    = 0
        self.spead_header.payload_length        = 0
        self.spead_header.sync_time             = 0
        self.spead_header.timestamp             = 0
        self.spead_header.center_frequency      = 0
        self.spead_header.scan_id               = 0
        self.spead_header.csp_channel_info      = 0
        self.spead_header.physical_channel_id   = 0
        self.spead_header.csp_antenna_info      = 0
        self.spead_header.offset                = 0
        self.spead_header.timestamp_scale       = 0

    def decode_header(self, pkt):
        items = unpack('>' + 'Q' * 9, pkt[0:8 * 9])
        self.spead_header.is_spead = False
        self.spead_header.is_csp_packet = False

        for idx in range(len(items)):
            item = items[idx]
            id = item >> 48
            val = item & 0x0000FFFFFFFFFFFF
            if not (self.spead_header.is_ska_spead == 1 and idx > 6):
                if id == 0x5304 and idx == 0:
                    self.spead_header.is_spead = True
                    if val & 0x000000000000FFFF == 0x0006:
                        self.spead_header.is_ska_spead = True
                elif id == 0x8001 and idx == 1:
                    heap_counter = val
                    if self.spead_header.is_ska_spead == False:
                        self.spead_header.packet_counter = heap_counter & 0xFFFFFFFF
                        self.spead_header.logical_channel_id = heap_counter >> 32
                    else:
                        self.spead_header.packet_counter = heap_counter & 0xFFFFFFFFFF
                elif id == 0x8004 and idx == 2:
                    self.spead_header.payload_length = val
                elif id == 0x9027 and idx == 3:
                    self.spead_header.sync_time = val
                elif id == 0x9600 and idx == 4:
                    self.spead_header.timestamp = val
                elif id == 0x9011 and idx == 5:
                    self.spead_header.center_frequency = val & 0xFFFFFFFF
                    self.spead_header.timestamp_scale = 1080
                elif id == 0xb010 and idx == 5:
                    self.spead_header.scan_id = val & 0xffffffff
                    self.spead_header.center_frequency = 0
                    self.spead_header.timestamp_scale = 108
                elif id == 0xb010 and idx == 3 and self.spead_header.is_ska_spead == True:
                    self.spead_header.scan_id = val & 0xffffffffffff
                    self.spead_header.timestamp_scale = 108
                elif id == 0xb000 and idx == 6:
                    self.spead_header.is_csp_packet = True
                    self.spead_header.csp_channel_info = val
                    self.spead_header.physical_channel_id = val & 0x3FF
                elif id == 0xb000 and idx == 4 and self.spead_header.is_ska_spead == True:
                    self.spead_header.is_csp_packet = True
                    self.spead_header.csp_channel_info = val
                    self.spead_header.logical_channel_id = val >> 32
                    self.spead_header.physical_channel_id = val & 0x3FF 
                elif id == 0xb001 and idx == 7:
                    self.spead_header.csp_antenna_info = val
                elif id == 0xb001 and idx == 5 and self.spead_header.is_ska_spead == True:
                    self.spead_header.csp_antenna_info = val
                elif id == 0x3300 and idx == 8:
                    self.spead_header.offset = 9*8
                elif id == 0x3300 and idx == 6 and self.spead_header.is_ska_spead == True:
                    self.spead_header.offset = 7*8
                else:
                    print("Error in header")
                    print("Unexpected item " + hex(item) + " at position " + str(idx))
                    input("Press a key...")
                    break
                
        return self.spead_header


class SpeadRxBeamPatternCheck(Process):
    def __init__(self, port, eth_if="eth2", *args, **kwargs):
        self.port = port
        self.raw_socket = True
        self.spead_header_decoder = CspSpeadHeaderDecoder()
        self.spead_header = CspSpeadHeaderDecoded

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

    def spead_header_decode(self, pkt):
        self.spead_header = self.spead_header_decoder.decode_header(pkt)
        return self.spead_header.is_csp_packet

    def check_buffer_multi(self):
        global realtime_pkt_buff
        global realtime_max_packets

        # t1_start = perf_counter()
        with Pool(realtime_nof_processes) as p:
            error_list = p.map(check_buffer, list(range(realtime_nof_processes)))
        # t1_stop = perf_counter()
        # elapsed = t1_stop - t1_start
        # print(elapsed)

        if len(error_list) > 1:
            errors = np.sum(np.asarray(error_list), axis=0)
        else:
            errors = error_list

        return errors

    def check_data(self, pattern, pattern_type=1):
        global realtime_pkt_buff
        global realtime_max_packets
        global realtime_pattern
        global realtime_pattern_type

        realtime_pattern = pattern
        realtime_pattern_type = pattern_type

        pkt_buff_ptr = memoryview(realtime_pkt_buff)
        pkt_buff_idx = 0
        for n in range(realtime_max_packets):
            self.recv2(pkt_buff_ptr)
            pkt_buff_idx += 16384
            pkt_buff_ptr = pkt_buff_ptr[16384:]

        return self.check_buffer_multi()
