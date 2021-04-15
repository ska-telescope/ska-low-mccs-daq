import sys
import socket
import numpy as np
import multiprocessing
from struct import *
from builtins import input
from time import perf_counter
from optparse import OptionParser
from multiprocessing import Process, Pool

nof_packets = 16384
sample_per_pkt = 8192 // (2 * 2 * 8)
nof_processes = 8
pkt_buff = bytearray(16384 * 16384)
timestamp_idx_list = []

def beamformer(id):
    global nof_processes
    global sample_per_pkt
    global pkt_buff
    global timestamp_idx_list

    power = np.zeros(2, dtype=np.uint64)
    nof_saturation = np.zeros(2, dtype=np.uint64)
    nof_sample = np.zeros(2, dtype=np.uint64)

    nof_tpm = len(timestamp_idx_list[0]) // 2

    for n, pkt_idx_list in enumerate(timestamp_idx_list):
        if n % nof_processes == id:
            # print("%d %d" % (id, n))
            for sample_idx in range(sample_per_pkt):
                pkt_reassembled = []
                for i, pkt_idx in enumerate(pkt_idx_list):
                    pkt_reassembled += unpack('b' * 32,
                                              pkt_buff[pkt_idx + sample_idx * 32: pkt_idx + (sample_idx + 1) * 32])
                sum = np.zeros(4, dtype=np.int64)
                for p in range(4):
                    for k in range(p, 32 * 2 * nof_tpm, 4):
                        if int(pkt_reassembled[k]) == -128:
                            sum[p] = -2 ** 31
                        else:
                            sum[p] += int(pkt_reassembled[k])
                for p in range(2):
                    if sum[2 * p] == -2 ** 31 or sum[2 * p + 1] == -2 ** 31:
                        nof_saturation[p] += 1
                    else:
                        power[p] += sum[2 * p] ** 2 + sum[2 * p + 1] ** 2
                        nof_sample[p] += 1

    return power[0], power[1], nof_saturation[0], nof_saturation[1], nof_sample[0], nof_sample[1]

class SpeadRxBeamPowerOffline(Process):
    def __init__(self, port, nof_tpm=16, eth_if="enp216s0f0", *args, **kwargs):
        global nof_processes
        global sample_per_pkt
        global pkt_buff
        global timestamp_idx_list

        self.port = port
        self.nof_tpm = nof_tpm
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
        self.lmc_capture_mode = 0
        self.lmc_fpga_id = -1
        self.lmc_tpm_id = -1
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
                    return

    def spead_header_decode(self, pkt, first_channel = -1):
        items = unpack('>' + 'Q'*9, pkt[0:8*9])
        self.is_spead = 0
        is_lmc_packet = 0
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
            elif id == 0xA004 and idx == 5:
                self.lmc_capture_mode = val
                is_lmc_packet = 1
            elif id == 0xA002 and idx == 6:
                self.lmc_channel_info = val
            elif id == 0xA001 and idx == 7:
                self.lmc_tpm_info = val
                self.lmc_tpm_id = (self.lmc_tpm_info & 0xF00000000) >> 32
                self.lmc_fpga_id = (self.lmc_tpm_info & 0xF) >> 0
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
        return is_lmc_packet and self.is_spead

    def process_buffer(self):

        global nof_packets
        global pkt_buff
        global nof_processes
        global timestamp_idx_list

        timestamp_idx_dict = {}
        pkt_buffer_idx = 0
        nof_full_buff = 0
        for n in range(nof_packets):
            # print(n)
            if self.spead_header_decode(pkt_buff[pkt_buffer_idx+42:pkt_buffer_idx+42+72]):
                # print(self.lmc_capture_mode)
                # print(self.lmc_tpm_id)

                if self.lmc_capture_mode == 5:
                    pkt_buffer_idx_offset = pkt_buffer_idx + 42 + 72
                    if self.timestamp not in list(timestamp_idx_dict.keys()):
                        timestamp_idx_dict[self.timestamp] = [pkt_buffer_idx_offset]
                    else:
                        l = timestamp_idx_dict[self.timestamp]
                        l.append(pkt_buffer_idx_offset)
                        timestamp_idx_dict[self.timestamp] = l
            pkt_buffer_idx += 16384

        timestamp_idx_list = []
        for t, ts in enumerate(list(timestamp_idx_dict)):
            pkt_idx_list = timestamp_idx_dict[ts]
            if len(pkt_idx_list) == 2 * self.nof_tpm:
                timestamp_idx_list.append(pkt_idx_list)
                nof_full_buff += 1

        print(nof_full_buff)


        t1_start = perf_counter()
        with Pool(nof_processes) as p:
             beam_list = p.map(beamformer, list(range(nof_processes)))
        # beam_list = beamformer(0)
        t1_stop = perf_counter()
        elapsed = t1_stop - t1_start
        print(elapsed)

        if np.ndim(beam_list) > 1:
            beam = np.sum(np.asarray(beam_list), axis=0)
        else:
            beam = beam_list

        power_accu_0 = beam[0]
        power_accu_1 = beam[1]
        nof_saturation_0 = beam[2]
        nof_saturation_1 = beam[3]
        nof_sample_0 = beam[4]
        nof_sample_1 = beam[5]

        power_0 = power_accu_0 / nof_sample_0
        power_1 = power_accu_1 / nof_sample_1
        power_0_db = 10 * np.log10(power_0)
        power_1_db = 10 * np.log10(power_1)

        # print(nof_full_buff)
        # print(nof_samples)
        # print(nof_saturation_0)
        # print(nof_saturation_1)
        # print(nof_sample_0)
        # print(nof_sample_1)
        # print(power_0_db)
        # print(power_1_db)
        return [power_0_db, power_1_db] #, nof_saturation_0, nof_saturation_1, nof_sample_0, nof_sample_1

    def get_power(self):
        global pkt_buff
        global nof_packets
        while True:
            pkt_buff_ptr = memoryview(pkt_buff)
            pkt_buff_idx = 0
            for n in range(nof_packets):
                self.recv2(pkt_buff_ptr)
                pkt_buff_idx += 16384
                pkt_buff_ptr = pkt_buff_ptr[16384:]
            print("Got buffer")
            return self.process_buffer()


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("-p",
                      dest="port",
                      default="4660",
                      help="UDP port [Default: 4660]")
    parser.add_option("-t",
                      dest="nof_tpm",
                      default="2",
                      help="Number of TPMs [Default: 2]")
    # parser.add_option("-n",
    #                   dest="nof_samples",
    #                   default="131072",
    #                   help="Number of samples to integrate")
    parser.add_option("-i",
                      dest="eth_if",
                      default="eth0",
                      help="Ethrnet Interface")

    (options, args) = parser.parse_args()

    spead_rx_inst = SpeadRxBeamPowerOffline(int(options.port), int(options.nof_tpm), options.eth_if)
    #x, y = spead_rx_inst.get_power(int(options.nof_samples), int(options.logic_channel))
    while True:
        print(spead_rx_inst.get_power())
    #print(x, y)
