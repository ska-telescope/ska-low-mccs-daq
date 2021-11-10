# Import DAQ and Access Layer libraries
# import pydaq.daq_receiver as daq
from pyaavs.tile import Tile


from datetime import datetime, timedelta
from sys import stdout
import numpy as np
import os.path
import logging
import socket
import random
import psutil
import shutil
import math
import time


def accurate_sleep(seconds):
    now = datetime.now()
    end = now + timedelta(seconds=seconds)
    while now < end:
        now = datetime.now()
        time.sleep(0.1)


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
    half = int(len(pattern) / 2)
    for n in range(int(half / 2)):
        tmp[4*n] = pattern[2*n]
        tmp[4*n+1] = pattern[2*n+1]
        tmp[4*n+2] = pattern[-(1+2*n+1)]
        tmp[4*n+3] = pattern[-(1+2*n)]
    return tmp


def set_pattern(tile, stage, pattern, adders, start, shift=0):
    # print("Setting " + stage + " data pattern")
    if stage == "channel":
        pattern_tmp = channelize_pattern(pattern)
    else:
        pattern_tmp = pattern

    signal_adder = []
    for n in range(32):
        signal_adder += [adders[n]]*4

    for i in range(2):
        tile.tpm.tpm_pattern_generator[i].set_pattern(pattern_tmp, stage)
        tile.tpm.tpm_pattern_generator[i].set_signal_adder(signal_adder[64*i:64*(i+1)], stage)
        tile['fpga1.pattern_gen.%s_left_shift' % stage] = shift
        tile['fpga2.pattern_gen.%s_left_shift' % stage] = shift
        tile['fpga1.pattern_gen.beamf_left_shift'] = 4
        tile['fpga2.pattern_gen.beamf_left_shift'] = 4
    if start:
        for i in range(2):
            tile.tpm.tpm_pattern_generator[i].start_pattern(stage)


def stop_pattern(tile, stage):
    # print("Stopping " + stage + " data pattern")
    if stage == "all":
        stages = ["jesd", "channel", "beamf"]
    else:
        stages = [stage]
    for s in stages:
        for i in range(2):
            tile.tpm.tpm_pattern_generator[i].stop_pattern(s)


def stop_station_pattern(station, stage):
    for tile in station.tiles:
        for i in range(2):
            tile.tpm.tpm_pattern_generator[i].stop_pattern(stage)


def disable_test_generator_and_pattern(tile):
    stop_pattern(tile, "all")
    tile['fpga1.jesd204_if.regfile_channel_disable'] = 0x0
    tile['fpga2.jesd204_if.regfile_channel_disable'] = 0x0
    tile.test_generator_set_tone(0, 0.0, 0.0)
    tile.test_generator_set_tone(1, 0.0, 0.0)
    tile.test_generator_set_noise(0.0)
    tile.test_generator_input_select(0x00000000)


def set_chennelizer_walking_pattern(tile):
    set_pattern(tile, "channel", range(1024), [0]*32, True, 0)
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_enable' % "channel"] = 1
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_enable' % "channel"] = 1
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_adder' % "channel"] = 1
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_adder' % "channel"] = 1
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_lo' % "channel"] = 0
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_lo' % "channel"] = 0
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_hi' % "channel"] = 255
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_hi' % "channel"] = 255
    tile['fpga1.pattern_gen.%s_frame_offset_change' % "channel"] = 0
    tile['fpga2.pattern_gen.%s_frame_offset_change' % "channel"] = 0

    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_clear' % "channel"] = 1
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_clear' % "channel"] = 1
    tile.wait_pps_event()
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_clear' % "channel"] = 0
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_clear' % "channel"] = 0


def set_delay(tile, delay):
    tile.tpm.test_generator[0].set_delay(delay[0:16])
    tile.tpm.test_generator[1].set_delay(delay[16:32])


def get_beam_value(data, pol, channel):
    sample = 0
    x = 0
    return data[pol, channel, sample, x][0] + data[pol, channel, sample, x][1]*1j


def reset_beamf_coeff(tile,  gain=2.0):
    for n in range(16):
        cal_coeff = [[complex(gain), complex(0.0), complex(0.0), complex(gain)]] * 512
        tile.tpm.beamf_fd[int(n / 8)].load_calibration(int(n % 8), cal_coeff)
        # tile.tpm.beamf_fd[int(n / 8)].load_cal_curve(int(n % 8), 0, cal_coeff)
    #tile.tpm.beamf_fd[0].compute_calibration_coefs()
    #tile.tpm.beamf_fd[1].compute_calibration_coefs()
    tile.tpm.beamf_fd[0].switch_calibration_bank(force=True)
    tile.tpm.beamf_fd[1].switch_calibration_bank(force=True)


def set_beamf_coeff(tile, coeff, channel):
    for n in range(16):
        # cal_coeff = [[complex(0.0), complex(0.0), complex(0.0), complex(0.0)]] * 512
        cal_coeff = [np.random.random_sample(4)] * 512
        cal_coeff[channel] = [coeff[0][n], complex(0.0), complex(0.0), coeff[1][n]]
        #tile.tpm.beamf_fd[int(n / 8)].load_calibration(int(n % 8), cal_coeff[64:448])
        tile.tpm.beamf_fd[int(n / 8)].load_cal_curve(int(n % 8), 0, cal_coeff)
    tile.tpm.beamf_fd[0].compute_calibration_coefs()
    tile.tpm.beamf_fd[1].compute_calibration_coefs()
    tile.tpm.beamf_fd[0].switch_calibration_bank()
    tile.tpm.beamf_fd[1].switch_calibration_bank()


def mask_antenna(tile, antenna, gain=1.0):
    for n in range(16):
        if n in antenna:
            cal_coeff = [[complex(0.0), complex(0.0), complex(0.0), complex(0.0)]] * 512
        else:
            cal_coeff = [[complex(gain), complex(0.0), complex(0.0), complex(gain)]] * 512
        tile.tpm.beamf_fd[int(n / 8)].load_calibration(int(n % 8), cal_coeff[64:448])
    tile.tpm.beamf_fd[0].switch_calibration_bank()
    tile.tpm.beamf_fd[1].switch_calibration_bank()


def enable_adc_test_pattern(tile, adc, pattern_type, pattern_value=[[15, 67, 252, 128]]*16):
    # print("Setting ADC pattern " + pattern_type)
    for adc_id in adc:
        # print("setting ADC pattern " + pattern_type + " on ADC " + str(adc_id))
        tile[("adc" + str(adc_id), 0x552)] = pattern_value[adc_id][0]
        tile[("adc" + str(adc_id), 0x554)] = pattern_value[adc_id][1]
        tile[("adc" + str(adc_id), 0x556)] = pattern_value[adc_id][2]
        tile[("adc" + str(adc_id), 0x558)] = pattern_value[adc_id][3]
        if pattern_type ==  "fixed":
            tile[("adc" + str(adc_id), 0x550)] = 0x8
        elif pattern_type == "ramp":
            tile[("adc" + str(adc_id), 0x550)] = 0xF
        else:
            logging.error("Supported patterns are fixed, ramp")
            sys.exit(-1)


def disable_adc_test_pattern(tile, adc):
    for adc_id in adc:
        tile[("adc" + str(adc_id), 0x550)] = 0x0


def get_beamf_pattern_data(channel, pattern, adder, shift):
    index = 4 * (int(channel / 2))
    ret = []
    for n in range(4):
        adder_idx = 64 * (channel % 2) + n
        data = pattern[index+n]
        data += adder[adder_idx]
        data &= 0xFF
        data = data << shift
        data = signed(data, 12, 12)
        ret.append(data)
    return ret


def rms_station_log(station, sampling_period=1.0):
    file_names = []
    time_now = str((datetime.utcnow() - datetime(1970, 1, 1)).total_seconds())
    time_now = time_now.replace(".", "_")
    for tile in station.tiles:
        file_name = "rms_log_" + str(tile._ip) + "_" + time_now + ".log"
        f = open(file_name, "w")
        f.write("")
        f.close()
        file_names.append(file_name)
    time_prev = datetime.now()
    try:
        while True:
            time_this = datetime.now()
            time_diff = time_this - time_prev
            time_sec = time_diff.total_seconds()
            time_prev = time_this
            for i, tile in enumerate(station.tiles):
                rms = tile.get_adc_rms()
                f = open(file_names[i], "a")
                txt = str(time_sec)
                for r in range(len(rms)):
                    txt += " " + str(rms[r])
                txt += "\n"
                f.write(txt)
                f.close()
            time.sleep(sampling_period)
    except KeyboardInterrupt:
        print('interrupted!')


def ddr_test(station, duration, last_addr=0x7FFFFF8):
    station['fpga1.ddr_simple_test.last_addr'] = last_addr
    station['fpga2.ddr_simple_test.last_addr'] = last_addr

    station['fpga1.ddr_simple_test.start'] = 0
    station['fpga2.ddr_simple_test.start'] = 0

    station['fpga1.ddr_simple_test.error'] = 0
    station['fpga2.ddr_simple_test.error'] = 0

    time.sleep(0.1)

    station['fpga1.ddr_simple_test.start'] = 1
    station['fpga2.ddr_simple_test.start'] = 1

    fpga1_pass = station['fpga1.ddr_simple_test.pass']
    fpga2_pass = station['fpga2.ddr_simple_test.pass']
    fpga1_status = station['fpga1.ddr_if.status']
    fpga2_status = station['fpga2.ddr_if.status']

    for n in range(duration):
        time.sleep(1)
        for n in range(len(station.tiles)):
            print(station['fpga1.ddr_simple_test.pass'])
            print(station['fpga2.ddr_simple_test.pass'])
            if station['fpga1.ddr_simple_test.error'][n] == 1:
                print("Tile %d FPGA1 error. Test error." % n)
                return
            if station['fpga2.ddr_simple_test.error'][n] == 1:
                print("Tile %d FPGA2 error. Test error." % n)
                return
            if (station['fpga1.ddr_if.status'][n] & 0xF00) != (fpga1_status[n] & 0xF00):
                print("Tile %d FPGA1 error. Reset error." % n)
                return
            if (station['fpga2.ddr_if.status'][n] & 0xF00) != (fpga2_status[n] & 0xF00):
                print("Tile %d FPGA2 error. Reset error." % n)
                return
            print("Test running ...")

    station['fpga1.ddr_simple_test.start'] = 0
    station['fpga2.ddr_simple_test.start'] = 0
    print("Test passed!")


def ddr_reset(station):
    station[0x00000020] = 0
    station[0x10000020] = 0
    station[0x00000020] = 0x10
    station[0x10000020] = 0x10
    station[0x00000020] = 0
    station[0x10000020] = 0


def remove_hdf5_files(temp_dir):
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    if not os.path.exists(temp_dir):
        # print("Creating temp folder: " + temp_dir)
        os.system("mkdir " + temp_dir)


def add_default_parser_options(parser):
    from optparse import OptionParser
    parser.add_option("--config", action="store", dest="config",
                      type="str", default=None, help="Station configuration file [default: None]")
    parser.add_option("--test_config", action="store", dest="test_config",
                      type="str", default="config/test_config.yml",
                      help="Test Environment configuration file [default: config/test_config.yml]")
    parser.add_option("--tpm_port", action="store", dest="tpm_port",
                      default="", help="UDP Port for UCP protocol [default: 10000]")
    parser.add_option("--tpm_ip", action="store", dest="tpm_ip",
                      default="", help="Specify TPM IP [default: None, Address retireved from configuratiuon files]")
    return parser

def get_tpm_version(tile):
    from pyfabil.boards.tpm_generic import TPMGeneric
    _tpm = TPMGeneric()
    _tpm_version = _tpm.get_tpm_version(socket.gethostbyname(tile._ip), 10000)
    return _tpm_version
