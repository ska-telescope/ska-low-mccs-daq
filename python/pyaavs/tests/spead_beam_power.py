import sys
import socket
import numpy as np
from struct import *
from builtins import input
from optparse import OptionParser
from multiprocessing import Process

raw_socket = True

class spead_rx(Process):
    def __init__(self, port, eth_if="eth2", *args, **kwargs):
        self.port = port

        if not raw_socket:
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
        self.logical_channel_id = 0
        self.exp_pkt_cnt = -1
        self.id = 0
        self.is_spead = 0
        self.processed_frame = 0
        self.accu_x = 0
        self.accu_y = 0
        self.nof_processed_samples = 0

    def close_socket(self):
        self.sock.close()

    def recv(self):
        if not raw_socket:
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

    def spead_header_decode(self, pkt, first_channel = -1):
        items = unpack('>' + 'Q'*9, pkt[0:8*9])
        self.is_spead = 0
        is_csp_packet = False
        # print("--------------------------------")
        for idx in range(len(items)):
            item = items[idx]
            # print(hex(item))
            id = item >> 48
            val = item & 0x0000FFFFFFFFFFFF
            # print(hex(id) + " " + hex(val))
            if id == 0x5304 and idx == 0:
                self.is_spead = 1
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

    def process_buffer(self, channel_id):
        if self.logical_channel_id == channel_id:
            values = np.asarray(self.data_buff)
            deinterleaved_pols = np.zeros((2,4096), dtype=np.int32)
            idx0 = 0
            idx1 = 0
            for n in range(len(self.data_buff)):
                if n % 4 == 0:
                    deinterleaved_pols[0, idx0] = values[n]
                    idx0 += 1
                elif n % 4 == 1:
                    deinterleaved_pols[0, idx0] = values[n]
                    idx0 += 1
                elif n % 4 == 2:
                    deinterleaved_pols[1, idx1] = values[n]
                    idx1 += 1
                elif n % 4 == 3:
                    deinterleaved_pols[1, idx1] = values[n]
                    idx1 += 1

            self.accu_x += np.sum(np.power(deinterleaved_pols[0, :], 2))
            self.accu_y += np.sum(np.power(deinterleaved_pols[1, :], 2))

            self.nof_processed_samples += int(len(self.data_buff) / 4)

    def get_power(self, nof_samples, channel_id):
        while True:
            while True:
                try:
                    _pkt = self.recv()
                    # print("pkt")
                    # print(_pkt[0:128])
                    break
                except socket.timeout:
                    print("socket timeout!")
                    pass

            if len(_pkt) > 8192:
                if self.spead_header_decode(_pkt):
                    self.data_buff = unpack('b' * self.payload_length, _pkt[self.offset:])
                    self.process_buffer(channel_id)
            if self.nof_processed_samples >= nof_samples:
                ret_x = int(self.accu_x / self.nof_processed_samples)
                ret_y = int(self.accu_y / self.nof_processed_samples)
                self.accu_x = 0
                self.accu_y = 0
                self.nof_processed_samples = 0
                return 10*np.log10(ret_x), 10*np.log10(ret_y)

if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("-p",
                      dest="port",
                      default="4660",
                      help="UDP port")
    parser.add_option("-c",
                      dest="logic_channel",
                      default="0",
                      help="Logical Channel ID")
    parser.add_option("-n",
                      dest="nof_samples",
                      default="131072",
                      help="Number of samples to integrate")

    (options, args) = parser.parse_args()

    spead_rx_inst = spead_rx(int(options.port))
    #x, y = spead_rx_inst.get_power(int(options.nof_samples), int(options.logic_channel))
    while True:
        print(spead_rx_inst.get_power(256*1024, 0))
    #print(x, y)
