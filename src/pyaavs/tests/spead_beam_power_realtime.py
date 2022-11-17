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
realtime_timestamp_idx_list = []

def power(id):
    global realtime_nof_processes
    global realtime_pkt_buff
    global realtime_timestamp_idx_list

    power = np.zeros(2, dtype=np.uint64)
    nof_saturation = np.zeros(2, dtype=np.uint64)
    nof_sample = np.zeros(2, dtype=np.uint64)

    for n, pkt_idx in enumerate(realtime_timestamp_idx_list):
        if n % realtime_nof_processes == id:
            # print("%d %d" % (id, n))
            pkt_reassembled = unpack('b' * 8192, realtime_pkt_buff[pkt_idx : pkt_idx + 8192])
            for k in range(0, 8192, 4):
                if int(pkt_reassembled[k]) == -128 or int(pkt_reassembled[k+1]) == -128 or int(pkt_reassembled[k+2]) == -128 or int(pkt_reassembled[k+3]) == -128:
                    nof_saturation[0] += 1
                    nof_saturation[1] += 1
                else:
                    power[0] += int(pkt_reassembled[k+0]) ** 2 + int(pkt_reassembled[k+1]) ** 2
                    power[1] += int(pkt_reassembled[k+2]) ** 2 + int(pkt_reassembled[k+3]) ** 2
                    nof_sample[0] += 1
                    nof_sample[1] += 1

    return power[0], power[1], nof_saturation[0], nof_saturation[1], nof_sample[0], nof_sample[1]

class SpeadRxBeamPowerRealtime(Process):
    def __init__(self, port, eth_if="eth2", *args, **kwargs):
        self.port = port
        self.raw_socket = True
        self.channel_id = 0

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
                    return nbytes

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

    def process_buffer(self, max_packets, contiguous_packets=0):
        global realtime_pkt_buff
        global realtime_timestamp_idx_list

        realtime_timestamp_idx_list = []
        pkt_buffer_idx = 0
        nof_full_buff = 0
        contiguous_packets_count = 0
        expected_packet_counter = None
        for n in range(max_packets):
            # print(n)
            if self.spead_header_decode(realtime_pkt_buff[pkt_buffer_idx + 42:pkt_buffer_idx + 42 + 72]):
                # print(self.lmc_capture_mode)
                # print(self.lmc_tpm_id)

                if self.logical_channel_id == self.channel_id:
                    pkt_buffer_idx_offset = pkt_buffer_idx + 42 + 72
                    realtime_timestamp_idx_list.append(pkt_buffer_idx_offset)
                    nof_full_buff += 1

                    if contiguous_packets > 0:
                        if expected_packet_counter is None:
                            expected_packet_counter = self.packet_counter + 1
                            expected_packet_counter = expected_packet_counter & 0xFFFFFFFF
                            contiguous_packets_count = 1
                        elif self.packet_counter == expected_packet_counter:
                            expected_packet_counter = self.packet_counter + 1
                            expected_packet_counter = expected_packet_counter & 0xFFFFFFFF
                            contiguous_packets_count += 1
                            if contiguous_packets_count >= contiguous_packets:
                                break
                        else:
                            if contiguous_packets_count < contiguous_packets:
                                expected_packet_counter = self.packet_counter + 1
                                expected_packet_counter = expected_packet_counter & 0xFFFFFFFF
                                contiguous_packets_count = 1
                                realtime_timestamp_idx_list = [pkt_buffer_idx]

            pkt_buffer_idx += 16384

        return contiguous_packets_count

    def calculate_power(self):

        global realtime_pkt_buff
        global realtime_nof_processes
        global realtime_timestamp_idx_list

        t1_start = perf_counter()
        with Pool(realtime_nof_processes) as p:
             beam_list = p.map(power, list(range(realtime_nof_processes)))
        # beam_list = beamformer(0)
        t1_stop = perf_counter()
        elapsed = t1_stop - t1_start
        # print(elapsed)

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
        return [power_0_db, power_1_db, nof_saturation_0, nof_saturation_1, nof_sample_0, nof_sample_1]

    def get_power(self, channel_id, max_packets=4096):
        global realtime_pkt_buff

        self.channel_id = channel_id
        while True:
            pkt_buff_ptr = memoryview(realtime_pkt_buff)
            pkt_buff_idx = 0
            for n in range(max_packets):
                self.recv2(pkt_buff_ptr)
                pkt_buff_idx += 16384
                pkt_buff_ptr = pkt_buff_ptr[16384:]
            self.process_buffer(max_packets)
            return self.calculate_power()

    def get_data(self, channel_id, max_packets=4096, contiguous_packets=128):
        global realtime_pkt_buff
        global realtime_timestamp_idx_list

        self.channel_id = channel_id
        while True:
            pkt_buff_ptr = memoryview(realtime_pkt_buff)
            pkt_buff_idx = 0
            for n in range(max_packets):
                self.recv2(pkt_buff_ptr)
                pkt_buff_idx += 16384
                pkt_buff_ptr = pkt_buff_ptr[16384:]
            packets = self.process_buffer(max_packets, contiguous_packets)
            if packets >= contiguous_packets:
                break

        nof_samples = 2048 * len(realtime_timestamp_idx_list)
        samples = np.zeros((4, nof_samples), dtype=np.int8)

        for n, pkt_idx in enumerate(realtime_timestamp_idx_list):
            # print("%d %d" % (id, n))
            pkt_reassembled = unpack('b' * 8192, realtime_pkt_buff[pkt_idx: pkt_idx + 8192])
            for k in range(0, 8192, 4):
                samples[0, k // 4] = pkt_reassembled[k]
                samples[1, k // 4] = pkt_reassembled[k + 1]
                samples[2, k // 4] = pkt_reassembled[k + 2]
                samples[3, k // 4] = pkt_reassembled[k + 3]
        print(samples[0, :128])
        return samples

    def get_data_rate(self, bytes):
        global realtime_pkt_buff

        pkt_buff_ptr = memoryview(realtime_pkt_buff)
        self.recv2(pkt_buff_ptr)
        nbytes = 0
        t1_start = perf_counter()
        while True:
            nbytes += self.recv2(pkt_buff_ptr)
            if nbytes > bytes:
                t1_stop = perf_counter()
                data_rate = nbytes / (t1_stop - t1_start)
                return data_rate


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

    spead_rx_inst = SpeadRxBeamPowerRealtime(int(options.port), options.eth_if)
    #x, y = spead_rx_inst.get_power(int(options.nof_samples), int(options.logic_channel))
    while True:
        print(spead_rx_inst.get_power(0))
    #print(x, y)
