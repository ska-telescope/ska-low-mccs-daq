from __future__ import division

import functools
import logging
import os
import socket
import threading
import time
from builtins import range
from builtins import str

import numpy as np
from past.utils import old_div
from pyfabil.base.definitions import *
from pyfabil.base.utils import ip2long
from pyfabil.boards.tpm import TPM


# Helper to disallow certain function calls on unconnected tiles
def connected(f):
    @functools.wraps(f)
    def wrapper(self, *args, **kwargs):
        if self.tpm is None:
            logging.warning("Cannot call function {} on unconnected TPM".format(f.__name__))
            raise LibraryError("Cannot call function {} on unconnected TPM".format(f.__name__))
        else:
            return f(self, *args, **kwargs)

    return wrapper


class Tile(object):
    def __init__(self, ip="10.0.10.2", port=10000, lmc_ip="10.0.10.1", lmc_port=4660, sampling_rate=800e6):
        self._lmc_port = lmc_port
        self._lmc_ip = socket.gethostbyname(lmc_ip)
        self._port = port
        self._ip = socket.gethostbyname(ip)
        self.tpm = None

        self.station_id = 0
        self.tile_id = 0

        self._sampling_rate = sampling_rate

        # Threads for continuously sending data
        self._RUNNING = 2
        self._ONCE = 1
        self._STOP = 0
        self._daq_threads = {}

        # Mapping between preadu and TPM inputs
        self.fibre_preadu_mapping = {0: 1, 1: 2, 2: 3, 3: 4,
                                     7: 13, 6: 14, 5: 15, 4: 16,
                                     8: 5, 9: 6, 10: 7, 11: 8,
                                     15: 9, 14: 10, 13: 11, 12: 12}

    # ---------------------------- Main functions ------------------------------------

    def connect(self, initialise=False, simulation=False, enable_ada=False):

        # Try to connect to board, if it fails then set tpm to None
        self.tpm = TPM()

        # Add plugin directory (load module locally)
        tf = __import__("pyaavs.tpm_test_firmware", fromlist=[None])
        self.tpm.add_plugin_directory(os.path.dirname(tf.__file__))

        self.tpm.connect(ip=self._ip, port=self._port, initialise=initialise,
                         simulator=simulation, enable_ada=enable_ada, fsample=self._sampling_rate)

        # Load tpm test firmware for both FPGAs (no need to load in simulation)
        if not simulation and self.tpm.is_programmed():
            self.tpm.load_plugin("TpmTestFirmware", device=Device.FPGA_1, fsample=self._sampling_rate)
            self.tpm.load_plugin("TpmTestFirmware", device=Device.FPGA_2, fsample=self._sampling_rate)
        elif not self.tpm.is_programmed():
            logging.warn("TPM is not programmed! No plugins loaded")

    def initialise(self, enable_ada=False, enable_test=False):
        """ Connect and initialise """

        # Connect to board
        self.connect(initialise=True, enable_ada=enable_ada)

        # Before initialing, check if TPM is programmed
        if not self.tpm.is_programmed():
            logging.error("Cannot initialise board which is not programmed")
            return

        # Disable debug UDP header
        self[0x30000024] = 0x2

        # Calibrate FPGA to CPLD streaming
        # self.calibrate_fpga_to_cpld()

        # Initialise firmware plugin
        for firmware in self.tpm.tpm_test_firmware:
            firmware.initialise_firmware()

        # Set LMC IP
        self.tpm.set_lmc_ip(self._lmc_ip, self._lmc_port)

        # Enable C2C streaming
        self.tpm["board.regfile.c2c_stream_enable"] = 0x1
        self.set_c2c_burst()

        # Switch off both PREADUs
        self.tpm.preadu[0].switch_off()
        self.tpm.preadu[1].switch_off()

        # Switch on preadu
        for preadu in self.tpm.preadu:
            preadu.switch_on()
            time.sleep(1)
            preadu.select_low_passband()
            preadu.read_configuration()

        # Synchronise FPGAs
        self.sync_fpgas()

        # Initialize f2f link
        self.tpm.tpm_f2f[0].initialise_core("fpga2->fpga1")
        self.tpm.tpm_f2f[1].initialise_core("fpga1->fpga2")

        # AAVS-only - swap polarisations due to remapping performed by preadu
        self.tpm['fpga1.jesd204_if.regfile_pol_switch'] = 0b00001111
        self.tpm['fpga2.jesd204_if.regfile_pol_switch'] = 0b00001111

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
                generator.set_tone(0, old_div(72 * self._sampling_rate, 1024), 0.0)
                generator.enable_prdg(0.4)
                generator.channel_select(0xFFFF)

        # Set destination and source IP/MAC/ports for 10G cores
        # This will create a loopback between the two FPGAs
        ip_octets = self._ip.split('.')
        for n in range(8):
            src_ip = "10.{}.{}.{}".format(n + 1, ip_octets[2], ip_octets[3])
            dst_ip = "10.{}.{}.{}".format((1 + n) + (4 if n < 4 else -4), ip_octets[2], ip_octets[3])
            self.configure_10g_core(n,
                                    src_mac=0x620000000000 + ip2long(src_ip),
                                    dst_mac=0x620000000000 + ip2long(dst_ip),
                                    src_ip=src_ip,
                                    dst_ip=dst_ip,
                                    src_port=0xF0D0,
                                    dst_port=4660)

        # wait UDP link up
        logging.info("Waiting for 10G link...")
        try:
            times = 0
            while True:
                linkup = 1
                for n in [0, 1, 2, 4, 5, 6]:
                    core_status = self.tpm.tpm_10g_core[n].get_arp_table_status(0, silent_mode=True)
                    if core_status & 0x4 == 0:
                        linkup = 0
                if linkup == 1:
                    logging.info("10G Link established! ARP table populated!")
                    break
                else:
                    times += 1
                    time.sleep(0.5)
                    if times == 20:
                        logging.warning("10G Links not established after 10 seconds! ARP table not populated!")
                        break
        except:
            time.sleep(4)
            self.mii_exec_test(10, False)
            self['fpga1.regfile.eth10g_ctrl'] = 0x0
            self['fpga2.regfile.eth10g_ctrl'] = 0x0

        for firmware in self.tpm.tpm_test_firmware:
            firmware.check_ddr_initialisation()

    def program_fpgas(self, bitfile):
        """ Program FPGA with specified firmware
        :param bitfile: Bitfile to load """
        self.connect(simulation=True)
        logging.info("Downloading bitfile to board")
        if self.tpm is not None:
            self.tpm.download_firmware(Device.FPGA_1, bitfile)

    def program_cpld(self, bitfile):
        """ Program CPLD with specified bitfile
        :param bitfile: Bitfile to flash to CPLD"""
        self.connect(simulation=True)
        logging.info("Downloading bitstream to CPLD FLASH")
        if self.tpm is not None:
            return self.tpm.tpm_cpld.cpld_flash_write(bitfile)

    @connected
    def read_cpld(self, bitfile="cpld_dump.bit"):
        """ Read bitfile in CPLD FLASH
        :param bitfile: Bitfile where to dump CPLD firmware"""
        logging.info("Reading bitstream from  CPLD FLASH")
        self.tpm.tpm_cpld.cpld_flash_read(bitfile)

    def get_ip(self):
        """ Get tile IP"""
        return self._ip

    @connected
    def get_temperature(self):
        """ Read board temperature """
        return self.tpm.temperature()

    @connected
    def get_voltage(self):
        """ Read board voltage """
        return self.tpm.voltage()

    @connected
    def get_current(self):
        """ Read board current """
        return self.tpm.current()

    @connected
    def get_rx_adc_rms(self):
        """ Get ADC power
        :param adc_id: ADC ID"""

        # If board is not programmed, return None
        if not self.tpm.is_programmed():
            return None

        # Get RMS values from board
        rms = []
        for adc_power_meter in self.tpm.adc_power_meter:
            rms.extend(adc_power_meter.get_RmsAmplitude())

        return rms

    @connected
    def get_adc_rms(self):
        """ Get ADC power
        :param adc_id: ADC ID"""

        # If board is not programmed, return None
        if not self.tpm.is_programmed():
            return None

        # Get RMS values from board
        rms = []
        for adc_power_meter in self.tpm.adc_power_meter:
            rms.extend(adc_power_meter.get_RmsAmplitude())

        # Re-map values
        return rms

    @connected
    def get_fpga0_temperature(self):
        """ Get FPGA1 temperature """
        if self.is_programmed():
            return self.tpm.tpm_sysmon[0].get_fpga_temperature()
        else:
            return 0

    @connected
    def get_fpga1_temperature(self):
        """ Get FPGA1 temperature """
        if self.is_programmed():
            return self.tpm.tpm_sysmon[1].get_fpga_temperature()
        else:
            return 0

    @connected
    def mii_prepare_test(self, board):
        for n in range(8):
            self.tpm.tpm_10g_core[n].mii_test_mac_config(board)
            self.tpm.tpm_10g_core[n].mii_test(10, show_result=False, wait_result=True)

    @connected
    def mii_exec_test(self, pkt_num, wait_result=True):
        for n in range(8):
            self.tpm.tpm_10g_core[n].mii_test(pkt_num, show_result=False, wait_result=False)

        if wait_result:
            self.tpm.tpm_10g_core[7].mii_wait_idle()

            for n in range(8):
                self.tpm.tpm_10g_core[n].mii_test_result()

    @connected
    def mii_test(self, pkt_num, board, wait_result=True):
        self.mii_prepare_test(board)
        self.mii_exec_test(pkt_num, wait_result)

    @connected
    def mii_show_result(self):
        for n in range(8):
            self.tpm.tpm_10g_core[n].mii_test_result()

    @connected
    def configure_10g_core(self, core_id, src_mac=None, src_ip=None,
                           dst_mac=None, dst_ip=None, src_port=None,
                           dst_port=None):
        """ Configure a 10G core
        :param core_id: 10G core ID
        :param src_mac: Source MAC address
        :param src_ip: Source IP address
        :param dst_mac: Destination MAC address
        :param dst_ip: Destination IP
        :param src_port: Source port
        :param dst_port: Destination port"""

        # Configure core
        if src_mac is not None:
            self.tpm.tpm_10g_core[core_id].set_src_mac(src_mac)
        if src_ip is not None:
            self.tpm.tpm_10g_core[core_id].set_src_ip(src_ip)
        if dst_mac is not None:
            self.tpm.tpm_10g_core[core_id].set_dst_mac(dst_mac)
        if dst_ip is not None:
            self.tpm.tpm_10g_core[core_id].set_dst_ip(dst_ip)
        if src_port is not None:
            self.tpm.tpm_10g_core[core_id].set_src_port(src_port)
        if dst_port is not None:
            self.tpm.tpm_10g_core[core_id].set_dst_port(dst_port)

    @connected
    def get_10g_core_configuration(self, core_id):
        """ Get the configuration for a 10g core
        :param core_id: Core ID """
        return {'src_mac': int(self.tpm.tpm_10g_core[core_id].get_src_mac()),
                'src_ip': int(self.tpm.tpm_10g_core[core_id].get_src_ip()),
                'dst_ip': int(self.tpm.tpm_10g_core[core_id].get_dst_ip()),
                'dst_mac': int(self.tpm.tpm_10g_core[core_id].get_dst_mac()),
                'src_port': int(self.tpm.tpm_10g_core[core_id].get_src_port()),
                'dst_port': int(self.tpm.tpm_10g_core[core_id].get_dst_port())}

    @connected
    def set_lmc_download(self, mode, payload_length=1024, dst_ip=None, src_port=0xF0D0, dst_port=4660, lmc_mac=None):
        """ Configure link and size of control data
        :param mode: 1g or 10g
        :param payload_length: SPEAD payload length in bytes
        :param dst_ip: Destination IP
        :param src_port: Source port for integrated data streams
        :param dst_port: Destination port for integrated data streams
        :param lmc_mac: LMC Mac address is required for 10G lane configuration"""

        # Using 10G lane
        if mode.upper() == "10G":
            if payload_length >= 8193:
                logging.warning("Packet length too large for 10G")
                return

            if lmc_mac is None:
                logging.warning("LMC MAC must be specified for 10G lane configuration")
                return

            # If dst_ip is None, use local lmc_ip
            if dst_ip is None:
                dst_ip = self._lmc_ip

            self.configure_10g_core(2, dst_mac=lmc_mac,
                                    dst_ip=dst_ip,
                                    src_port=src_port,
                                    dst_port=dst_port)

            self.configure_10g_core(6, dst_mac=lmc_mac,
                                    dst_ip=dst_ip,
                                    src_port=src_port,
                                    dst_port=dst_port)

            self['fpga1.lmc_gen.payload_length'] = payload_length
            self['fpga2.lmc_gen.payload_length'] = payload_length

            self['fpga1.lmc_gen.tx_demux'] = 2
            self['fpga2.lmc_gen.tx_demux'] = 2

        # Using dedicated 1G link
        elif mode.upper() == "1G":
            self['fpga1.lmc_gen.tx_demux'] = 1
            self['fpga2.lmc_gen.tx_demux'] = 1
        else:
            logging.warning("Supported modes are 1g, 10g")
            return

    @connected
    def set_lmc_integrated_download(self, mode, channel_payload_length, beam_payload_length,
                                    dst_ip=None, src_port=0xF0D0, dst_port=4660, lmc_mac=None,):
        """ Configure link and size of control data
        :param mode: 1g or 10g
        :param channel_payload_length: SPEAD payload length for integrated channel data
        :param beam_payload_length: SPEAD payload length for integrated beam data
        :param dst_ip: Destination IP
        :param src_port: Source port for integrated data streams
        :param dst_port: Destination port for integrated data streams
        :param lmc_mac: LMC Mac address is required for 10G lane configuration"""

        # Using 10G lane
        if mode.upper() == "10G":
            if lmc_mac is None:
                logging.error("LMC MAC must be specified for 10G lane configuration")
                return

            # If dst_ip is None, use local lmc_ip
            if dst_ip is None:
                dst_ip = self._lmc_ip

            self.configure_10g_core(2, dst_mac=lmc_mac,
                                    dst_ip=dst_ip,
                                    src_port=src_port,
                                    dst_port=dst_port)

            self.configure_10g_core(6, dst_mac=lmc_mac,
                                    dst_ip=dst_ip,
                                    src_port=src_port,
                                    dst_port=dst_port)

        # Using dedicated 1G link
        elif mode.upper() == "1G":
            pass
        else:
            logging.error("Supported mode are 1g, 10g")
            return

        # Setting payload lengths
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].configure_download(mode, channel_payload_length, beam_payload_length)

    @connected
    def set_station_id(self, station_id, tile_id):
        """ Set station ID
        :param station_id: Station ID
        :param tile_id: Tile ID within station """
        try:
            self['fpga1.regfile.station_id'] = station_id
            self['fpga2.regfile.station_id'] = station_id
            self['fpga1.regfile.tpm_id'] = tile_id
            self['fpga2.regfile.tpm_id'] = tile_id
        except:
            self['fpga1.dsp_regfile.config_id.station_id'] = station_id
            self['fpga2.dsp_regfile.config_id.station_id'] = station_id
            self['fpga1.dsp_regfile.config_id.tpm_id'] = tile_id
            self['fpga2.dsp_regfile.config_id.tpm_id'] = tile_id

    @connected
    def get_station_id(self):
        """ Get station ID """
        if not self.tpm.is_programmed():
            return -1
        else:
            try:
                tile_id = self['fpga1.regfile.station_id']
            except:
                tile_id = self['fpga1.dsp_regfile.config_id.station_id']
            return tile_id

    @connected
    def get_tile_id(self):
        """ Get tile ID """
        if not self.tpm.is_programmed():
            return -1
        else:
            try:
                tile_id = self['fpga1.regfile.tpm_id']
            except:
                tile_id = self['fpga1.dsp_regfile.config_id.tpm_id']
            return tile_id

    @connected
    def tweak_transceivers(self):
        """ Tweak transceivers """
        for f in ['fpga1', 'fpga2']:
            for n in range(4):
                try:
                    add = int(self.tpm.memory_map['%s.eth_10g_drp.gth_channel_%i' % (f, n)].address) + 4*0x7C
                except:
                    add = int(self.tpm.memory_map['%s.eth_drp.gth_channel_%i' % (f, n)].address) + 4 * 0x7C
                self[add] = 0x6060

    @connected
    def get_fpga_time(self, device):
        """ Return time from FPGA
        :param device: FPGA to get time from """
        if device == Device.FPGA_1:
            return self["fpga1.pps_manager.curr_time_read_val"]
        elif device == Device.FPGA_2:
            return self["fpga2.pps_manager.curr_time_read_val"]
        else:
            raise LibraryError("Invalid device specified")

    @connected
    def set_fpga_time(self, device, device_time):
        """ Set tile time
        :param device: FPGA to set time to
        :param device_time: Time """
        if device == Device.FPGA_1:
            self["fpga1.pps_manager.curr_time_write_val"] = device_time
            self["fpga1.pps_manager.curr_time_cmd.wr_req"] = 0x1
        elif device == Device.FPGA_2:
            self["fpga2.pps_manager.curr_time_write_val"] = device_time
            self["fpga2.pps_manager.curr_time_cmd.wr_req"] = 0x1
        else:
            raise LibraryError("Invalid device specified")

    @connected
    def get_fpga_timestamp(self, device=Device.FPGA_1):
        """ Get timestamp from FPGA
        :param device: FPGA to read timestamp from """
        if device == Device.FPGA_1:
            return self["fpga1.pps_manager.timestamp_read_val"]
        elif device == Device.FPGA_2:
            return self["fpga2.pps_manager.timestamp_read_val"]
        else:
            raise LibraryError("Invalid device specified")

    @connected
    def get_phase_terminal_count(self):
        """ Get phase terminal count """
        return self["fpga1.pps_manager.sync_tc.cnt_1_pulse"]

    @connected
    def set_phase_terminal_count(self, value):
        """ Set phase terminal count """
        self["fpga1.pps_manager.sync_tc.cnt_1_pulse"] = value
        self["fpga2.pps_manager.sync_tc.cnt_1_pulse"] = value

    @connected
    def get_pps_delay(self):
        """ Get delay between PPS and 20 MHz clock """
        return self["fpga1.pps_manager.sync_phase.cnt_hf_pps"]

    @connected
    def wait_pps_event(self):
        """ Wait for a PPS edge """
        t0 = self.get_fpga_time(Device.FPGA_1)
        while t0 == self.get_fpga_time(Device.FPGA_1):
            pass

    @connected
    def check_pending_data_requests(self):
        """ Checks whether there are any pending data requests """
        return (self["fpga1.lmc_gen.request"] + self["fpga2.lmc_gen.request"]) > 0

    #######################################################################################

    @connected
    def set_channeliser_truncation(self, trunc):
        """ Set channeliser truncation scale """
        if 0 > trunc or trunc > 7:
            logging.warn("Could not set channeliser truncation to %d, setting to 0" % trunc)
            trunc = 0
        trunc_vec = 256 * [trunc]

        for i in range(32):
            self['fpga1.channelizer.block_sel'] = i
            self['fpga1.channelizer.rescale_data'] = trunc_vec
            self['fpga2.channelizer.block_sel'] = i
            self['fpga2.channelizer.rescale_data'] = trunc_vec
            
    @connected
    def set_time_delays(self, delays):
        """ Set coarse zenith delay for input ADC streams
            Delay specified in nanoseconds, nominal is 0.
            Delay in samples, positive delay adds delay to the signal stream """
        
        # Compute maximum and minimum delay
        frame_length = (1.0 / self._sampling_rate) * 1e9
        min_delay =  frame_length * -124
        max_delay = frame_length * 127
        
        logging.info("frame_length = {} , min_delay = {} , max_delay = {}".format(frame_length,min_delay,max_delay))

        # Check that we have the correct numnber of delays (one or 16)
        if type(delays) in [float, int]:
            # Check that we have a valid delay
            if min_delay <= delays  <= max_delay:
                # possible problem to fix here :
#                delays_hw = [int(round(delays / frame_length))] * 32
                # Test from Riccardo :
                delays_hw = [int(round(old_div(delays, frame_length)) + 128)] * 32
            else:
                logging.warning("Specified delay {} out of range [{:.2f}, {:.2f}], skipping".format(delays, min_delay, max_delay))
                return False

        elif type(delays) is list and len(delays) == 32:
            # Check that all delays are valid
            delays = np.array(delays, dtype=np.float)
            if np.all(min_delay <= delays) and np.all(delays <= max_delay):
                delays_hw = np.clip((np.round(old_div(delays, frame_length)) + 128).astype(np.int), 4, 255).tolist()
            else:
                logging.warning("Specified delays {} out of range [{:.2f}, {:.2f}], skipping".format(delays, min_delay, max_delay))
                return False

        else:
            logging.warning("Invalid delays specfied (must be a number of list of numbers of length 32)")
            return False
            
        logging.info("Setting hardware delays = {}".format(delays_hw))

        # Write delays to board
        self['fpga1.test_generator.delay_0'] = delays_hw[:16]
        self['fpga2.test_generator.delay_0'] = delays_hw[16:]
        return True    

    # ---------------------------- Pointing and calibration routines ---------------------------
    def initialise_beamformer(self, start_channel, nof_channels, is_first, is_last):
        """ Initialise tile and station beamformers """
        self.tpm.beamf_fd[0].initialise_beamf()
        self.tpm.beamf_fd[1].initialise_beamf()
        self.tpm.beamf_fd[0].set_regions([[start_channel, nof_channels, 0]])
        self.tpm.beamf_fd[1].set_regions([[start_channel, nof_channels, 0]])
        self.tpm.beamf_fd[0].antenna_tapering = ([1.0] * 8)
        self.tpm.beamf_fd[1].antenna_tapering = ([1.0] * 8)
        self.tpm.beamf_fd[0].compute_calibration_coefs()
        self.tpm.beamf_fd[1].compute_calibration_coefs()

        # Interface towards beamformer in FPGAs
        self.tpm.station_beamf[0].initialize()
        self.tpm.station_beamf[1].initialize()
        self.set_first_last_tile(is_first, is_last)
        self.tpm.station_beamf[0].defineChannelTable([[start_channel, nof_channels, 0]])
        self.tpm.station_beamf[1].defineChannelTable([[start_channel, nof_channels, 0]])

    def set_beamformer_regions(self, region_array):
        """ Set frequency regions.
            Regions are defined in a 2-d array, for a maximum of 16 regions.
            Each element in the array defines a region, with
            the form [start_ch, nof_ch, beam_index]
            - start_ch:    region starting channel (currently must be a
                           multiple of 2, LS bit discarded)
            - nof_ch:      size of the region: must be multiple of 8 chans
            - beam_index:  beam used for this region, range [0:8)
            Total number of channels must be <= 384
            The routine computes the arrays beam_index, region_off, region_sel,
            and the total number of channels nof_chans, and programs it in the HW"""
        self.tpm.beamf_fd[0].set_regions(region_array)
        self.tpm.beamf_fd[1].set_regions(region_array)
        self.tpm.station_beamf[0].defineChannelTable(region_array)
        self.tpm.station_beamf[1].defineChannelTable(region_array)

    def set_pointing_delay(self, delay_array, beam_index):
        """ The method specifies the delay in seconds and the delay rate in seconds/seconds.
            The delay_array specifies the delay and delay rate for each antenna.
            beam_index specifies which beam is described (range 0:7).
            Delay is updated inside the delay engine at the time specified
            by method load_delay"""
        self.tpm.beamf_fd[0].set_delay(delay_array[0:8], beam_index)
        self.tpm.beamf_fd[1].set_delay(delay_array[8:], beam_index)

    def load_pointing_delay(self, load_time=0):
        """ Delay is updated inside the delay engine at the time specified """
        if load_time == 0:
            load_time = self.current_tile_beamformer_frame() + 64

        self.tpm.beamf_fd[0].load_delay(load_time)
        self.tpm.beamf_fd[1].load_delay(load_time)

    def load_calibration_coefficients(self, antenna, calibration_coefs):
        """Loads calibration coefficients.
           calibration_coefs is a bi-dimensional complex array of the form
           calibration_coefs[channel, polarization], with each element representing
           a normalized coefficient, with (1.0, 0.0) the normal, expected response for
           an ideal antenna.
           Channel is the index specifying the channels at the beamformer output,
           i.e. considering only those channels actually processed and beam assignments.
           The polarization index ranges from 0 to 3.
           0: X polarization direct element
           1: X->Y polarization cross element
           2: Y->X polarization cross element
           3: Y polarization direct element
           The calibration coefficients may include any rotation matrix (e.g.
           the parallitic angle), but do not include the geometric delay. """
        if antenna < 8:
            self.tpm.beamf_fd[0].load_calibration(antenna, calibration_coefs)
        else:
            self.tpm.beamf_fd[1].load_calibration(antenna - 8, calibration_coefs)

    def load_antenna_tapering(self, tapering_coefs):
        """ tapering_coefs is a vector of 16 values, one per antenna.
           Default (at initialization) is 1.0"""
        self.tpm.beamf_fd[0].load_antenna_tapering(tapering_coefs[0:8])
        self.tpm.beamf_fd[1].load_antenna_tapering(tapering_coefs[8:])

    def load_beam_angle(self, angle_coefs):
        """ Angle_coeffs is an array of one element per beam, specifying a rotation
           angle, in radians, for the specified beam. The rotation is the same
           for all antennas. Default is 0 (no rotation).
           A positive pi/4 value transfers the X polarization to the Y polarization.
           The rotation is applied after regular calibration.
           Rot_matrix[beam] then contains the rotation matrix of each beam"""
        self.tpm.beamf_fd[0].load_beam_angle(angle_coefs)
        self.tpm.beamf_fd[1].load_beam_angle(angle_coefs)

    def compute_calibration_coefficients(self):
        """Compute the calibration coefficients and load them in the hardware."""
        self.tpm.beamf_fd[0].compute_calibration_coefs()
        self.tpm.beamf_fd[1].compute_calibration_coefs()

    def switch_calibration_bank(self, switch_time=0):
        if switch_time == 0:
            switch_time = self.current_tile_beamformer_frame() + 64

        self.tpm.beamf_fd[0].switch_calibration_bank(switch_time)
        self.tpm.beamf_fd[1].switch_calibration_bank(switch_time)

    def set_beamformer_epoch(self, epoch):
        """ Set the Unix epoch in seconds since Unix reference time"""
        ret1 = self.tpm.station_beamf[0].set_epoch(epoch)
        ret2 = self.tpm.station_beamf[1].set_epoch(epoch)
        return ret1 and ret2

    def set_csp_rounding(self, rounding):
        """ Set output rounding for CSP """
        ret1 = self.tpm.station_beamf[0].set_csp_rounding(rounding)
        ret2 = self.tpm.station_beamf[1].set_csp_rounding(rounding)
        return ret1 and ret2

    def current_station_beamformer_frame(self):
        """ Return current frame, in units of 256 ADC frames (276,48 us)"""
        return self.tpm.station_beamf[0].current_frame()

    def current_tile_beamformer_frame(self):
        """ Return current frame, in units of 256 ADC frames (276,48 us)"""
        return self.tpm.beamf_fd[0].current_frame()

    def set_first_last_tile(self, is_first, is_last):
        """ Defines if a tile is first, last, both or intermediate
            Parameters: isFirst, isLast, boolean
            One, and only one tile must be first, and last, in a chain
            A tile can be both (one tile chain), or none """
        ret1 = self.tpm.station_beamf[0].set_first_last_tile(is_first, is_last)
        ret2 = self.tpm.station_beamf[1].set_first_last_tile(is_first, is_last)
        return ret1 and ret2

    def define_spead_header(self, station_id, subarray_id, nof_antennas, ref_epoch=-1, start_time=0):
        """ Define_spead_header() used to define SPEAD header for last tile
            requires stationId, subarrayId and numAntennas from LMC
            refEpoch = -1 (default) uses value already defined ib set_epoch()
            startTime (in seconds): offset from frame time, default 0 """
        ret1 = self.tpm.station_beamf[0].define_spead_header(station_id, subarray_id, nof_antennas, ref_epoch,
                                                             start_time)
        ret2 = self.tpm.station_beamf[1].define_spead_header(station_id, subarray_id, nof_antennas, ref_epoch,
                                                             start_time)
        return ret1 and ret2

    def beamformer_is_running(self):
        """ Check if station beamformer is running """
        return self.tpm.station_beamf[0].is_running()

    def start_beamformer(self, start_time=0, duration=-1):
        """ Start the beamformer.
        Duration: if > 0 is a duration in frames * 256 (276.48 us)
        if == -1 run forever"""

        if self.beamformer_is_running():
            return False

        if start_time == 0:
            start_time = self.current_station_beamformer_frame() + 40

        start_time &= 0xfffffff8  # Impose a start time multiple of 8 frames

        if duration != -1:
            duration = (duration & 0xfffffff8)

        ret1 = self.tpm.station_beamf[0].start(start_time, duration)
        ret2 = self.tpm.station_beamf[1].start(start_time, duration)

        if ret1 and ret2:
            return True
        else:
            self.abort()

        return False

    def stop_beamformer(self):
        """ Stop beamformer """
        self.tpm.station_beamf[0].abort()
        self.tpm.station_beamf[1].abort()
        return True

    # ---------------------------- Synchronisation routines ------------------------------------
    @connected
    def post_synchronisation(self):
        """ Post tile configuration synchronization """

        self.wait_pps_event()

        current_tc = self.get_phase_terminal_count()
        delay = self.get_pps_delay()

        self.set_phase_terminal_count(self.calculate_delay(delay, current_tc, 16, 24))

        self.wait_pps_event()

        delay = self.get_pps_delay()
        logging.info("Finished tile post synchronisation ({})".format(delay))

    @connected
    def sync_fpgas(self):
        devices = ["fpga1", "fpga2"]

        for f in devices:
            self.tpm['%s.pps_manager.pps_gen_tc' % f] = old_div(int(self._sampling_rate), 4) - 1

        # Setting sync time
        for f in devices:
            self.tpm["%s.pps_manager.curr_time_write_val" % f] = int(time.time())

        # sync time write command
        for f in devices:
            self.tpm["%s.pps_manager.curr_time_cmd.wr_req" % f] = 0x1

        self.check_synchronization()

    @connected
    def check_synchronization(self):
        t0, t1, t2 = 0, 0, 1
        while t0 != t2:
            t0 = self.tpm["fpga1.pps_manager.curr_time_read_val"]
            t1 = self.tpm["fpga2.pps_manager.curr_time_read_val"]
            t2 = self.tpm["fpga1.pps_manager.curr_time_read_val"]

        fpga = "fpga1" if t0 > t1 else "fpga2"
        for i in range(abs(t1 - t0)):
            logging.debug("Decrementing %s by 1" % fpga)
            self.tpm["%s.pps_manager.curr_time_cmd.down_req" % fpga] = 0x1

    @connected
    def check_fpga_synchronization(self):
        # check PLL status
        pll_status = self.tpm['pll', 0x508]
        if pll_status == 0xE7:
            logging.debug("PLL locked to external reference clock.")
        elif pll_status == 0xF2:
            logging.warning("PLL locked to internal reference clock.")
        else:
            logging.error("PLL is not locked!")

        # check PPS detection
        if self.tpm["fpga1.pps_manager.pps_detected"] == 0x1:
            logging.debug("FPGA1 is locked to external PPS")
        else:
            logging.warning("FPGA1 is not locked to external PPS")
        if self.tpm["fpga2.pps_manager.pps_detected"] == 0x1:
            logging.debug("FPGA2 is locked to external PPS")
        else:
            logging.warning("FPGA2 is not locked to external PPS")

        # check FPGA time
        self.wait_pps_event()
        t0 = self.tpm["fpga1.pps_manager.curr_time_read_val"]
        t1 = self.tpm["fpga2.pps_manager.curr_time_read_val"]
        logging.debug("FPGA1 time is " + str(t0))
        logging.debug("FPGA2 time is " + str(t1))
        if t0 != t1:
            logging.warning("Time different between FPGAs detected!")

        # check FPGA timestamp
        t0 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        t1 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        logging.info("FPGA1 timestamp is " + str(t0))
        logging.info("FPGA2 timestamp is " + str(t1))
        if abs(t0 - t1) > 1:
            logging.warning("Timestamp different between FPGAs detected!")

        # Check FPGA ring beamfomrer timestamp
        t0 = self.tpm["fpga1.beamf_ring.current_frame"]
        t1 = self.tpm["fpga2.beamf_ring.current_frame"]
        logging.info("FPGA1 beamformer timestamp is " + str(t0))
        logging.info("FPGA2 beamformer timestamp is " + str(t1))
        if abs(t0 - t1) > 1:
            logging.warning("Beamformer timestamp different between FPGAs detected!")

    @connected
    def set_c2c_burst(self):
        # Setting C2C burst when supported by FPGAs and CPLD
        self.tpm['fpga1.regfile.c2c_stream_ctrl.idle_val'] = 0
        self.tpm['fpga2.regfile.c2c_stream_ctrl.idle_val'] = 0
        try:
            fpga_burst_supported = self.tpm['fpga1.regfile.feature.c2c_linear_burst']
        except:
            fpga_burst_supported = 0
        try:
            self.tpm['board.regfile.c2c_ctrl.mm_burst_enable'] = 0
            cpld_burst_supported = 1
        except:
            cpld_burst_supported = 0

        if cpld_burst_supported == 1 and fpga_burst_supported == 1:
            self.tpm['board.regfile.c2c_ctrl.mm_burst_enable'] = 1
            logging.debug("C2C burst activated.")
            return
        if fpga_burst_supported == 0:
            logging.debug("C2C burst is not supported by FPGAs.")
        if cpld_burst_supported == 0:
            logging.debug("C2C burst is not supported by CPLD.")

    @connected
    def synchronised_data_operation(self, seconds=0.2, timestamp=None):
        """ Synchronise data operations between FPGAs
         :param seconds: Number of seconds to delay operation
         :param timestamp: Timestamp at which tile will be synchronised"""

        # Wait while previous data requests are processed
        while self.tpm['fpga1.lmc_gen.request'] != 0 or self.tpm['fpga2.lmc_gen.request'] != 0:
            logging.info("Waiting for enable to be reset")
            time.sleep(2)

        # Read timestamp
        if timestamp is not None:
            t0 = timestamp
        else:
            t0 = max(self.tpm["fpga1.pps_manager.timestamp_read_val"],
                     self.tpm["fpga2.pps_manager.timestamp_read_val"])

        # Set arm timestamp
        # delay = number of frames to delay * frame time (shift by 8)
        delay = seconds * (old_div(old_div(1, (1080 * 1e-9)), 256))
        for fpga in self.tpm.tpm_fpga:
            fpga.fpga_apply_sync_delay(t0 + int(delay))

    @connected
    def synchronised_beamformer_coefficients(self, timestamp=None, seconds=0.2):
        """ Synchronise beamformer coefficients download
        :param timestamp: Timestamp to synchronise against
        :param seconds: Number of seconds to delay operation """

        # Read timestamp
        if timestamp is None:
            t0 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        else:
            t0 = timestamp

        # Set arm timestamp
        # delay = number of frames to delay * frame time (shift by 8)
        delay = seconds * (old_div(old_div(1, (1080 * 1e-9)), 256))
        for f in ["fpga1", "fpga2"]:
            self.tpm["%s.beamf.timestamp_req" % f] = t0 + int(delay)

    @connected
    def configure_integrated_channel_data(self, integration_time=0.5):
        """ Configure continuous integrated channel data """
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].configure("channel", integration_time, first_channel=0, last_channel=512,
                                                 time_mux_factor=2, carousel_enable=0x1)

    @connected
    def configure_integrated_beam_data(self, integration_time=0.5):
        """ Configure continuous integrated beam data """
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].configure("beamf", integration_time, first_channel=0, last_channel=192,
                                                 time_mux_factor=1, carousel_enable=0x0)

    @connected
    def stop_integrated_beam_data(self):
        """ Stop transmission of integrated beam data"""
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].stop_integrated_beam_data()

    @connected
    def stop_integrated_channel_data(self):
        """ Stop transmission of integrated beam data"""
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].stop_integrated_channel_data()

    @connected
    def stop_integrated_data(self):
        """ Stop transmission of integrated data"""
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].stop_integrated_data()

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
            for station_beamformer in self.tpm.station_beamf:
                station_beamformer.set_epoch(sync_time)
            self.tpm['%s.pps_manager.sync_time_val' % f] = sync_time

    # ---------------------------- Wrapper for data acquisition: RAW ------------------------------------
    def _send_raw_data(self, sync=False, period=0, timestamp=None, seconds=0.2):
        """ Repeatedly send raw data from the TPM
        :param sync: Get synchronised packets
        :param period: Period in seconds
        """
        # Loop indefinitely if a period is defined
        while self._daq_threads['RAW'] != self._STOP:
            # Data transmission should be synchronised across FPGAs
            self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)

            # Send data from all FPGAs
            for i in range(len(self.tpm.tpm_test_firmware)):
                if sync:
                    self.tpm.tpm_test_firmware[i].send_raw_data_synchronised()
                else:
                    self.tpm.tpm_test_firmware[i].send_raw_data()

            # Period should be >= 2, otherwise return
            if self._daq_threads['RAW'] == self._ONCE:
                return

            # Sleep for defined period
            time.sleep(period)

        # Finished looping, exit
        self._daq_threads.pop('RAW')

    @connected
    def send_raw_data(self, sync=False, period=0, timeout=0, timestamp=None, seconds=0.2):
        """ Send raw data from the TPM
        :param sync: Synchronised flag
        :param period: Period in seconds
        :param timeout: Timeout in seconds
        :param timestamp: When to start
        :param seconds: Period"""
        # Period sanity check
        if period < 1:
            self._daq_threads['RAW'] = self._ONCE
            self._send_raw_data(sync, timestamp=timestamp, seconds=seconds)
            self._daq_threads.pop('RAW')
            return

        # Stop any other streams
        self.stop_data_transmission()

        # Create thread which will continuously send raw data
        t = threading.Thread(target=self._send_raw_data, args=(sync, period, timestamp, seconds))
        self._daq_threads['RAW'] = self._RUNNING
        t.start()

        # If period, and timeout specified, schedule stop transmission
        if period > 0 and timeout > 0:
            self.schedule_stop_data_transmission(timeout)

    @connected
    def send_raw_data_synchronised(self, period=0, timeout=0, timestamp=None, seconds=0.2):
        """  Send synchronised raw data
        :param period: Period in seconds
        :param timeout: Timeout in seconds
        :param timestamp: When to start
        :param seconds: Period"""
        self.send_raw_data(sync=True, period=period, timeout=timeout,
                           timestamp=timestamp, seconds=seconds)

    def stop_raw_data(self):
        """ Stop sending raw data """
        if 'RAW' in list(self._daq_threads.keys()):
            self._daq_threads['RAW'] = self._STOP

    # ---------------------------- Wrapper for data acquisition: CHANNEL ------------------------------------
    def _send_channelised_data(self, number_of_samples=128, first_channel=0, last_channel=511, timestamp=None, seconds=0.2, period=0):
        """ Send channelized data from the TPM
        :param number_of_samples: Number of samples to send
        :param timestamp: When to start
        :param seconds: When to synchronise """

        # Loop indefinitely if a period is defined
        while self._daq_threads['CHANNEL'] != self._STOP:
            # Data transmission should be synchronised across FPGAs
            self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)

            # Send data from all FPGAs
            for i in range(len(self.tpm.tpm_test_firmware)):
                self.tpm.tpm_test_firmware[i].send_channelised_data(number_of_samples, first_channel, last_channel)

            # Period should be >= 2, otherwise return
            if self._daq_threads['CHANNEL'] == self._ONCE:
                return

            # Sleep for defined period
            time.sleep(period)

        # Finished looping, exit
        self._daq_threads.pop('CHANNEL')

    @connected
    def send_channelised_data(self, number_of_samples=128, first_channel=0, last_channel=511, period=0,
                              timeout=0, timestamp=None, seconds=0.2):
        """ Send channelised data from the TPM
        :param number_of_samples: Number of spectra to send
        :param first_channel: First channel to send
        :param last_channel: Last channel to send
        :param timeout: Timeout to stop transmission
        :param timestamp: When to start transmission
        :param seconds: When to synchronise
        :param period: Period in seconds to send data """

        # Check if number of samples is a multiple of 32
        if number_of_samples % 32 != 0:
            new_value = (int(old_div(number_of_samples, 32)) + 1) * 32
            logging.warn("{} is not a multiple of 32, using {}".format(number_of_samples, new_value))
            number_of_samples = new_value

        # Period sanity check
        if period < 1:
            self._daq_threads['CHANNEL'] = self._ONCE
            self._send_channelised_data(number_of_samples, first_channel, last_channel, timestamp, seconds, period=0)
            self._daq_threads.pop('CHANNEL')
            return

        # Stop any other streams
        self.stop_data_transmission()

        # Create thread which will continuously send raw data
        t = threading.Thread(target=self._send_channelised_data, args=(number_of_samples, first_channel, last_channel,
                                                                       timestamp, seconds, period))
        self._daq_threads['CHANNEL'] = self._RUNNING
        t.start()

        # If period, and timeout specified, schedule stop transmission
        if period > 0 and timeout > 0:
            self.schedule_stop_data_transmission(timeout)

    def stop_channelised_data(self):
        """ Stop sending channelised data """
        if 'CHANNEL' in list(self._daq_threads.keys()):
            self._daq_threads['CHANNEL'] = self._STOP

    # ---------------------------- Wrapper for data acquisition: BEAM ------------------------------------
    def _send_beam_data(self, period=0, timestamp=None, seconds=0.2):
        """ Send beam data from the TPM
        :param period: Period in seconds to send data """

        # Loop indefinitely if a period is defined
        while self._daq_threads['BEAM'] != self._STOP:

            # Data transmission should be syncrhonised across FPGAs
            self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)

            # Send data from all FPGAs
            for i in range(len(self.tpm.tpm_test_firmware)):
                self.tpm.tpm_test_firmware[i].send_beam_data()

            # Period should be >= 2, otherwise return
            if self._daq_threads['BEAM'] == self._ONCE:
                return

            # Sleep for defined period
            time.sleep(period)

        # Finished looping, exit
        self._daq_threads.pop('BEAM')

    @connected
    def send_beam_data(self, period=0, timeout=0, timestamp=None, seconds=0.2):
        """ Send beam data from the TPM
        :param period: Period in seconds to send data
        :param timeout: When to stop
        :param timestamp: When to send
        :param seconds: When to synchronise"""
        # Period sanity check

        # Stop any other streams
        self.stop_data_transmission()

        if period < 1:
            self._daq_threads['BEAM'] = self._ONCE
            self._send_beam_data(timestamp=timestamp, seconds=seconds)
            self._daq_threads.pop('BEAM')
            return

        # Create thread which will continuously send raw data
        t = threading.Thread(target=self._send_beam_data, args=(period, timestamp, seconds))
        self._daq_threads['BEAM'] = self._RUNNING
        t.start()

        # If period, and timeout specified, schedule stop transmission
        if period > 0 and timeout > 0:
            self.schedule_stop_data_transmission(timeout)

    def stop_beam_data(self):
        """ Stop sending raw data """
        if 'BEAM' in list(self._daq_threads.keys()):
            self._daq_threads['BEAM'] = self._STOP

    # ---------------------------- Wrapper for data acquisition: CONT CHANNEL ----------------------------
    @connected
    def send_channelised_data_continuous(self, channel_id, number_of_samples=128, wait_seconds=0,
                                         timeout=0, timestamp=None, seconds=0.2):
        """ Continuously send channelised data from a single channel
        :param channel_id: Channel ID
        :param number_of_samples: Number of spectra to send
        :param wait_seconds: Wait time before sending data
        :param timeout: When to stop
        :param timestamp: When to start
        :param seconds: When to synchronise
        """
        time.sleep(wait_seconds)
        self.stop_data_transmission()
        self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)
        for i in range(len(self.tpm.tpm_test_firmware)):
            self.tpm.tpm_test_firmware[i].send_channelised_data_continuous(channel_id, number_of_samples)
        self.schedule_stop_data_transmission(timeout)

# ---------------------------- Wrapper for data acquisition: NARROWBAND CHANNEL ----------------------------
    @connected
    def send_channelised_data_narrowband(self, frequency, round_bits, number_of_samples=128, wait_seconds=0,
                                         timeout=0, timestamp=None, seconds=0.2):
        """ Continuously send channelised data from a single channel
        :param frequency: Sky frequency to transmit
        :param round_bits: Specify which bits to round
        :param number_of_samples: Number of spectra to send
        :param wait_seconds: Wait time before sending data
        :param timeout: When to stop
        :param timestamp: When to start
        :param seconds: When to synchronise
        """
        time.sleep(wait_seconds)
        self.stop_data_transmission()
        self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)
        for i in range(len(self.tpm.tpm_test_firmware)):
            self.tpm.tpm_test_firmware[i].send_channelised_data_narrowband(frequency, round_bits, number_of_samples)
        self.schedule_stop_data_transmission(timeout)

    def stop_channelised_data_continuous(self):
        """ Stop sending channelised data """
        for i in range(len(self.tpm.tpm_test_firmware)):
            self.tpm.tpm_test_firmware[i].stop_channelised_data_continuous()

    def schedule_stop_data_transmission(self, timeout=0):
        """ Schedule a stop all data transmission operation if timeout is specified
        :param timeout: Timeout value
        """
        if timeout <= 0:
            return

        timer = threading.Timer(timeout, self.stop_data_transmission)
        timer.start()

    @connected
    def stop_data_transmission(self):
        """ Stop all data transmission from TPM"""

        logging.info("Stopping all transmission")
        for k, v in self._daq_threads.items():
            if v == self._RUNNING:
                self._daq_threads[k] = self._STOP
        self.stop_channelised_data_continuous()

    @staticmethod
    def calculate_delay(current_delay, current_tc, ref_low, ref_hi):
        """ Calculate delay
        :param current_delay: Current delay
        :param current_tc: Current phase register terminal count
        :param ref_low: Low reference
        :param ref_hi: High reference """

        for n in range(5):
            if current_delay <= ref_low:
                new_delay = current_delay + old_div(n * 40, 5)
                new_tc = (current_tc + n) % 5
                if new_delay >= ref_low:
                    return new_tc
            elif current_delay >= ref_hi:
                new_delay = current_delay - old_div(n * 40, 5)
                new_tc = current_tc - n
                if new_tc < 0:
                    new_tc += 5
                if new_delay <= ref_hi:
                    return new_tc
            else:
                return current_tc

    # ---------------------------- Wrapper for test generator ----------------------------

    def test_generator_set_tone(self, dds, frequency=100e6, ampl=0.0, phase=0.0, delay=128):
        t0 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        self.tpm.test_generator[0].set_tone(dds, frequency, ampl, phase, t0 + delay)
        self.tpm.test_generator[1].set_tone(dds, frequency, ampl, phase, t0 + delay)
        t1 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        if t1 >= t0 + delay or t1 <= t0:
            logging.info("Set tone test pattern generators synchronisation failed.")
            logging.info("Start Time   = " + str(t0))
            logging.info("Finish time  = " + str(t1))
            logging.info("Maximum time = " + str(t0+delay))
            return -1
        return 0

    def test_generator_disable_tone(self, dds, delay=128):
        t0 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        self.tpm.test_generator[0].set_tone(dds, 0, 0, 0, t0 + delay)
        self.tpm.test_generator[1].set_tone(dds, 0, 0, 0, t0 + delay)
        t1 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        if t1 >= t0 + delay or t1 <= t0:
            logging.info("Set tone test pattern generators synchronisation failed.")
            logging.info("Start Time   = " + str(t0))
            logging.info("Finish time  = " + str(t1))
            logging.info("Maximum time = " + str(t0+delay))
            return -1
        return 0

    def test_generator_set_noise(self, ampl=0.0, delay=128):
        t0 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        self.tpm.test_generator[0].enable_prdg(ampl, t0 + delay)
        self.tpm.test_generator[1].enable_prdg(ampl, t0 + delay)
        t1 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        if t1 >= t0 + delay or t1 <= t0:
            logging.info("Set tone test pattern generators synchronisation failed.")
            logging.info("Start Time   = " + str(t0))
            logging.info("Finish time  = " + str(t1))
            logging.info("Maximum time = " + str(t0+delay))
            return -1
        return 0

    def test_generator_input_select(self, inputs):
        self.tpm.test_generator[0].channel_select(inputs & 0xFFFF)
        self.tpm.test_generator[1].channel_select((inputs >> 16) & 0xFFFF)

    def __str__(self):
        return str(self.tpm)

    def __getitem__(self, key):
        return self.tpm[key]

    def __setitem__(self, key, value):
        self.tpm[key] = value

    def __getattr__(self, name):
        if name in dir(self.tpm):
            return getattr(self.tpm, name)
        else:
            raise AttributeError("'Tile' or 'TPM' object have no attribute {}".format(name))


if __name__ == "__main__":
    tile = Tile(ip="10.0.10.2", port=10000)
    tile.connect()