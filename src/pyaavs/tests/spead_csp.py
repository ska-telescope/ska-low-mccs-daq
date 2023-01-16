import os
import time
import h5py
import math
import socket
import random
from struct import *
from builtins import input
from optparse import OptionParser
from multiprocessing import Process
import test_functions as tf
#import pyshark
import binascii

def s_round(data, bits, max_width=32):
    if bits == 0:
        return data
    elif data == -2**(max_width-1):
        return data
    else:
        c_half = 2**(bits-1)
        if data >= 0:
            data = (data + c_half + 0) >> bits
        else:
            data = (data + c_half - 1) >> bits
        return data

def signed(data, bits=8):
    data = data % (2**bits)
    if data >= 2**(bits-1):
        return data - 2**bits
    else:
        return data

class spead_rx(Process):
    def __init__(self, port, *args, **kwargs):
        self.port = port
        self.sock = socket.socket(socket.AF_INET,      # Internet
                                socket.SOCK_DGRAM)   # UDP
        self.sock.settimeout(1)
        self.sock.bind(("0.0.0.0", self.port))
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32*1024*1024)

        self.reassembled = [[0] * int(8192 / 4)] * 392
        self.data_buff = [0] * int(8192 / 4)
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
        self.file_name = "integrated_channel_" + str(int(time.time())) + '.h5'
        self.is_spead = 0
        self.processed_frame = 0
        self.exp_data = [[0] * 4 ] * 1024
        self.checked = 0
        self.frame_offset_0 = -1
        self.frame_offset_1 = -1
        self.frame_offset_error_0 = 0
        self.frame_offset_error_1 = 0
        self.file = open("dump_error.txt","w")
        self.file.write("")
        self.file.close()        

        #random.seed(0)
        #    self.exp_buff = [0] * 1024
        #for n in range(1024):
        #    self.exp_buff[n] = random.randint(0, 255)
        #self.exp_buff = range(1024)

    def close_socket(self):
        self.sock.close()

    def sum_data(self, value, nof_tpms):
        value = value * nof_tpms
        value = tf.s_round(value, 4, 16)
        if value > 127:
            value = 127
        if value < -128:
            value = -128
        return value

    def beam_data(self, values, nof_tpms):
        ret = []
        if type(values) is not list:
            val = [values]
        else:
            val = values
        for v in val:
            ret.append(self.sum_data(v, nof_tpms))
        return ret

    def make_exp_data(self, nof_tpms, pattern, adders):
        if len(pattern) != 1024:
            print("Pattern must be a 1024 element array")
            exit(-1)
        for n in range(512):
            data = tf.get_beamf_pattern_data(n, pattern, adders, 4-int(math.log(nof_tpms, 2)))
            data = self.beam_data(data, nof_tpms)
            self.exp_data[n] = data

    def spead_header_decode(self, pkt, first_channel):
        items = unpack('>' + 'Q'*9, pkt[0:8*9])
        self.is_spead = 0
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
                self.center_frequency = val & 0xFFFFFFFF
                exp_freq = 400e6 * (self.logical_channel_id + first_channel) / 512
                if self.center_frequency != exp_freq:
                    print("Error frequency ID")
                    print("Expected ID " + str(exp_freq) + ", received " + str(self.center_frequency))
                    print(hex(val))
                    print("Received logical channel_id: " + str(self.logical_channel_id))
                    input("Press a key...")
                    # break
            elif id == 0xb000 and idx == 6:
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

    def dump(self, channel_id):
        s = "Packet Error \n"
        s += "Channel_id " + str(channel_id)
        for i in range(len(self.data_buff)):
            s += hex(self.data_buff[i]) + "\n"
        s += "\n"
        self.file = open("dump_error.txt","a+")
        self.file.write(s)
        self.file.close()

    def check_buffer(self, channel_id, frame_adder, nof_tpms):
        n = channel_id
        exp_val = 0
        if frame_adder == 0:
            for m in range(4):
                exp_val = exp_val | ((self.exp_data[n][m] & 0xFF) << m*8)
            for i in range(len(self.data_buff)):
                rcv_val = self.data_buff[i]
                if rcv_val != exp_val:
                    print("Error in logical channel " + str(n))
                    print("Sample Index: " + str(i))
                    print("Error - Exp: " + hex(exp_val) + " Rcv " + hex(rcv_val)) #+ hex((rcv_val >> 24) & 0xFF) + " " + hex((rcv_val >> 16) & 0xFF) + " " + hex((rcv_val >> 8) & 0xFF) + " " + hex((rcv_val >> 0) & 0xFF)
                    input("Press a key...")
                    break
        else:
            exp_val = [0] * 4
            first_val = self.data_buff[0]
            found = 0
            dump_done = 0
            data_mask = (nof_tpms - 1)
            for n in range(3):
                data_mask = (data_mask << 8) + (nof_tpms-1)
            for i in range(len(self.data_buff)):
                rcv_val = self.data_buff[i]
                if (rcv_val & data_mask) != 0:
                        print("Data Error in logical channel " + str(channel_id))
                        print("Sample Index: " + str(i))
                        print("Error: "  + hex(rcv_val))
                        for n in range(16):
                            print(hex(self.data_buff[i-8+n]))
                            input("Press a key...")
                if rcv_val != first_val:
                    if found == 0:
                        for m in range(4):
                            exp_val[m] = (first_val >> m*8) & 0xFF
                            exp_val[m] += nof_tpms
                            if exp_val[m] == 128:
                                exp_val[m] = 0
                        for m in range(4):
                            rcv_val8 = (rcv_val >> m*8) & 0xFF
                            if rcv_val8 != exp_val[m]:
                                print("Error in logical channel " + str(channel_id))
                                print("Sample Index: " + str(i+1))
                                print("Error - Exp: " + hex(first_val) + " Rcv " + hex((rcv_val >> 24) & 0xFF) + " " + hex((rcv_val >> 16) & 0xFF) + " " + hex((rcv_val >> 8) & 0xFF) + " " + hex((rcv_val >> 0) & 0xFF))
                                for  n in range(16):
                                    print(hex(self.data_buff[i-8+n]))
                                #input("Press a key...")
                                print()
                                if dump_done == 0:
                                    dump_done = 1
                                    self.dump(channel_id)
                                #break
                        if channel_id % 2 == 0:
                            frame_offset = self.frame_offset_0
                        else:
                            frame_offset = self.frame_offset_1

                        if frame_offset < 0:
                            frame_offset = i
                        else:
                            if frame_offset != i:
                                print("Frame Offset error in logical channel " + str(channel_id))
                                print("Sample Index: " + str(i))
                                print("Error - Exp: " + hex(first_val) + " Rcv " + hex((rcv_val >> 24) & 0xFF) + " " + hex((rcv_val >> 16) & 0xFF) + " " + hex((rcv_val >> 8) & 0xFF) + " " + hex((rcv_val >> 0) & 0xFF))
                                print("Expected frame offset " + str(frame_offset))
                                print()
                                if channel_id % 2 == 0:
                                    self.frame_offset_error_0 += 1
                                else:
                                    self.frame_offset_error_1 += 1
                                input("Press a key...")
                                #break
                                if dump_done == 0:
                                    dump_done = 1
                                    self.dump(channel_id)
                        first_val = rcv_val
                        frame_offset = i

                        if channel_id % 2 == 0:
                            self.frame_offset_0 = frame_offset
                        else:
                            self.frame_offset_1 = frame_offset
                    else:
                        print("Multiple Frame Offset error in logical channel " + str(n))
                        print("Sample Index: " + str(i))
                        print("Error - Exp: " + hex(first_val) + " Rcv " + hex((rcv_val >> 24) & 0xFF) + " " + hex((rcv_val >> 16) & 0xFF) + " " + hex((rcv_val >> 8) & 0xFF) + " " + hex((rcv_val >> 0) & 0xFF))
                        print("Expected frame offset " + str(frame_offset))
                        input("Press a key...")
                        print()
                        if dump_done == 0:
                            dump_done = 1
                            self.dump(channel_id)
                        #break

        self.processed_frame += 1
        if self.processed_frame % 1000 == 0:
            print("Frames processed with no errors: " + str(self.processed_frame))
            #if self.frame_offset >= 0:
            print("Frame offset 0: " + str(self.frame_offset_0))
            print("Frame offset 1: " + str(self.frame_offset_1))
            print("Frame offset error 0: " + str(self.frame_offset_error_0))
            print("Frame offset error 1: " + str(self.frame_offset_error_1))

    def run_test(self, nof_tpms, pattern, adders, frame_adder, first_channel, nof_packets):
        self.make_exp_data(nof_tpms, pattern, adders)
        checked = 0

        # packet_burst = nof_packets
        # cap = pyshark.LiveCapture(interface='eth3', bpf_filter='udp port 4660')

        # while True:
        #     for packet in cap.sniff_continuously(packet_count=packet_burst):
        #         _pkt = binascii.unhexlify(packet.data.data)
        #         #print(_pkt[0:128])
        #         #input()
        #
        #         if len(_pkt) > 8192:
        #             self.spead_header_decode(_pkt, first_channel)
        #             self.data_buff = unpack('I' * (self.payload_length / 4), _pkt[self.offset:])
        #             self.check_buffer(self.logical_channel_id, frame_adder)
        #             checked += 1
        #         # print(len(_pkt))
        #         # print(checked)
        #         if checked == nof_packets and nof_packets > 0:
        #             return


        while True:
            while True:
                try:
                    _pkt, _addr = self.sock.recvfrom(1024*10)
                    # print("pkt")
                    # print(_pkt[0:128])
                    break
                except socket.timeout:
                    print("socket timeout!")
            if len(_pkt) > 8192:
                self.spead_header_decode(_pkt, first_channel)
                self.data_buff = unpack('I' * int(self.payload_length / 4), _pkt[self.offset:])
                self.check_buffer(self.logical_channel_id, frame_adder, nof_tpms)
                checked += 1
            if checked == nof_packets and nof_packets > 0:
                break


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("-p",
                      dest="port",
                      default="4660",
                      help="UDP port")
    parser.add_option("-t",
                      dest="tpm_num",
                      default="2",
                      help="Number of TPMs in the station beamformer")

    (options, args) = parser.parse_args()


    pattern = range(1024)
    adders = [0, 1]
    nof_packets = -1

    spead_rx_inst = spead_rx(int(options.port))
    spead_rx_inst.run_test(int(options.tpm_num), pattern, adders, nof_packets)
