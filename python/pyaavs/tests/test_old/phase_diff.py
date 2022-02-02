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
import test_functions as tf
from datetime import datetime
import numpy as np
import os.path
import logging
import random
import math
import time

temp_dir = "./temp_daq_test"
data = []
data_received = False


def phase_diff_calc(ref, test):
    a0 = np.angle(ref, deg=True)
    a1 = np.angle(test, deg=True)
    phase_diff = a1 - a0
    return phase_diff


def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received
    global data

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    if mode == "burst_channel":
        channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = channel_file.read_data(channels=range(512),  # List of channels to read (not use in raw case)
                                               antennas=range(16),
                                               polarizations=[0, 1],
                                               n_samples=128)
        print("Channel data: {}".format(data.shape))

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
    parser.add_option("-c", "--channel", action="store", dest="channel",
                      default="64", help="Frequency channel [default: 64]")
    parser.add_option("-r", "--reference_antenna", action="store", dest="reference_antenna",
                      default="0", help="Reference antenna [default: 0]")
    parser.add_option("-x", "--reference_pol", action="store", dest="reference_pol",
                      default="0", help="Test polarisation  [default: 0]")
    parser.add_option("-i", "--test_antenna", action="store", dest="test_antenna",
                      default="0", help="Test antenna [default: 1]")
    parser.add_option("-y", "--test_pol", action="store", dest="test_pol",
                      default="1", help="Test polarisation [default: 0]")
    parser.add_option("-p", "--polling_time", action="store", dest="polling_time",
                      default="1", help="Polling time in seconds [default: 1]")
    parser.add_option("--test_mode", action="store_true", dest="test_mode",
                      default=False, help="Enable test mode")
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

    # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
    # I'll change this to make it nicer
    daq_config = {
                  'receiver_interface': 'eth3',  # CHANGE THIS if required
                  'directory': temp_dir,  # CHANGE THIS if required
                  'nof_beam_channels': 384,
                  'nof_beam_samples': 32,
                  'receiver_frame_size': 9000
                  }

    # Configure the DAQ receiver and start receiving data
    daq.populate_configuration(daq_config)
    daq.initialise_daq()

    # Start whichever consumer is required and provide callback
    # daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    daq.start_channel_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    # daq.start_beam_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required


    tf.stop_pattern(tile, "all")
    tile['fpga1.jesd204_if.regfile_channel_disable'] = 0x0000
    tile['fpga2.jesd204_if.regfile_channel_disable'] = 0x0000
    tile.test_generator_disable_tone(0)
    tile.test_generator_disable_tone(1)
    tile.test_generator_set_noise(0.0)
    tile.test_generator_input_select(0x0)
    tf.set_delay(tile, [0]*32)

    if conf.test_mode:
        tile.test_generator_set_tone(0, int(conf.channel) * 400e6 / 512, 1.0)
        tile.test_generator_input_select(0xFFFFFFFF)

    reference_antenna = int(conf.reference_antenna)
    reference_pol = int(conf.reference_pol)
    test_antenna = int(conf.test_antenna)
    test_pol = int(conf.test_pol)
    channel = int(conf.channel)
    polling_time = float(conf.polling_time)
    iter = 0

    time_now = str((datetime.utcnow() - datetime(1970, 1, 1)).total_seconds())
    time_now = time_now.replace(".", "_")
    file_name = "phase_diff_log_channel_" + str(channel) + "_" + time_now + ".log"
    f = open(file_name, "w")
    f.write("")
    f.close()

    tile['fpga1.lmc_gen.readout_channel_ptr.channel'] = channel
    tile['fpga2.lmc_gen.readout_channel_ptr.channel'] = channel
    if reference_antenna < 8:
        tile['fpga1.lmc_gen.readout_channel_ptr.input_0'] = 2*reference_antenna + reference_pol
        reference_fpga = 'fpga1'
    else:
        tile['fpga2.lmc_gen.readout_channel_ptr.input_0'] = 2*(reference_antenna-8) + reference_pol
        reference_fpga = 'fpga2'
    if test_antenna < 8:
        tile['fpga1.lmc_gen.readout_channel_ptr.input_1'] = 2*test_antenna + test_pol
        test_fpga = 'fpga1'
    else:
        tile['fpga2.lmc_gen.readout_channel_ptr.input_1'] = 2*(test_antenna-8) + test_pol
        test_fpga = 'fpga2'

    print("Channel " + str(channel))
    time_prev = datetime.now()
    while True:

        time_this = datetime.now()
        time_diff = time_this - time_prev
        time_sec = time_diff.total_seconds()
        time_prev = time_this

        reference_value = tf.signed((tile['%s.lmc_gen.readout_input_0' % reference_fpga] & 0xFFF), 12) + tf.signed(((tile['%s.lmc_gen.readout_input_0' % reference_fpga] >> 12) & 0xFFF),12)*1j
        test_value =      tf.signed((tile['%s.lmc_gen.readout_input_1' % test_fpga]      & 0xFFF), 12) + tf.signed(((tile['%s.lmc_gen.readout_input_1' % test_fpga]      >> 12) & 0xFFF), 12)*1j

        print("R: " + str(reference_value))
        print("T: " + str(test_value))
        phase_diff = phase_diff_calc(reference_value, test_value)
        print("Reference Channel amplitude : " + str(abs(reference_value)))
        print("Test Channel amplitude      : " + str(abs(test_value)))
        print("Phase diff                  : " + str(phase_diff))

        f = open(file_name, "a")
        txt = str(time_sec)
        txt += " " + str(reference_value.real)
        txt += " " + str(reference_value.imag)
        txt += " " + str(test_value.real)
        txt += " " + str(test_value.imag)
        txt += " " + str(phase_diff) + "\n"
        f.write(txt)
        f.close()

        # remove_files()
        # data_received = False
        # tile.send_channelised_data(256)
        #
        # while not data_received:
        #     time.sleep(0.1)
        #
        # phase_diff = []
        # phase_ref = []
        # phase_test = []
        # ch, ant, pol, sam = data.shape
        # for i in range(sam):
        #     reference_value = data[channel, reference_antenna, reference_pol, i][0] + data[channel, reference_antenna, reference_pol, i][1]*1j
        #     test_value = data[channel, test_antenna, test_pol, i][0] + data[channel, test_antenna, test_pol, i][1]*1j
        #
        #     phase_diff.append(phase_diff_calc(reference_value, test_value))
        #     phase_ref.append(np.angle(reference_value))
        #     phase_test.append(np.angle(test_value))
        #
        #phase_diff_avg = np.average(phase_diff))
        #phase_diff_std = np.std(phase_diff))
        #print(str(sam) + " samples")
        #print("Reference Channel amplitude : " + str(abs(reference_value)))
        #print("Test Channel amplitude      : " + str(abs(test_value)))
        #print("Phase diff                  : " + str(phase_diff_avg))
        #print("Standard deviation          : " + str(phase_diff_std))
        #print

        if conf.test_mode:
            iter += 1
            if iter == 128:
                iter = 0
            tf.set_delay(tile, [0] + [iter]*31)

        time.sleep(polling_time)

        # f = open(file_name, "a")
        # txt = str(phase_diff_avg) + " " + str(phase_diff_std) + "\n"
        # f.write(txt)
        # f.close()

    daq.stop_daq()
