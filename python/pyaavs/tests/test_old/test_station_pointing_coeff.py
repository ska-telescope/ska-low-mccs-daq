# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.station import Station

# Import required persisters
from pydaq.persisters.aavs_file import FileModes
from pydaq.persisters.raw import RawFormatFileManager
from pydaq.persisters.channel import ChannelFormatFileManager
from pydaq.persisters.beam import BeamFormatFileManager
from pydaq.persisters import *

from builtins import input
from sys import stdout
import numpy as np
import os.path
import logging
import random
import math
import time

from spead_csp_pcap import *

temp_dir = "./temp_daq_test"
data_received = False
test_pattern = range(1024)
test_adders = range(32)
channel_integration_length = 0
channel_accumulator_width = 0
channel_round_bits = 0
raw_data_synchronised = 0


def set_pattern(tile, stage, pattern, adders, nof_tpms, start):
    print("Setting " + stage + " data pattern")
    for i in range(2):
        tile.tpm.tpm_pattern_generator[i].set_pattern(pattern, stage)
        tile.tpm.tpm_pattern_generator[i].set_signal_adder([adders[i]]*64, stage)
        tile['fpga1.pattern_gen.beamf_left_shift'] = 4 - int(math.log(nof_tpms, 2))
        tile['fpga2.pattern_gen.beamf_left_shift'] = 4 - int(math.log(nof_tpms, 2))
        if start:
            tile.tpm.tpm_pattern_generator[i].start_pattern(stage)

if __name__ == "__main__":

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    str_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(str_format)
    log.addHandler(ch)

     # Assign tiles
    station_tiles = ["10.0.10.3", "10.0.10.4", "10.0.10.6", "10.0.10.2"]
    nof_tpms = len(station_tiles)

    # Create station
    station = Station(0, port=10000, lmc_ip="10.0.10.100", lmc_port=4600)
    for t in station_tiles:
        station.add_tile(t)

    # Program and initialise tiles
    station.connect(initialise=False,
                    program=False,
                    bitfile="",
                    enable_test=False,
                    program_cpld=False,
                    channel_truncation=0,
                    beam_integration_time=-1,
                    channel_integration_time=-1,
                    start_beamformer=False,
                    use_teng=False)

    for n in range(nof_tpms):
        delay = [[0, 0]]*16
        station.tiles[n].set_pointing_delay(delay, 0)

    t0 = station.tiles[0].get_fpga_timestamp()
    for n in range(nof_tpms):
        station.tiles[n].load_pointing_delay(t0 + 64)

    # for n in range(nof_tpms):
    #     pattern = [0x23]*1024
    #     station.tiles[n].tpm.tpm_pattern_generator[0].set_pattern(pattern, "channel")
    #     station.tiles[n].tpm.tpm_pattern_generator[1].set_pattern(pattern, "channel")
    #     station.tiles[n].tpm.tpm_pattern_generator[0].clear_signal_adder("channel")
    #     station.tiles[n].tpm.tpm_pattern_generator[1].clear_signal_adder("channel")
    #     station.tiles[n].tpm.tpm_pattern_generator[0].start_pattern("channel")
    #     station.tiles[n].tpm.tpm_pattern_generator[1].start_pattern("channel")
    #     station.tiles[n].tpm.tpm_pattern_generator[0].stop_pattern("beamf")
    #     station.tiles[n].tpm.tpm_pattern_generator[1].stop_pattern("beamf")
    #     print("pattern set")

    station['fpga1.jesd204_if.regfile_channel_copy'] = 0xFFFF
    station['fpga2.jesd204_if.regfile_channel_copy'] = 0xFFFF
    for n in range(nof_tpms):
        station.tiles[n].tpm.tpm_pattern_generator[0].stop_pattern("channel")
        station.tiles[n].tpm.tpm_pattern_generator[1].stop_pattern("channel")
        station.tiles[n].tpm.tpm_pattern_generator[0].stop_pattern("beamf")
        station.tiles[n].tpm.tpm_pattern_generator[1].stop_pattern("beamf")
        print("pattern generator stopped")

    signal_frequency = 50e6
    start_frequency  = 50e6
    first_channel = start_frequency * 512 / 400e6
    logical_channel = signal_frequency * 512 / 400e6 - first_channel

    ip = ["10.1.10.", "10.2.10.", "10.5.10.", "10.6.10."]
    src_ip = ip[int(logical_channel) % 4] + station_tiles[nof_tpms-1].split(".")[-1]
    port = 4660

    for n in range(nof_tpms):
        station.tiles[n].set_csp_rounding(int(math.log(nof_tpms, 2)))
        station.tiles[n].tpm.test_generator[0].channel_select(0x0000)
        station.tiles[n].tpm.test_generator[1].channel_select(0x0000)
        station.tiles[n].tpm.test_generator[0].disable_prdg()
        station.tiles[n].tpm.test_generator[1].disable_prdg()

    points = 5
    duration = points+1

    for iter in range(2):
        file_name = "test_" + str(iter) + ".pcap"
        os.system("touch " + file_name)
        os.system("chmod 777 " + file_name)

        cmd = "tshark -i eth3 -f \"src " + src_ip + " and dst port " + str(port) + "\" -w " + file_name + " -a duration:" + str(duration) + " &"
        os.system(cmd)

        time.sleep(3)

        for i in range(5):

            for n in range(nof_tpms):
                delay = [[(5e-9)*i, 0]]*16
                station.tiles[n].set_pointing_delay(delay, 0)

            t0 = station.tiles[0].get_fpga_timestamp()
            for n in range(nof_tpms):
                if n == 0:
                    req_delay = 64 + iter
                else:
                    req_delay = 64
                station.tiles[n].load_pointing_delay(t0 + req_delay)

            t1 = station.tiles[0].current_tile_beamformer_frame()
            if t1 >= t0 + req_delay:
                print("Delay loading Time Error")
            else:
                print("Delay of " + str(delay[0][0]) + " ns applied at frame " + str(t0+64))

            time.sleep(1)

        # set delay to 0
        for n in range(nof_tpms):
            delay = [[0, 0]]*16
            station.tiles[n].set_pointing_delay(delay, 0)

        t0 = station.tiles[0].get_fpga_timestamp()
        for n in range(nof_tpms):
            station.tiles[n].load_pointing_delay(t0 + 64)

        time.sleep(2)

    # Process acquired data
    spead_0_inst = spead_rx()
    spead_0_inst.run_parser("test_0.pcap", logical_channel)
    spead_0_inst.process()
    time.sleep(0.01)

    spead_1_inst = spead_rx()
    spead_1_inst.run_parser("test_1.pcap", logical_channel)
    spead_1_inst.process()
    time.sleep(0.01)

    input("Press a key to close")
