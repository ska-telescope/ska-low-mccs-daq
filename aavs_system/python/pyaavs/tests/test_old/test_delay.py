import numpy as np
import time


def test_setup(beamformer, ch):
    """
  Test of the delay in the beamformer
  Generates a set of short integrations, in a given channel, 
  with delay compensated in the tile beamformer
  Delay compensation ranges from -8 t0 +8 times the delay to compensate
  in steps of 0.1 times
  """
    tile = beamformer.tile
    tload = tile.tpm["fpga1.pps_manager.timestamp_read_val"] + 100
    tile.tpm.test_generator[0].set_tone(0, (ch + 1 / 1024.) * 800e6 / 1024, 1.0, 0.0, tload)
    tile.tpm.test_generator[1].set_tone(0, (ch + 1 / 1024.) * 800e6 / 1024, 1.0, 0.0, tload)
    tile.tpm.test_generator[0].set_tone(1, ((ch + 4) + 1 / 1024.) * 800e6 / 1024, 1.0, 0.0, tload)
    tile.tpm.test_generator[1].set_tone(1, ((ch + 4) + 1 / 1024.) * 800e6 / 1024, 1.0, 0.0, tload)
    tile.tpm.test_generator[0].channel_select(0xffff)
    tile.tpm.test_generator[1].channel_select(0xffff)
    beamformer.set_first_last_tile(True, False)
    beamformer.set_regions([[ch & 0x1f8, 8, 0]])
    beamformer.set_global_level(16)
    tile['fpga1.regfile.debug'] = 0
    tile['fpga2.regfile.debug'] = 0
    tile.set_channeliser_truncation(4)

    delay0 = [0] * 16
    delay1 = [8, 8, 7, 7, 6, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1]
    delay2 = [0, 0, -1, -1, -2, -2, -3, -3, -4, -4, -5, -5, -6, -6, -7, -7]
    tile.tpm.test_generator[0].set_delay(delay1)
    tile.tpm.test_generator[1].set_delay(delay2)
    delay_fp = [[0.0, 0.0]] * 16
    beamformer.set_delay(delay_fp, 0)
    beamformer.load_delay()
    time.sleep(0.02)


#
def test_delay(beamformer):
    """
  Test of the delay in the beamformer
  Generates a set of short integrations, in a given channel, 
  with delay compensated in the tile beamformer
  Delay compensation ranges from -8 t0 +8 times the delay to compensate
  in steps of 0.1 times
  """
    tile = beamformer.tile
    ch = 129
    sample_time = 1.25e-9
    delay_fp = [[0.0, 0.0]] * 16
    test_setup(beamformer, ch)
    for d in range(-600, 200):
        for i in range(16):
            delay_fp[i] = [(i - 8) * 0.01 * d * sample_time, 0.0]
        beamformer.set_delay(delay_fp, 0)
        # start_frame = (beamformer.current_frame()+256)&0xfffffff8
        start_frame = 0
        beamformer.load_delay(start_frame)
        time.sleep(0.01)
        beamformer.start(start_frame, 16)
        time.sleep(0.02)

    tile.tpm.test_generator[0].set_delay([0] * 16)
    tile.tpm.test_generator[1].set_delay([0] * 16)
    beamformer.set_delay([[0.0, 0.0]] * 16, 0)
    beamformer.load_delay(0)
    time.sleep(0.01)


#
def test_rate(beamformer):
    """
  # Test of the delay rate in the beamformer
  # Generates a set of short integrations, in a given channel, 
  # with delay compensated in the tile beamformer
  Delay sweep is done using the delay rate.  It starts at -2 times the 
  actual delay, and sweeps at the actual delay every 600 seconds.
  So it should be compensated at exactly 1800 seconds from start
  A short integration is taken every 12 seconds for 3600 seconds
  """
    tile = beamformer.tile
    ch = 129
    sample_time = 1.25e-9
    delay_fp = [[0.0, 0.0]] * 16
    test_setup(beamformer, ch)
    d = -2.0  # Initial delay
    delay_fp = [[0.0, 0.0]] * 16
    for i in range(16):
        del1 = (i - 8) * d * sample_time
        delay_fp[i] = [del1, -del1 / 600.]  # Delay rate compensates after 1800s
    beamformer.set_delay(delay_fp, 0)
    beamformer.load_delay()
    time.sleep(0.02)
    for d in range(300):
        beamformer.start(0, 16)
        if np.mod(d, 10):
            print(d / 10)
        time.sleep(12.)

    tile.tpm.test_generator[0].set_delay([0] * 16)
    tile.tpm.test_generator[1].set_delay([0] * 16)
    beamformer.set_delay([[0.0, 0.0]] * 16, 0)
    beamformer.load_delay(0)
    time.sleep(0.01)


def test_prdg_delay(beamformer):
    tile = beamformer.tile
    ch = 128
    tload = tile.tpm["fpga1.pps_manager.timestamp_read_val"] + 100
    tile.tpm.test_generator[0].enable_prdg(1.0, tload)
    tile.tpm.test_generator[1].enable_prdg(1.0, tload)
    tile.tpm.test_generator[0].set_tone(0, 0.0, 0.0)
    tile.tpm.test_generator[0].set_tone(1, 0.0, 0.0)
    tile.tpm.test_generator[1].set_tone(0, 0.0, 0.0)
    tile.tpm.test_generator[1].set_tone(1, 0.0, 0.0)
    tile.tpm.test_generator[0].channel_select(0xffff)
    tile.tpm.test_generator[1].channel_select(0xffff)
    beamformer.set_first_last_tile(True, False)
    beamformer.set_regions([[ch & 0x1f8, 8, 0]])
    beamformer.set_global_level(16)
    tile['fpga1.regfile.debug'] = 0
    tile['fpga2.regfile.debug'] = 0
    tile.set_channeliser_truncation(1)

    delay0 = [0] * 16
    delay1 = [0] * 16
    delay2 = [0] * 16
    delay = [-42, -41, -32, -24, -23, -21, -13, -1, 1, 4, 19, 21, 23, 33, 37, 40]
    sample_time = 1.25e-9
    delay_fp = [[0.0, 0.0]] * 16
    for i in range(16):
        delay_fp[i] = [-sample_time * delay[i]]
        delay1[i] = delay[i / 2]
        delay2[i] = delay[i / 2 + 8]
#
