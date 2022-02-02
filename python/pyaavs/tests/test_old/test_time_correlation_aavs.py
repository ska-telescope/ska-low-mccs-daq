# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile import Tile

# Import required persisters
from pydaq.persisters.aavs_file import FileModes
from pydaq.persisters.raw import RawFormatFileManager
from pydaq.persisters.channel import ChannelFormatFileManager
from pydaq.persisters.beam import BeamFormatFileManager
from pydaq.persisters import *

from sys import stdout
import numpy as np
import os.path
import logging
import random
import math
import time
import sys

temp_dir = "./temp_daq_test"
data_received = False
beam_int_data_received = False
channel_int_data_received = False
test_pattern = range(1024)
test_adders = range(32)
channel_integration_length = 0
channel_accumulator_width = 0
channel_round_bits = 0
delays = []
max_idx = np.zeros((32, 64),dtype='int')

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


def integrated_sample_calc(data_re, data_im, integration_length, round_bits, max_width):
    power = data_re**2 + data_im**2
    accumulator = power * integration_length
    round = s_round(accumulator, round_bits, max_width)
    return round


# Custom function to compute the absoule of the custom data type
def complex_f(value):
    return math.sqrt((value[0] ** 2) + (value[1] ** 2))
complex_func = np.vectorize(complex_f)


def signed(data, bits=8, ext_bits=8):
    data = data % 2**bits
    if data >= 2**(bits-1):
        data -= 2**bits
    if ext_bits > bits:
        if data == -2**(bits-1):
            data = -2**(ext_bits-1)
    return data


def channelize_pattern(pattern):
        """ Change the frequency channel order to match che channelizer output
        :param pattern: pattern buffer, frequency channel in increasing order
        """
        tmp = [0]*len(pattern)
        half = len(pattern) / 2
        for n in range(half / 2):
            tmp[4*n] = pattern[2*n]
            tmp[4*n+1] = pattern[2*n+1]
            tmp[4*n+2] = pattern[-(1+2*n+1)]
            tmp[4*n+3] = pattern[-(1+2*n)]
        return tmp


def set_pattern(tile, stage, pattern, adders, start):
    print("Setting " + stage + " data pattern")
    signal_adder = []
    for n in range(32):
        signal_adder += [adders[n]]*4

    for i in range(2):
        tile.tpm.tpm_pattern_generator[i].set_pattern(pattern, stage)
        tile.tpm.tpm_pattern_generator[i].set_signal_adder(signal_adder[64*i:64*(i+1)], stage)
        tile['fpga1.pattern_gen.beamf_left_shift'] = 4
        tile['fpga2.pattern_gen.beamf_left_shift'] = 4
        if start:
            tile.tpm.tpm_pattern_generator[i].start_pattern(stage)

def set_delay(tile, delay):
    tile.tpm.test_generator[0].set_delay(delay[0:16])
    tile.tpm.test_generator[1].set_delay(delay[16:32])

def correlate_raw(data):
    global delays
    
    print(data[0, 0, 0:8])
    print(data[1, 0, 0:8])
    ref = np.array(data[0, 0, 0:2048],dtype='int')
    for a in range(16):
        for p in range(1):
            b = np.array(data[a, p, 0:2048],dtype='int')
            correlation = np.correlate(ref, b,'full')
            max = correlation[-2047-16:-2047+16].max()
            idx = np.where(correlation[-2047-16:-2047+16] == max)
            if len(idx) == 1 and idx[0] in range(128):
                idx = idx[0]
                max_idx[a][int(idx)] = max_idx[a][int(idx)]+1
            print(max, idx)


def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    if mode == "burst_raw":
        raw_file = RawFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = raw_file.read_data(antennas=range(16),  # List of channels to read (not use in raw case)
                                           polarizations=[0, 1],
                                           n_samples=32*1024)
        print("Raw data: {}".format(data.shape))
        correlate_raw(data)

    data_received = True



def remove_files():
    # create temp directory
    if not os.path.exists(temp_dir):
        print("Creating temp folder: " + temp_dir)
        os.system("mkdir " + temp_dir)
    os.system("rm " + temp_dir + "/*.hdf5")

if __name__ == "__main__":


    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser.add_option("--port", action="store", dest="port",
                      type="int", default="10000", help="Port [default: 10000]")
    parser.add_option("--tpm_ip", action="store", dest="tpm_ip",
                      default="10.0.10.3", help="IP [default: 10.0.10.3]")
    (conf, args) = parser.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    str_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(str_format)
    log.addHandler(ch)
    remove_files()

    # Connect to tile (and do whatever is required)
    tile = Tile(ip=conf.tpm_ip, port=conf.port)
    tile.connect()

    #t0 = tile.tpm["fpga1.pps_manager.timestamp_read_val"]
    #tile.tpm.test_generator[0].enable_prdg(0.2, t0+256)
    #tile.tpm.test_generator[1].enable_prdg(0.2, t0+256)
    #tile.tpm.test_generator[0].channel_select(0xFFFF)
    #tile.tpm.test_generator[1].channel_select(0xFFFF)
    time.sleep(0.2)


    # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
    # I'll change this to make it nicer
    daq_config = {
                  'receiver_interface': 'eth3',  # CHANGE THIS if required
                  'directory': temp_dir,  # CHANGE THIS if required
                  'nof_beam_channels': 384,
                  'nof_beam_samples': 32
                  }

    # Configure the DAQ receiver and start receiving data
    daq.populate_configuration(daq_config)
    daq.initialise_daq()

    # Start whichever consumer is required and provide callback
    daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    #
    # raw data synchronised
    #
    remove_files()

    delays = [0] * 32
    set_delay(tile,delays)
    
    while True:
        data_received = False
        # Send data from tile
        tile.send_raw_data_synchronised()
        # Wait for data to be received
        while not data_received:
            time.sleep(0.1)
        for a in range(16):
            for i in range(31):
                sys.stdout.write('{:3d}'.format(int(max_idx[a][i])) + " ")
            print()

    #delays = [random.randrange(0,16,1) for x in range(32)]
    #delays[0] = 0
    #set_delay(tile,delays)

    data_received = False
    # Send data from tile
    tile.send_raw_data_synchronised()
    # Wait for data to be received
    while not data_received:
        time.sleep(0.1)

    print(delays)

    daq.stop_daq()

