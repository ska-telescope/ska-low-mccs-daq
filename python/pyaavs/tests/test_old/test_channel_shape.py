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
import numpy as np
import os.path
import logging
import random
import math
import time

temp_dir = "./temp_daq_test"
data = []
data_received = False


def filter_value(val):
    #if val == 2**32-1:
    #    val = 0
    if val > 0:
        pw = 10*np.log10(val)
    else:
        pw = 0
    return val, pw


def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received
    global data

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    if mode == "integrated_beam":
        beam_file = BeamFormatFileManager(root_path=os.path.dirname(filepath), daq_mode=FileDAQModes.Integrated)
        data, timestamps = beam_file.read_data(channels=range(384),
                                           polarizations=[0, 1],
                                           n_samples=1)
        print("Integrated beam data: {}".format(data.shape))
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
                      default="128", help="Frequency channel")
    parser.add_option("-s", "--sampling_points", action="store", dest="points",
                      default="100", help="Number of sampling points")
    parser.add_option("-f", "--frequency", action="store", dest="freq",
                      default="no", help="Frequency for single frequency acquisition")
    parser.add_option("-e", "--extension", action="store", dest="extension",
                      default="3", help="Extension")
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

    extension = float(conf.extension)
    channel = int(conf.channel)
    if channel not in range(512):
        print("Selected frequency channel not in range [0:511]")
        exit()

    if conf.freq != "no":
        points = 1
        lo_frequency = float(conf.freq)
        hi_frequency = lo_frequency
        frequency_adder = 1.0
        channel = int(lo_frequency / 400e6*512+0.5)
        print(channel)
    else:
        points = int(conf.points)
        channel_width = 400e6 / 512
        test_width = extension * channel_width
        center_freq = 400e6 / 512 * channel
        lo_frequency = center_freq - test_width / 2
        if lo_frequency < 0.0:
            lo_frequency = 0.0
        hi_frequency = center_freq + test_width / 2
        if hi_frequency > 400e6:
            hi_frequency = 400e6
        frequency_adder = (hi_frequency - lo_frequency) / points

    tile.stop_pattern("all")
    tile['fpga1.jesd204_if.regfile_channel_disable'] = 0xFFFF
    tile['fpga2.jesd204_if.regfile_channel_disable'] = 0xFFFF
    tile.test_generator_disable_tone(0)
    tile.test_generator_disable_tone(1)
    tile.test_generator_set_noise(0.0)
    tile.test_generator_input_select(0xFFFFFFFF)
    for n in range(16):
        cal_coeff = [[complex(2.0), complex(0.0), complex(0.0), complex(2.0)]] * 512
        #if n == 0:
        #    cal_coeff = [[complex(1.0), complex(0.0), complex(0.0), complex(0.0)]] * 512
        #else:
        #    cal_coeff = [[complex(0.0), complex(0.0), complex(0.0), complex(0.0)]] * 512
        tile.tpm.beamf_fd[int(n / 8)].load_calibration(n % 8, cal_coeff[64:448])
    tile.tpm.beamf_fd[0].switch_calibration_bank(force=True)
    tile.tpm.beamf_fd[1].switch_calibration_bank(force=True)
    tile.set_channeliser_truncation(4)

    amplitude = 1.0

    tile['fpga1.lmc_integrated_gen.beamf_scaling_factor'] = 10
    tile['fpga2.lmc_integrated_gen.beamf_scaling_factor'] = 10

    time.sleep(0.2)

    # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
    # I'll change this to make it nicer
    daq_config = {
                      'receiver_interface': 'eth3',  # CHANGE THIS if required
                      'directory': temp_dir,  # CHANGE THIS if required
                      'nof_beam_channels': 384,
                      'nof_beam_samples': 1
                      }

    # Configure the DAQ receiver and start receiving data
    daq.populate_configuration(daq_config)
    daq.initialise_daq()

    # Start whichever consumer is required and provide callback
    daq.start_integrated_beam_data_consumer(callback=data_callback)
    #
    # raw data synchronised
    #
    response_vc = []
    response_vp = []
    response_vn = []
    power_pc = []
    power_pp = []
    power_pn = []
    freqs = []
    iteration = 1
    print(lo_frequency)
    print(hi_frequency)
    test_frequency = lo_frequency

    f = open("channel_" + str(channel) + "_response.txt", "w")
    f.write("")
    f.close()

    while test_frequency <= hi_frequency:
        remove_files()
        print("Iteration " + str(iteration) + "/" + str(points) + ": Acquiring frequency " + str(test_frequency))

        while tile.test_generator_set_tone(0, test_frequency, amplitude, delay=1000) < 0:
            print("Setting test generator again...")

        for n in range(3):
            remove_files()
            data_received = False
            while not data_received:
                time.sleep(0.1)

        kc = data[0, channel-64, 0, 0]
        kp = data[0, channel-64-1, 0, 0]
        kn = data[0, channel-64+1, 0, 0]

        # if kc < 1236311703:
        #     print("Error!")
        #     print("Value:     " + str(kc) + " " + str(kp) + " " + str(kn))
        #     exit()

        vc, pc = filter_value(kc)
        vp, pp = filter_value(kp)
        vn, pn = filter_value(kn)

        print("Value:     " + str(kc) + " " + str(kp) + " " + str(kn))
        print("Appending: " + str(vc) + " " + str(vp) + " " + str(vn))

        response_vc.append(kc)
        response_vp.append(kp)
        response_vn.append(kn)
        power_pc.append(pc)
        power_pp.append(pp)
        power_pn.append(pn)
        freqs.append(test_frequency / 1e6)

        test_frequency += frequency_adder
        iteration += 1

        f = open("channel_" + str(channel) + "_response.txt", "a")
        txt = str(test_frequency / 1e6) + " " + str(vc) + " " + str(vp) + " " + str(vn) + "\n"
        f.write(txt)
        f.close()

    plt.plot(freqs, power_pc, 'bo', markersize=2)
    plt.plot(freqs, power_pp, 'ro', markersize=2)
    plt.plot(freqs, power_pn, 'go', markersize=2)
    plt.savefig("channel_" + str(channel) + "_response.png", dpi=300)

    # f = open("channel_" + str(channel) + "_response.txt", "w")
    # txt = ""
    # for n in range(len(freqs)):
    #     txt += str(freqs[n]) + " " + str(response[n]) + "\n"
    # f.write(txt)
    # f.close()

    daq.stop_integrated_beam_data_consumer()

