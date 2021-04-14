import sys
import socket
import numpy as np
import multiprocessing
from struct import *
from builtins import input
from time import perf_counter
from optparse import OptionParser
from multiprocessing import Process, Pool

nof_processes = 8
raw_socket = True
timestamp_idx_dict = {}
sample_per_pkt = 8192 // (2 * 2 * 8)
pkt_buff = bytearray(16384 * 16384)



def beamformer(id):
    global timestamp_idx_dict
    global pkt_buff

    power_accu_0 = 0
    power_accu_1 = 0
    nof_saturation_0 = 0
    nof_saturation_1 = 0
    for t, ts in enumerate(list(timestamp_idx_dict)):
        if t % id == 0:
            pkt_idx_list = timestamp_idx_dict[ts]
            if len(pkt_idx_list) == 32:
                for sample_idx in range(sample_per_pkt):
                    sum_0_re = 0
                    sum_0_im = 0
                    sum_1_re = 0
                    sum_1_im = 0
                    sample_pow_0 = 0
                    sample_pow_1 = 0
                    for pkt_idx in pkt_idx_list:
                        pkt_data = unpack('b' * 32, pkt_buff[pkt_idx + sample_idx * 32: pkt_idx + (sample_idx + 1) * 32])
                        for k in range(0, 32, 4):
                            if pkt_data[k] != 0x80 and pkt_data[k + 1] != 0x80:
                                sum_0_re += pkt_data[k]
                                sum_0_im += pkt_data[k + 1]
                            else:
                                nof_saturation_0 += 1
                        for k in range(2, 32, 4):
                            if pkt_data[k] != 0x80 and pkt_data[k + 1] != 0x80:
                                sum_1_re += pkt_data[k]
                                sum_1_im += pkt_data[k + 1]
                            else:
                                nof_saturation_1 += 1
                        # for k in range(0, 32, 4):
                        #     sum_0_re += pkt_data[k]
                        # for k in range(1, 32, 4):
                        #     sum_0_im += pkt_data[k]
                        # for k in range(2, 32, 4):
                        #     sum_1_re += pkt_data[k]
                        # for k in range(3, 32, 4):
                        #     sum_1_im += pkt_data[k]
                    sample_pow_0 += sum_0_re ** 2 + sum_0_im ** 2
                    sample_pow_1 += sum_1_re ** 2 + sum_1_im ** 2
                    power_accu_0 += sample_pow_0
                    power_accu_1 += sample_pow_1
    return power_accu_0, power_accu_1, nof_saturation_0, nof_saturation_1


class SpeadRxBeamPowerOffline(Process):
    def __init__(self, port, eth_if="enp216s0f0", *args, **kwargs):
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

    @property
    def process_buffer(self):

        global timestamp_idx_dict
        global pkt_buff

        timestamp_idx_dict = {}
        pkt_buffer_idx = 0
        nof_full_buff = 0
        for n in range(16384):
            if self.spead_header_decode(pkt_buff[pkt_buffer_idx+42:pkt_buffer_idx+42+72]):
                #print(self.lmc_capture_mode)
                #print(self.lmc_tpm_id)
                #print
                if self.lmc_capture_mode == 5:
                    pkt_buffer_idx_offset = pkt_buffer_idx + 42 + 72
                    if self.timestamp not in list(timestamp_idx_dict.keys()):
                        timestamp_idx_dict[self.timestamp] = [pkt_buffer_idx_offset]
                    else:
                        l = timestamp_idx_dict[self.timestamp]
                        l.append(pkt_buffer_idx_offset)
                        timestamp_idx_dict[self.timestamp] = l
                        if len(l) == 32:
                            nof_full_buff += 1
            pkt_buffer_idx += 16384
        nof_samples = nof_full_buff * sample_per_pkt

        t1_start = perf_counter()

        with Pool(nof_processes) as p:
            beam_list = p.map(beamformer, list(range(nof_processes)))
        beam = np.sum(np.asarray(beam_list), range(4))

        power_accu_0 = beam[0]
        power_accu_1 = beam[1]
        nof_saturation_0 = beam[2]
        nof_saturation_1 = beam[3]

        # power_accu_0 = 0
        # power_accu_1 = 0
        # nof_saturation_0 = 0
        # nof_saturation_1 = 0
        # for t, ts in enumerate(list(timestamp_idx_dict)):
        #     pkt_idx_list = timestamp_idx_dict[ts]
        #     if len(pkt_idx_list) == 32:
        #         for sample_idx in range(sample_per_pkt):
        #             sum_0_re = 0
        #             sum_0_im = 0
        #             sum_1_re = 0
        #             sum_1_im = 0
        #             sample_pow_0 = 0
        #             sample_pow_1 = 0
        #             for pkt_idx in pkt_idx_list:
        #                 pkt_data = unpack('b' * 32, pkt_buff[pkt_idx + sample_idx * 32: pkt_idx + (sample_idx + 1) * 32])
        #                 for k in range(0, 32, 4):
        #                     if pkt_data[k] != 0x80 and pkt_data[k+1] != 0x80:
        #                         sum_0_re += pkt_data[k]
        #                         sum_0_im += pkt_data[k+1]
        #                     else:
        #                         nof_saturation_0 += 1
        #                 for k in range(2, 32, 4):
        #                     if pkt_data[k] != 0x80 and pkt_data[k+1] != 0x80:
        #                         sum_1_re += pkt_data[k]
        #                         sum_1_im += pkt_data[k+1]
        #                     else:
        #                         nof_saturation_1 += 1
        #                 # for k in range(0, 32, 4):
        #                 #     sum_0_re += pkt_data[k]
        #                 # for k in range(1, 32, 4):
        #                 #     sum_0_im += pkt_data[k]
        #                 # for k in range(2, 32, 4):
        #                 #     sum_1_re += pkt_data[k]
        #                 # for k in range(3, 32, 4):
        #                 #     sum_1_im += pkt_data[k]
        #             sample_pow_0 += sum_0_re ** 2 + sum_0_im ** 2
        #             sample_pow_1 += sum_1_re ** 2 + sum_1_im ** 2
        #             power_accu_0 += sample_pow_0
        #             power_accu_1 += sample_pow_1
        t1_stop = perf_counter()

        elapsed = t1_stop - t1_start

        power_0 = power_accu_0 / nof_saturation_0
        power_1 = power_accu_1 / nof_saturation_1
        power_0_db = 10 * np.log10(power_0)
        power_1_db = 10 * np.log10(power_1)

        print(elapsed)
        print(nof_full_buff)
        print(nof_samples)
        print(nof_saturation_0)
        print(nof_saturation_1)
        print(power_0_db)
        print(power_1_db)
        return power_0_db, power_1_db, nof_saturation_0, nof_saturation_1

    def get_power(self):
        global pkt_buff
        while True:
            pkt_buff_ptr = memoryview(pkt_buff)
            pkt_buff_idx = 0
            for n in range(16384):
                self.recv2(pkt_buff_ptr)
                pkt_buff_idx += 16384
                pkt_buff_ptr = pkt_buff_ptr[16384:]
            return self.process_buffer


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
    parser.add_option("-i",
                      dest="eth_if",
                      default="eth0",
                      help="Ethrnet Interface")

    (options, args) = parser.parse_args()

    spead_rx_inst = SpeadRxBeamPowerOffline(int(options.port), options.eth_if)
    #x, y = spead_rx_inst.get_power(int(options.nof_samples), int(options.logic_channel))
    while True:
        print(spead_rx_inst.get_power())
    #print(x, y)
