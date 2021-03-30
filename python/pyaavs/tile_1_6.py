import functools
import logging
import socket
import threading
import os

from datetime import datetime
from sys import stdout
import numpy as np
import time
import struct

from pyfabil.base.definitions import *
from pyfabil.base.utils import ip2long
from pyfabil.boards.tpm_1_6 import TPM_1_6
from pyaavs.tile import Tile
#from pyaavs.plugins import *


# Helper to disallow certain function calls on unconnected tiles
def connected(f):
    @functools.wraps(f)
    def wrapper(self, *args, **kwargs):
        if self.tpm is None:
            logging.warn("Cannot call function {} on unconnected TPM".format(f.__name__))
            raise LibraryError("Cannot call function {} on unconnected TPM".format(f.__name__))
        else:
            return f(self, *args, **kwargs)

    return wrapper


class Tile_1_6(Tile):
    def __init__(self, ip="10.0.10.2", port=10000, lmc_ip="10.0.10.1", lmc_port=4660, sampling_rate=800e6):
        super(Tile_1_6, self).__init__(ip, port, lmc_ip, lmc_port, sampling_rate)
    # ---------------------------- Main functions ------------------------------------

    def connect(self, initialise=False, simulation=False, enable_ada=False, enable_adc=True, dsp_core=True):

        # Try to connect to board, if it fails then set tpm to None
        self.tpm = TPM_1_6()

        # Add plugin directory (load module locally)
        tf = __import__("pyaavs.plugins.tpm_1_6.tpm_test_firmware", fromlist=[None])
        self.tpm.add_plugin_directory(os.path.dirname(tf.__file__))

        self.tpm.connect(ip=self._ip, port=self._port, initialise=initialise,
                         simulator=simulation, enable_ada=enable_ada, enable_adc=enable_adc, fsample=self._sampling_rate)

        # Load tpm test firmware for both FPGAs (no need to load in simulation)
        if not simulation and self.tpm.is_programmed():
            self.tpm.load_plugin("Tpm_1_6_TestFirmware", device=Device.FPGA_1, fsample=self._sampling_rate, dsp_core=dsp_core)
            self.tpm.load_plugin("Tpm_1_6_TestFirmware", device=Device.FPGA_2, fsample=self._sampling_rate, dsp_core=dsp_core)
        elif not self.tpm.is_programmed():
            logging.warn("TPM is not programmed! No plugins loaded")

    def initialise(self, enable_ada=False, enable_test=False, enable_adc=True):
        """ Connect and initialise """

        # Connect to board
        self.connect(initialise=True, enable_ada=enable_ada, enable_adc=enable_adc)

        # Before initialing, check if TPM is programmed
        if not self.tpm.is_programmed():
            logging.error("Cannot initialise board which is not programmed")
            return

        # Disable debug UDP header
        self.tpm['board.regfile.ena_header'] = 0x1

        # Calibrate FPGA to CPLD streaming
        # self.calibrate_fpga_to_cpld()

        # Initialise firmware plugin
        for firmware in self.tpm.tpm_test_firmware:
            firmware.initialise_firmware()

        # Set LMC IP
        self.tpm.set_lmc_ip(self._lmc_ip, self._lmc_port)

        # Enable C2C streaming
        self.tpm["board.regfile.ena_stream"] = 0x1
        # self.tpm['board.regfile.ethernet_pause']=10000
        self.set_c2c_burst()

        # Switch off both PREADUs
        #self.tpm.tpm_preadu[0].switch_off()
        #self.tpm.tpm_preadu[1].switch_off()

        # Switch on preadu
        # for preadu in self.tpm.tpm_preadu:
        #     preadu.switch_on()
        #     time.sleep(1)
        #     preadu.select_low_passband()
        #     preadu.read_configuration()

        # Synchronise FPGAs
        self.sync_fpgas()

        # Initialize f2f link
        for f2f in self.tpm.tpm_f2f:
            f2f.assert_reset()
        for f2f in self.tpm.tpm_f2f:
            f2f.deassert_reset()

        # AAVS-only - swap polarisations due to remapping performed by preadu
        # self.tpm['fpga1.jesd204_if.regfile_pol_switch'] = 0b00001111
        # self.tpm['fpga2.jesd204_if.regfile_pol_switch'] = 0b00001111

        # Reset test pattern generator
        self.tpm.test_generator[0].channel_select(0x0000)
        self.tpm.test_generator[1].channel_select(0x0000)
        self.tpm.test_generator[0].disable_prdg()
        self.tpm.test_generator[1].disable_prdg()

        # Use test_generator plugin instead!
        if enable_test:
            # Test pattern. Tones on channels 72 & 75 + pseudo-random noise
            logging.info("Enabling test pattern")
            for generator in self.tpm.test_generator:
                generator.set_tone(0, 72 * self._sampling_rate / 1024, 0.0)
                generator.enable_prdg(0.4)
                generator.channel_select(0xFFFF)

        # Set destination and source IP/MAC/ports for 10G cores
        # This will create a loopback between the two FPGAs
        ip_octets = self._ip.split('.')
        for n in range(len(self.tpm.tpm_10g_core)):
            src_ip = "10.10.{}.{}".format(n + 1, ip_octets[3])
            # dst_ip = "10.{}.{}.{}".format((1 + n) + (4 if n < 4 else -4), ip_octets[2], ip_octets[3])
            if self.tpm.tpm_test_firmware[0].xg_40g_eth:
                self.configure_40g_core(n, 0,
                                        src_mac=0x620000000000 + ip2long(src_ip),
                                        # dst_mac=None,  # 0x620000000000 + ip2long(dst_ip),
                                        src_ip=src_ip,
                                        dst_ip=None,  # dst_ip,
                                        src_port=0xF0D0,
                                        dst_port=4660)
            else:
                self.configure_10g_core(n,
                                        src_mac=0x620000000000 + ip2long(src_ip),
                                        dst_mac=None, #0x620000000000 + ip2long(dst_ip),
                                        src_ip=src_ip,
                                        dst_ip=None, #dst_ip,
                                        src_port=0xF0D0,
                                        dst_port=4660)

        for firmware in self.tpm.tpm_test_firmware:
            firmware.check_ddr_initialisation()

    def f2f_aurora_test_start(self):
        for f2f in self.tpm.tpm_f2f:
            f2f.start_tx_test()
        for f2f in self.tpm.tpm_f2f:
            f2f.start_rx_test()

    def f2f_aurora_test_check(self):
        for f2f in self.tpm.tpm_f2f:
            f2f.get_test_result()

    def f2f_aurora_test_stop(self):
        for f2f in self.tpm.tpm_f2f:
            f2f.stop_test()
