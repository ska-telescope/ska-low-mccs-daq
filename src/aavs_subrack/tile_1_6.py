import functools
import logging
import os

from pyfabil.base.definitions import *
from pyfabil.boards.tpm_1_6 import TPM_1_6

from pyaavs.tile import Tile


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

    def connect(self, initialise=False, simulation=False, enable_ada=False, enable_adc=True):

        # Try to connect to board, if it fails then set tpm to None
        self.tpm = TPM_1_6()

        # Add plugin directory (load module locally)
        tf = __import__("aavs_subrack.tpm_test_firmware", fromlist=[None])
        self.tpm.add_plugin_directory(os.path.dirname(tf.__file__))

        self.tpm.connect(ip=self._ip, port=self._port, initialise=initialise,
                         simulator=simulation, enable_ada=enable_ada, enable_adc=enable_adc, fsample=self._sampling_rate)

        # Load tpm test firmware for both FPGAs (no need to load in simulation)
        if not simulation and self.tpm.is_programmed():
            self.tpm.load_plugin("Tpm_1_6_TestFirmware", device=Device.FPGA_1, fsample=self._sampling_rate)
            self.tpm.load_plugin("Tpm_1_6_TestFirmware", device=Device.FPGA_2, fsample=self._sampling_rate)
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
        # self[0x30000024] = 0x2

        # Calibrate FPGA to CPLD streaming
        # self.calibrate_fpga_to_cpld()

        # Initialise firmware plugin
        for firmware in self.tpm.tpm_test_firmware:
            firmware.initialise_firmware()

        # Set LMC IP
        self.tpm.set_lmc_ip(self._lmc_ip, self._lmc_port)

        # Enable C2C streaming
        self.tpm["board.regfile.ena_stream"] = 0x1
        self.tpm['board.regfile.ena_header'] = 0x1
        self.tpm['board.regfile.ethernet_pause']=10000

        # Switch off both PREADUs
        #self.tpm.preadu[0].switch_off()
        #self.tpm.preadu[1].switch_off()

        # Switch on preadu
        # for preadu in self.tpm.preadu:
        #     preadu.switch_on()
        #     time.sleep(1)
        #     preadu.select_low_passband()
        #     preadu.read_configuration()

        # Synchronise FPGAs
        self.sync_fpgas()

        # Initialize f2f link
        # self.tpm.tpm_f2f[0].initialise_core("fpga2->fpga1")
        # self.tpm.tpm_f2f[1].initialise_core("fpga1->fpga2")

        # AAVS-only - swap polarisations due to remapping performed by preadu
        # self.tpm['fpga1.jesd204_if.regfile_pol_switch'] = 0b00001111
        # self.tpm['fpga2.jesd204_if.regfile_pol_switch'] = 0b00001111

        # Reset test pattern generator
        # self.tpm.test_generator[0].channel_select(0x0000)
        # self.tpm.test_generator[1].channel_select(0x0000)
        # self.tpm.test_generator[0].disable_prdg()
        # self.tpm.test_generator[1].disable_prdg()

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
        # ip_octets = self._ip.split('.')
        # for n in range(8):
        #     src_ip = "10.{}.{}.{}".format(n + 1, ip_octets[2], ip_octets[3])
        #     dst_ip = "10.{}.{}.{}".format((1 + n) + (4 if n < 4 else -4), ip_octets[2], ip_octets[3])
        #     self.configure_10g_core(n,
        #                             src_mac=0x620000000000 + ip2long(src_ip),
        #                             dst_mac=0x620000000000 + ip2long(dst_ip),
        #                             src_ip=src_ip,
        #                             dst_ip=dst_ip,
        #                             src_port=0xF0D0,
        #                             dst_port=4660)
        #
        # # wait UDP link up
        # logging.info("Waiting for 10G link...")
        # try:
        #     times = 0
        #     while True:
        #         linkup = 1
        #         for n in [0, 1, 2, 4, 5, 6]:
        #             core_status = self.tpm.tpm_10g_core[n].get_arp_table_status(0, silent_mode=True)
        #             if core_status & 0x4 == 0:
        #                 linkup = 0
        #         if linkup == 1:
        #             logging.info("10G Link established! ARP table populated!")
        #             break
        #         else:
        #             times += 1
        #             time.sleep(0.5)
        #             if times == 20:
        #                 logging.warning("10G Links not established after 10 seconds! ARP table not populated!")
        #                 break
        # except:
        #     time.sleep(4)
        #     self.mii_exec_test(10, False)
        #     self['fpga1.regfile.eth10g_ctrl'] = 0x0
        #     self['fpga2.regfile.eth10g_ctrl'] = 0x0

        for firmware in self.tpm.tpm_test_firmware:
            firmware.check_ddr_initialisation()

    @connected
    def start_acquisition(self, start_time=None, delay=2):
        """ Start data acquisition """

        for f in ['fpga1', 'fpga2']:
            self.tpm['%s.regfile.eth10g_ctrl' % f] = 0x0

        # Temporary (moved here from TPM control)
        try:
            self.tpm['fpga1.regfile.c2c_stream_header_insert'] = 0x1
            self.tpm['fpga2.regfile.c2c_stream_header_insert'] = 0x1
        except:
            self.tpm['fpga1.regfile.c2c_stream_ctrl.header_insert'] = 0x1
            self.tpm['fpga2.regfile.c2c_stream_ctrl.header_insert'] = 0x1

        try:
            self.tpm['fpga1.regfile.lmc_stream_demux'] = 0x1
            self.tpm['fpga2.regfile.lmc_stream_demux'] = 0x1
        except:
            pass

        devices = ["fpga1", "fpga2"]

        for f in devices:
            # Disable start force (not synchronised start)
            self.tpm["%s.pps_manager.start_time_force" % f] = 0x0
            self.tpm["%s.lmc_gen.timestamp_force" % f] = 0x0

        # Read current sync time
        if start_time is None:
            t0 = self.tpm["fpga1.pps_manager.curr_time_read_val"]
        else:
            t0 = start_time

        sync_time = t0 + delay
        # Write start time
        for f in devices:
            # for station_beamformer in self.tpm.station_beamf:
            #     station_beamformer.set_epoch(sync_time)
            self.tpm['%s.pps_manager.sync_time_val' % f] = sync_time
