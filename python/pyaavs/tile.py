# type: ignore
# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
#
# Distributed under the terms of the GPL license.
# See LICENSE.txt for more info.
"""
Hardware functions for the TPM 1.2 hardware.
"""
import functools
import logging
import socket
import numpy as np
import time
import math
import os
from ipaddress import IPv4Address

from pyfabil.base.definitions import Device, LibraryError, BoardError, Status
from pyfabil.base.utils import ip2long
from pyfabil.boards.tpm import TPM

from pyaavs.tile_health_monitor import TileHealthMonitor


# Helper to disallow certain function calls on unconnected tiles
def connected(f):
    """
    Helper to disallow certain function calls on unconnected tiles.

    :param f: the method wrapped by this helper
    :type f: callable

    :return: the wrapped method
    :rtype: callable
    """

    @functools.wraps(f)
    def wrapper(self, *args, **kwargs):
        """
        Wrapper that checks the TPM is connected before allowing the wrapped method to
        proceed.

        :param self: the method called
        :type self: object
        :param args: positional arguments to the wrapped method
        :type args: list
        :param kwargs: keyword arguments to the wrapped method
        :type kwargs: dict

        :raises LibraryError: if the TPM is not connected

        :return: whatever the wrapped method returns
        :rtype: object
        """
        if self.tpm is None:
            self.logger.warning(
                "Cannot call function " + f.__name__ + " on unconnected TPM"
            )
            raise LibraryError(
                "Cannot call function " + f.__name__ + " on unconnected TPM"
            )
        else:
            return f(self, *args, **kwargs)

    return wrapper


class Tile(TileHealthMonitor):
    """
    Tile hardware interface library.
    """

    def __init__(
        self,
        ip="10.0.10.2",
        port=10000,
        lmc_ip="10.0.10.1",
        lmc_port=4660,
        sampling_rate=800e6,
        logger=None,
    ):
        """
        Initialise a new Tile12 instance.

        :param logger: the logger to be used by this Command. If not
                provided, then a default module logger will be used.
        :type logger: :py:class:`logging.Logger`
        :param ip: IP address of the hardware
        :type ip: str
        :param port: UCP Port address of the hardware port
        :type port: int
        :param lmc_ip: IP address of the MCCS DAQ recevier
        :type lmc_ip: str
        :param lmc_port: UCP Port address of the MCCS DAQ receiver
        :type lmc_port: int
        :param sampling_rate: ADC sampling rate
        :type sampling_rate: float
        """
        if logger is None:
            self.logger = logging.getLogger("")
        else:
            self.logger = logger
        self._lmc_port = lmc_port
        self._lmc_ip = socket.gethostbyname(lmc_ip)
        self._arp_table = {}
        self._40g_configuration = {}
        self._port = port
        self._ip = socket.gethostbyname(ip)
        self.tpm = None

        self._channeliser_truncation = 4
        self.subarray_id = 0
        self.station_id = 0
        self.tile_id = 0

        self._sampling_rate = sampling_rate

        self.preadu_signal_map = {0: {'preadu_id': 1, 'channel': 14},
                                  1: {'preadu_id': 1, 'channel': 15},
                                  2: {'preadu_id': 1, 'channel': 12},
                                  3: {'preadu_id': 1, 'channel': 13},
                                  4: {'preadu_id': 1, 'channel': 10},
                                  5: {'preadu_id': 1, 'channel': 11},
                                  6: {'preadu_id': 1, 'channel': 8},
                                  7: {'preadu_id': 1, 'channel': 9},
                                  8: {'preadu_id': 0, 'channel': 0},
                                  9: {'preadu_id': 0, 'channel': 1},
                                  10: {'preadu_id': 0, 'channel': 2},
                                  11: {'preadu_id': 0, 'channel': 3},
                                  12: {'preadu_id': 0, 'channel': 4},
                                  13: {'preadu_id': 0, 'channel': 5},
                                  14: {'preadu_id': 0, 'channel': 6},
                                  15: {'preadu_id': 0, 'channel': 7},
                                  16: {'preadu_id': 1, 'channel': 6},
                                  17: {'preadu_id': 1, 'channel': 7},
                                  18: {'preadu_id': 1, 'channel': 4},
                                  19: {'preadu_id': 1, 'channel': 5},
                                  20: {'preadu_id': 1, 'channel': 2},
                                  21: {'preadu_id': 1, 'channel': 3},
                                  22: {'preadu_id': 1, 'channel': 0},
                                  23: {'preadu_id': 1, 'channel': 1},
                                  24: {'preadu_id': 0, 'channel': 8},
                                  25: {'preadu_id': 0, 'channel': 9},
                                  26: {'preadu_id': 0, 'channel': 10},
                                  27: {'preadu_id': 0, 'channel': 11},
                                  28: {'preadu_id': 0, 'channel': 12},
                                  29: {'preadu_id': 0, 'channel': 13},
                                  30: {'preadu_id': 0, 'channel': 14},
                                  31: {'preadu_id': 0, 'channel': 15}}
                                  
        self.init_health_monitoring()
        self.daq_modes_with_timestamp_flag = ["raw_adc_mode", "channelized_mode", "beamformed_mode"]

    # ---------------------------- Main functions ------------------------------------
    def tpm_version(self):
        """
        Determine whether this is a TPM V1.2 or TPM V1.6
        :return: TPM hardware version
        :rtype: string
        """
        return "tpm_v1_2"

    @property
    def info(self):
        communication_status = self.check_communication()
        if not communication_status["CPLD"]:
            raise BoardError(f"Bard communication error, unable to get health status. Check communication status and try again.")
        info = {}
        # Populate Hardware portion as provided by Sanitas
        info['hardware'] = self.tpm.get_board_info()
        # Convert EEP information to IPv4Address type
        info['hardware']['ip_address_eep'] = IPv4Address(info['hardware']['ip_address_eep'])
        info['hardware']['netmask_eep'] = IPv4Address(info['hardware']['netmask_eep'])
        info['hardware']['gateway_eep'] = IPv4Address(info['hardware']['gateway_eep'])
        # Populate Firmware Build information from first FPGA
        info['fpga_firmware'] = {}
        info['fpga_firmware']['design'] = self.tpm.tpm_firmware_information[0].get_design()
        info['fpga_firmware']['build'] = self.tpm.tpm_firmware_information[0].get_build()
        info['fpga_firmware']['compile_time'] = self.tpm.tpm_firmware_information[0].get_time()
        info['fpga_firmware']['compile_user'] = self.tpm.tpm_firmware_information[0].get_user()
        info['fpga_firmware']['compile_host'] = self.tpm.tpm_firmware_information[0].get_host()
        info['fpga_firmware']['git_branch'] = self.tpm.tpm_firmware_information[0].get_git_branch()
        info['fpga_firmware']['git_commit'] = self.tpm.tpm_firmware_information[0].get_git_commit()
        # Dictionary manipulation, move 1G network information
        info['network'] = {}
        info['network']['1g_ip_address'] = IPv4Address(info['hardware']['ip_address'])
        info['network']['1g_mac_address'] = info['hardware']['MAC']
        info['network']['1g_netmask'] = IPv4Address(info['hardware']['netmask'])
        info['network']['1g_gateway'] = IPv4Address(info['hardware']['gateway'])
        del info['hardware']['ip_address']
        del info['hardware']['MAC']
        del info['hardware']['netmask']
        del info['hardware']['gateway']
        # Add 40G network information, using ARP table entry for station beam packets
        if communication_status["FPGA0"] and communication_status["FPGA1"]:
            config_40g_1 = self.get_40g_core_configuration(arp_table_entry=0, core_id=0)
            config_40g_2 = self.get_40g_core_configuration(arp_table_entry=0, core_id=1)
            info['network']['40g_ip_address_p1'] = IPv4Address(config_40g_1['src_ip'])
            mac = config_40g_1['src_mac']
            info['network']['40g_mac_address_p1'] = ':'.join(f'{(mac >> (i * 8)) & 0xFF:02X}' for i in reversed(range(6)))
            info['network']['40g_gateway_p1'] = IPv4Address(config_40g_1['gateway_ip'])
            info['network']['40g_netmask_p1'] = IPv4Address(config_40g_1['netmask'])
            info['network']['40g_ip_address_p2']= IPv4Address(config_40g_2['src_ip'])
            mac = config_40g_2['src_mac']
            info['network']['40g_mac_address_p2'] = ':'.join(f'{(mac >> (i * 8)) & 0xFF:02X}' for i in reversed(range(6)))
            info['network']['40g_gateway_p2'] = IPv4Address(config_40g_2['gateway_ip'])
            info['network']['40g_netmask_p2'] = IPv4Address(config_40g_2['netmask'])
        else:
            info['network'].update(dict.fromkeys(['40g_ip_address_p1', '40g_mac_address_p1', '40g_gateway_p1', '40g_netmask_p1', '40g_ip_address_p2', '40g_mac_address_p2', '40g_gateway_p2', '40g_netmask_p2']))
        return info

    def connect(
        self,
        initialise=False,
        load_plugin=True,
        enable_ada=False,
        enable_adc=True,
        dsp_core=True,
        adc_mono_channel_14_bit=False,
        adc_mono_channel_sel=0,
    ):
        """
        Connect to the hardware and loads initial configuration.

        :param initialise: Initialises the TPM object
        :type initialise: bool
        :param load_plugin: loads software plugins
        :type load_plugin: bool
        :param enable_ada: Enable ADC amplifier (usually not present)
        :type enable_ada: bool
        :param enable_adc: Enable ADC
        :type enable_adc: bool
        :param dsp_core: Enable loading of DSP core plugins
        :type dsp_core: bool
        :param adc_mono_channel_14_bit: Enable ADC mono channel 14bit mode
        :type adc_mono_channel_14_bit: bool
        :param adc_mono_channel_sel: Select channel in mono channel mode (0=A, 1=B)
        :type adc_mono_channel_sel: int
        """
        # Try to connect to board, if it fails then set tpm to None
        self.tpm = TPM()

        # Add plugin directory (load module locally)
        tf = __import__("pyaavs.plugins.tpm.tpm_test_firmware", fromlist=[None])
        self.tpm.add_plugin_directory(os.path.dirname(tf.__file__))

        # Connect using tpm object.
        # simulator parameter is used not to load the TPM specific plugins,
        # no actual simulation is performed.
        try:
            self.tpm.connect(
                ip=self._ip,
                port=self._port,
                initialise=initialise,
                simulator=not load_plugin,
                enable_ada=enable_ada,
                enable_adc=enable_adc,
                fsample=self._sampling_rate,
                mono_channel_14_bit=adc_mono_channel_14_bit,
                mono_channel_sel=adc_mono_channel_sel,
            )
        except (BoardError, LibraryError) as e:
            self.tpm = None
            self.logger.error("Failed to connect to board at " + self._ip)
            self.logger.error("Exception: " + str(e))
            return

        # Load tpm test firmware for both FPGAs (no need to load in simulation)
        if load_plugin and self.tpm.is_programmed():
            for device in [Device.FPGA_1, Device.FPGA_2]:
                self.tpm.load_plugin(
                    "TpmTestFirmware",
                    device=device,
                    fsample=self._sampling_rate,
                    dsp_core=dsp_core,
                    logger=self.logger,
                )
        elif not self.tpm.is_programmed():
            self.logger.warning("TPM is not programmed! No plugins loaded")

    def is_programmed(self):
        """
        Check whether the TPM is connected and programmed.

        :return: If the TPM is programmed
        :rtype: bool
        """
        if self.tpm is None:
            return False
        return self.tpm.is_programmed()

    @property
    def active_40g_port(self):
        # If single 40G not supported by firmware both ports must be used
        if not self.tpm.has_register("fpga1.dsp_regfile.config_id.is_master"):
            return [True, True]
        return [
            self.tpm["fpga1.dsp_regfile.config_id.is_master"] > 0,
            self.tpm["fpga2.dsp_regfile.config_id.is_master"] > 0
        ]

    def initialise(self,
                   station_id=0, tile_id=0,
                   lmc_use_40g=False, lmc_dst_ip=None, lmc_dst_port=4660,
                   lmc_integrated_use_40g=False,
                   src_ip_fpga1=None, src_ip_fpga2=None,
                   dst_ip_fpga1=None, dst_ip_fpga2=None,
                   src_port=4661, dst_port=4660, dst_port_single_port_mode=4662, rx_port_single_port_mode=4662,
                   netmask_40g=None, gateway_ip_40g=None,
                   active_40g_ports_setting="port1-only",
                   enable_adc=True,
                   enable_ada=False, enable_test=False, use_internal_pps=False,
                   pps_delay=0,
                   time_delays=0,
                   is_first_tile=False,
                   is_last_tile=False,
                   qsfp_detection="auto",
                   adc_mono_channel_14_bit=False,
                   adc_mono_channel_sel=0):
        """
        Connect and initialise.

        :param station_id: station ID
        :type station_id: int
        :param tile_id: Tile ID in the station
        :type tile_id: int
        :param lmc_use_40g: if True use 40G interface to transmit LMC data, otherwise use 1G
        :type lmc_use_40g: bool
        :param lmc_dst_ip: destination IP address for LMC data packets
        :type lmc_dst_ip: str
        :param lmc_dst_port: destination UDP port for LMC data packets
        :type lmc_dst_port: int
        :param lmc_integrated_use_40g: if True use 40G interface to transmit LMC integrated data, otherwise use 1G
        :type lmc_integrated_use_40g: bool
        :param src_ip_fpga1: source IP address for FPGA1 40G interface
        :type src_ip_fpga1: str
        :param src_ip_fpga2: source IP address for FPGA2 40G interface
        :type src_ip_fpga2: str
        :param dst_ip_fpga1: destination IP address for beamformed data from FPGA1 40G interface
        :type dst_ip_fpga1: str
        :param dst_ip_fpga2: destination IP address for beamformed data from FPGA2 40G interface
        :type dst_ip_fpga2: str
        :param src_port: source UDP port for beamformed data packets
        :type src_port: int
        :param dst_port: destination UDP port for beamformed data packets
        :type dst_port: int
        :param enable_ada: enable adc amplifier, Not present in most TPM versions
        :type enable_ada: bool
        :param enable_adc: Enable ADC
        :type enable_adc: bool
        :param enable_test: setup internal test signal generator instead of ADC
        :type enable_test: bool

        :param use_internal_pps: use internal PPS generator synchronised across FPGAs
        :type use_internal_pps: bool
        :param pps_delay: PPS delay correction in 625ps units
        :type pps_delay: int
        :param time_delays: time domain delays for 32 inputs
        :type time_delays: list(int)
        :param is_first_tile: True if this tile is the first tile in the beamformer chain
        :type is_first_tile: bool
        :param is_last_tile: True if this tile is the last tile in the beamformer chain
        :type is_last_tile: bool
        :param qsfp_detection: "auto" detects QSFP cables automatically,
                               "qsfp1", force QSFP1 cable detected, QSFP2 cable not detected
                               "qsfp2", force QSFP1 cable not detected, QSFP2 cable detected
                               "all", force QSFP1 and QSFP2 cable detected
                               "flyover_test", force QSFP1 and QSFP2 cable detected and adjust
                                polarity for board-to-board cable
                               "none", force no cable not detected
        :type qsfp_detection: str
        :param adc_mono_channel_14_bit: Enable ADC mono channel 14bit mode
        :type adc_mono_channel_14_bit: bool
        :param adc_mono_channel_sel: Select channel in mono channel mode (0=A, 1=B)
        :type adc_mono_channel_sel: int
        """
        # Connect to board
        self.connect(initialise=True, enable_ada=enable_ada, enable_adc=enable_adc,
                     adc_mono_channel_14_bit=adc_mono_channel_14_bit, adc_mono_channel_sel=adc_mono_channel_sel)

        # Before initialing, check if TPM is programmed
        if not self.tpm.is_programmed():
            self.logger.error("Cannot initialise board which is not programmed")
            return

        # Disable debug UDP header
        self['board.regfile.header_config'] = 0x2

        # write PPS delay correction variable into the FPGAs
        if pps_delay < -128 or pps_delay > 127:
            self.logger.error("PPS delay out of range [-128, 127]")
            return
        self["fpga1.pps_manager.sync_tc.cnt_2"] = pps_delay & 0xFF
        self["fpga2.pps_manager.sync_tc.cnt_2"] = pps_delay & 0xFF

        # Initialise firmware plugin
        for firmware in self.tpm.tpm_test_firmware:
            firmware.initialise_firmware()

        # Set station and tile IDs
        self.set_station_id(station_id, tile_id)

        # Set LMC IP
        self.tpm.set_lmc_ip(self._lmc_ip, self._lmc_port)

        # Enable C2C streaming
        self.tpm["board.regfile.c2c_stream_enable"] = 0x1
        self.set_c2c_burst()
        
        # Display Temperature during initialisation
        logging.info(f"Board Temperature - {round(self.get_temperature(), 1)} C")
        
        # Switch off both PREADUs
        for preadu in self.tpm.tpm_preadu:
            preadu.switch_off()

        # Switch on preadu
        for preadu in self.tpm.tpm_preadu:
            preadu.switch_on()
            time.sleep(1)
            preadu.select_low_passband()
            preadu.read_configuration()

        # Synchronise FPGAs
        self.sync_fpga_time(use_internal_pps=use_internal_pps)

        # Initialize f2f link
        self.tpm.tpm_f2f[0].initialise_core("fpga2->fpga1")
        self.tpm.tpm_f2f[1].initialise_core("fpga1->fpga2")

        # AAVS-only - swap polarisations due to remapping performed by preadu
        self.tpm["fpga1.jesd204_if.regfile_pol_switch"] = 0b00001111
        self.tpm["fpga2.jesd204_if.regfile_pol_switch"] = 0b00001111

        # Reset test pattern generator
        for _test_generator in self.tpm.test_generator:
            _test_generator.channel_select(0x0000)
            _test_generator.disable_prdg()

        # Use test_generator plugin instead!
        if enable_test:
            # Test pattern. Tones on channels 72 & 75 + pseudo-random noise
            self.logger.info("Enabling test pattern")
            for generator in self.tpm.test_generator:
                generator.set_tone(0, 72 * self._sampling_rate / 1024, 0.0)
                generator.enable_prdg(0.4)
                generator.channel_select(0xFFFF)

        # Set destination and source IP/MAC/ports for 40G cores
        # This will create a loopback between the two FPGAs
        self.set_default_eth_configuration(
                                           src_ip_fpga1=src_ip_fpga1,
                                           src_ip_fpga2=src_ip_fpga2,
                                           dst_ip_fpga1=dst_ip_fpga1,
                                           dst_ip_fpga2=dst_ip_fpga2,
                                           src_port=src_port,
                                           dst_port=dst_port,
                                           channel2_dst_port=dst_port_single_port_mode,
                                           channel2_rx_port=rx_port_single_port_mode,
                                           netmask_40g=netmask_40g,
                                           gateway_ip_40g=gateway_ip_40g,
                                           qsfp_detection=qsfp_detection)

        for firmware in self.tpm.tpm_test_firmware:
            if not firmware.check_ddr_initialisation():
                firmware.initialise_ddr()

        # Configure standard data streams
        if lmc_use_40g:
            logging.info("Using 10G for LMC traffic")
            self.set_lmc_download("10g", 8192,
                                  dst_ip=lmc_dst_ip,
                                  dst_port=lmc_dst_port,
                                  netmask_40g=netmask_40g,
                                  gateway_ip_40g=gateway_ip_40g)
        else:
            logging.info("Using 1G for LMC traffic")
            self.set_lmc_download("1g")

        # Configure integrated data streams
        if lmc_integrated_use_40g:
            logging.info("Using 10G for integrated LMC traffic")
            self.set_lmc_integrated_download("10g", 1024, 2048,
                                             dst_ip=lmc_dst_ip,
                                             dst_port=lmc_dst_port,
                                             netmask_40g=netmask_40g,
                                             gateway_ip_40g=gateway_ip_40g)
        else:
            logging.info("Using 1G for integrated LMC traffic")
            self.set_lmc_integrated_download("1g", 1024, 2048)

        # Set time delays
        self.set_time_delays(time_delays)

        # set first/last tile flag
        if self.tpm.tpm_test_firmware[0].station_beamformer_implemented:
            for _station_beamf in self.tpm.station_beamf:
                _station_beamf.set_first_last_tile(is_first_tile, is_last_tile)

        # Clear Health Monitoring Following Initialisation
        # Clears any false errors detected from bring-up
        self.enable_health_monitoring()
        self.clear_health_status()

    def program_fpgas(self, bitfile):
        """
        Program both FPGAs with specified firmware.

        :param bitfile: Bitfile to load
        :type bitfile: str
        :raises LibraryError: bitfile is None type
        """
        self.connect(load_plugin=False)
        if bitfile is None:
            self.logger.error("Provided bitfile in None type")
            raise LibraryError("bitfile is None type")
        if self.tpm is not None:
            self.logger.info("Downloading bitfile " + bitfile + " to board")
            self.tpm.download_firmware(Device.FPGA_1, bitfile)
        else:
            self.logger.warning(
                "Can not download bitfile " + bitfile + ": board not connected"
            )

    @connected
    def erase_fpgas(self):
        """Erase FPGA configuration memory."""
        self.tpm.erase_fpga()

    def program_cpld(self, bitfile):
        """
        Program CPLD with specified bitfile. Use with VERY GREAT care, this might leave
        the FPGA in an unreachable state. TODO Wiser to leave the method out altogether
        and use a dedicated utility instead?

        :param bitfile: Bitfile to flash to CPLD

        :return: write status
        """
        self.connect(load_plugin=False)
        self.logger.info("Downloading bitstream to CPLD FLASH")
        if self.tpm is not None:
            return self.tpm.tpm_cpld.cpld_flash_write(bitfile)

    @connected
    def read_cpld(self, bitfile="cpld_dump.bit"):
        """
        Read bitfile in CPLD FLASH.

        :param bitfile: Bitfile where to dump CPLD firmware
        :type bitfile: str
        """
        self.logger.info("Reading bitstream from CPLD FLASH")
        self.tpm.tpm_cpld.cpld_flash_read(bitfile)

    @connected
    def print_fpga_firmware_information(self, fpga_id=0):
        """
        Print FPGA firmware information
        :param fpga_id: FPGA ID, 0 or 1
        :type fpga_id: int
        """
        if self.is_programmed():
            self.tpm.tpm_firmware_information[fpga_id].print_information()

    def get_ip(self):
        """
        Get tile IP.
        :return: tile IP address
        :rtype: str
        """
        return self._ip

    @connected
    def get_temperature(self):
        """
        Read board temperature.
        :return: board temperature
        :rtype: float
        """
        return self.tpm.temperature()

    @connected
    def get_rx_adc_rms(self):
        """
        Get ADC power.
        :return: ADC RMS power
        :rtype: list(float)
        """
        # If board is not programmed, return None
        if not self.tpm.is_programmed():
            return None

        # Get RMS values from board
        rms = []
        for adc_power_meter in self.tpm.adc_power_meter:
            rms.extend(adc_power_meter.get_RmsAmplitude())

        return rms

    @connected
    def get_adc_rms(self, sync=False):
        """
        Get ADC power, immediate.

        :param sync: Synchronise RMS read
        :type sync: bool

        :return: ADC RMS power
        :rtype: list(float)
        """
        # If board is not programmed, return None
        if not self.tpm.is_programmed():
            return None

        # Get RMS values from board
        rms = []
        for adc_power_meter in self.tpm.adc_power_meter:
            rms.extend(adc_power_meter.get_RmsAmplitude(sync=sync))

        # Re-map values
        return rms

    @connected
    def get_fpga0_temperature(self):
        """
        Get FPGA0 temperature
        :return: FPGA0 temperature
        :rtype: float
        """
        if self.is_programmed():
            return self.tpm.tpm_sysmon[0].get_fpga_temperature()
        else:
            return 0

    @connected
    def get_fpga1_temperature(self):
        """
        Get FPGA1 temperature
        :return: FPGA0 temperature
        :rtype: float
        """
        if self.is_programmed():
            return self.tpm.tpm_sysmon[1].get_fpga_temperature()
        else:
            return 0

    @connected
    def is_qsfp_module_plugged(self, qsfp_id=0):
        """
        Initialise firmware components.

        :return: True when cable is detected
        """
        qsfp_status = self['board.regfile.pll_10g']
        if qsfp_id == 0:
            qsfp_status = (qsfp_status >> 4) & 0x1
        else:
            qsfp_status = (qsfp_status >> 6) & 0x1
        if qsfp_status == 0:
            return True
        else:
            return False

    @connected
    def configure_10g_core(
        self,
        core_id,
        src_mac=None,
        src_ip=None,
        dst_mac=None,
        dst_ip=None,
        src_port=None,
        dst_port=None,
    ):
        """
        Configure a 10G core.

        :todo: Legacy method. Check whether to be deleted.

        :param core_id: 10G core ID
        :param src_mac: Source MAC address
        :param src_ip: Source IP address
        :param dst_mac: Destination MAC address
        :param dst_ip: Destination IP
        :param src_port: Source port
        :param dst_port: Destination port
        """
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
    def configure_40g_core(
        self,
        core_id=0,
        arp_table_entry=0,
        src_mac=None,
        src_ip=None,
        src_port=None,
        dst_ip=None,
        dst_port=None,
        rx_port_filter=None,
        netmask=None,
        gateway_ip=None
    ):
        """
        Configure a 40G core.

        :param core_id: 40G core ID
        :param arp_table_entry: ARP table entry ID
        :param src_mac: Source MAC address
        :param src_ip: Source IP address
        :param dst_ip: Destination IP
        :param src_port: Source port
        :param dst_port: Destination port
        :param rx_port_filter: Filter for incoming packets
        :param netmask: Netmask
        :param gateway_ip: Gateway IP
        """
        # Configure core
        if src_mac is not None:
            self.tpm.tpm_10g_core[core_id].set_src_mac(src_mac)
        if src_ip is not None:
            self.tpm.tpm_10g_core[core_id].set_src_ip(src_ip)
        if dst_ip is not None:
            self.tpm.tpm_10g_core[core_id].set_dst_ip(dst_ip, arp_table_entry)
        if src_port is not None:
            self.tpm.tpm_10g_core[core_id].set_src_port(src_port, arp_table_entry)
        if dst_port is not None:
            self.tpm.tpm_10g_core[core_id].set_dst_port(dst_port, arp_table_entry)
        if rx_port_filter is not None:
            self.tpm.tpm_10g_core[core_id].set_rx_port_filter(
                rx_port_filter, arp_table_entry
            )
        if netmask is not None:
            self.tpm.tpm_10g_core[core_id].set_netmask(netmask)
        if gateway_ip is not None:
            self.tpm.tpm_10g_core[core_id].set_gateway_ip(gateway_ip)


    @connected
    def get_40g_core_configuration(self, core_id, arp_table_entry=0):
        """
        Get the configuration for a 40g core.

        :param core_id: Core ID
        :type core_id: int
        :param arp_table_entry: ARP table entry to use
        :type arp_table_entry: int

        :return: core configuration
        :rtype: dict
        """
        try:
            self._40g_configuration = {
                "core_id": core_id,
                "arp_table_entry": arp_table_entry,
                "src_mac": int(self.tpm.tpm_10g_core[core_id].get_src_mac()),
                "src_ip": int(self.tpm.tpm_10g_core[core_id].get_src_ip()),
                "dst_ip": int(
                    self.tpm.tpm_10g_core[core_id].get_dst_ip(arp_table_entry)
                ),
                "src_port": int(
                    self.tpm.tpm_10g_core[core_id].get_src_port(arp_table_entry)
                ),
                "dst_port": int(
                    self.tpm.tpm_10g_core[core_id].get_dst_port(arp_table_entry)
                ),
                "netmask": int(self.tpm.tpm_10g_core[core_id].get_netmask()),
                "gateway_ip": int(self.tpm.tpm_10g_core[core_id].get_gateway_ip()),
            }
        except IndexError:
            self._40g_configuration = None

        return self._40g_configuration

    def configure_active_40g_ports(self, configuration):
        """
        Configure which of the two 40G QSFP ports is used.
        Options are:
         - Port 1 Only: "port1-only" (lower TPM 40G port, labeled P1 on newer subracks)
         - Port 2 Only: "port2-only" (upper TPM 40G port, labeled P2 on newer subracks)
         - Both Port 1 and Port 2: "both-ports"
        NOTE: TPM 1.2 hardware does not support single port operation. Configurion of the
        is_master register will be ignored by the FPGA & both ports will always be used.
        """
        # If single 40G not supported by firmware both ports must be used
        if not self.tpm.has_register("fpga1.dsp_regfile.config_id.is_master"):
            self.logger.warning("TPM firmware does not support different active 40G port configurations. Both 40G ports will be used.")
            return
        if self.tpm_version == "tpm_v1_2":
            self.logger.warning("TPM 1.2 does not support different active 40G port configurations. Both 40G ports will be used.")
            return
        if configuration == "port1-only":
            if self.tpm.tpm_10g_core[0].is_tx_disabled():
                self.logger.error(
                    "Cannot configure to use 40G Port 1. Port was disabled during initialisation."
                    "\n Re-initialise without QSFP transciever detection set to auto to allow hot swapping of TPM 40G ports."
                    )
                return
            self["fpga1.dsp_regfile.config_id.is_master"] = 1
            self["fpga2.dsp_regfile.config_id.is_master"] = 0
            self.logger.info("TPM in single 40G Port mode! Using only 40G Port 1.")
        elif configuration == "port2-only":
            if self.tpm.tpm_10g_core[1].is_tx_disabled():
                self.logger.error(
                    "Cannot configure to use 40G Port 2. Port was disabled during initialisation."
                    "\n Re-initialise without QSFP transciever detection set to auto to allow hot swapping of TPM 40G ports."
                    )
                return
            self["fpga1.dsp_regfile.config_id.is_master"] = 0
            self["fpga2.dsp_regfile.config_id.is_master"] = 1
            self.logger.info("TPM in single 40G Port mode! Using only 40G Port 2.")
        elif configuration == "both-ports":
            if self.tpm.tpm_10g_core[0].is_tx_disabled():
                self.logger.error(
                    "Cannot configure to use 40G Port 1. Port was disabled during initialisation."
                    "\n Re-initialise without QSFP transciever detection set to auto to allow hot swapping of TPM 40G ports."
                    )
                return
            if self.tpm.tpm_10g_core[1].is_tx_disabled():
                self.logger.error(
                    "Cannot configure to use 40G Port 2. Port was disabled during initialisation."
                    "\n Re-initialise without QSFP transciever detection set to auto to allow hot swapping of TPM 40G ports."
                    )
                return
            self["fpga1.dsp_regfile.config_id.is_master"] = 1
            self["fpga2.dsp_regfile.config_id.is_master"] = 1
            self.logger.info("TPM in dual 40G Port mode!")
        else:
            self.logger.error(f"Invalid configuration {configuration} specifie. Options are: port1-only, port2-only, both-ports")
        return


    @connected
    def set_default_eth_configuration(
            self,
            src_ip_fpga1=None,
            src_ip_fpga2=None,
            dst_ip_fpga1=None,
            dst_ip_fpga2=None,
            src_port=4661,
            dst_port=4660,
            channel2_dst_port=4662,
            channel2_rx_port=4662,
            netmask_40g=None,
            gateway_ip_40g=None,
            qsfp_detection="auto"):
        """
        Set destination and source IP/MAC/ports for 40G cores.

        This will create a loopback between the two FPGAs.

        :param src_ip_fpga1: source IP address for FPGA1 40G interface
        :type src_ip_fpga1: str
        :param src_ip_fpga2: source IP address for FPGA2 40G interface
        :type src_ip_fpga2: str
        :param dst_ip_fpga1: destination IP address for beamformed data from FPGA1 40G interface
        :type dst_ip_fpga1: str
        :param dst_ip_fpga2: destination IP address for beamformed data from FPGA2 40G interface
        :type dst_ip_fpga2: str
        :param src_port: source UDP port for beamformed data packets
        :type src_port: int
        :param dst_port: destination UDP port for beamformed data packets
        :type dst_port: int

        :return: core configuration
        :rtype: dict

        """
        if self["fpga1.regfile.feature.xg_eth_implemented"] == 1:
            src_ip_list = [src_ip_fpga1, src_ip_fpga2]
            dst_ip_list = [dst_ip_fpga1, dst_ip_fpga2]

            for n in range(len(self.tpm.tpm_10g_core)):

                if qsfp_detection == "all":
                    cable_detected = True
                elif qsfp_detection == "flyover_test":
                    cable_detected = True
                    if self.tpm_version == "tpm_v1_2":
                        self.logger.warning(
                            "Forcing QSFP module detection as 'flyover_test' is not supported on TPM 1.2"
                        )
                    else:
                        self.tpm.tpm_test_firmware[n].configure_40g_core_flyover_test()
                elif qsfp_detection == "auto" and self.is_qsfp_module_plugged(n):
                    cable_detected = True
                elif n == 0 and qsfp_detection == "qsfp1":
                    cable_detected = True
                elif n == 1 and qsfp_detection == "qsfp2":
                    cable_detected = True
                else:
                    cable_detected = False


                # 40G Source IP
                src_ip = src_ip_list[n]
                # If src IP not specified, generate one based on 1G IP
                if src_ip_list[n] is None:
                    src_ip_octets = self._ip.split(".")
                    src_ip = f"10.0.{n + 1}.{src_ip_octets[3]}"

                # 40G Destination IP
                dst_ip = dst_ip_list[n]

                # if QSFP cable is detected then reset core,
                # check for link up (done in reset reset_core) and set default IP address,
                # otherwise disable TX
                if cable_detected:
                    self.tpm.tpm_10g_core[n].reset_core(timeout=10)
                    self.configure_40g_core(
                        core_id=n,
                        arp_table_entry=0,
                        src_mac=0x620000000000 + ip2long(src_ip),
                        src_ip=src_ip,
                        dst_ip=dst_ip,
                        src_port=src_port,
                        dst_port=dst_port,
                        rx_port_filter=dst_port,
                        netmask=netmask_40g,
                        gateway_ip=gateway_ip_40g,
                    )
                    # Also configure entry 2 with the same settings
                    # Required for operation in single port mode
                    # In Dual Port Mode each core uses arp table entry 0 for station beam transmission 
                    # to the next tile in the chain and lastly to CSP.
                    # Two FPGAs = Two Simultaneous Daisy chains (a chain of FPGA1s and a chain of FPGA2s)
                    # In Single Port Mode Master FPGA uses arp table entry 0, Slave FPGA uses arp table entry 2 to achieve the same
                    # functionality but with a single UDP core.
                    self.configure_40g_core(
                        core_id=n,
                        arp_table_entry=2,
                        src_mac=0x620000000000 + ip2long(src_ip),
                        src_ip=src_ip,
                        dst_ip=dst_ip,
                        src_port=src_port,
                        dst_port=channel2_dst_port,
                        netmask=netmask_40g,
                        gateway_ip=gateway_ip_40g,
                    )
                    # Set RX port filter for RX channel 1
                    # Required for operation in single port mode
                    # RX channel 2 should come out on TID 1 in firmware
                    self.configure_40g_core(
                        core_id=n,
                        arp_table_entry=1,
                        rx_port_filter=channel2_rx_port
                    )
                else:
                    self.tpm.tpm_10g_core[n].tx_disable()
            
    @connected
    def set_lmc_download(
        self,
        mode,
        payload_length=1024,
        dst_ip=None,
        src_port=0xF0D0,
        dst_port=4660,
        netmask_40g=None,
        gateway_ip_40g=None
    ):
        """
        Configure link and size of control data for LMC packets.

        :param mode: "1g" or "10g"
        :type mode: str
        :param payload_length: SPEAD payload length in bytes
        :type payload_length: int
        :param dst_ip: Destination IP
        :type dst_ip: str
        :param src_port: Source port for integrated data streams
        :type src_port: int
        :param dst_port: Destination port for integrated data streams
        :type dst_port: int
        """
        # Using 10G lane
        if mode.upper() == "10G":
            if payload_length >= 8193:
                self.logger.warning("Packet length too large for 10G")
                return

            # If dst_ip is None, use local lmc_ip
            if dst_ip is None:
                dst_ip = self._lmc_ip

            
            for core_id in range(len(self.tpm.tpm_10g_core)):
                self.configure_40g_core(
                    core_id=core_id,
                    arp_table_entry=1,
                    dst_ip=dst_ip,
                    src_port=src_port,
                    dst_port=dst_port,
                    netmask=netmask_40g,
                    gateway_ip=gateway_ip_40g,
                )
                # Also configure entry 3 with the same settings
                # Required for operation in single port mode
                # In Dual Port Mode each core uses arp table entry 1 for LMC transmission
                # In Single Port Mode Master FPGA uses arp table entry 1, Slave FPGA uses arp table entry 3
                self.configure_40g_core(
                    core_id=core_id,
                    arp_table_entry=3,
                    dst_ip=dst_ip,
                    src_port=src_port,
                    dst_port=dst_port,
                    netmask=netmask_40g,
                    gateway_ip=gateway_ip_40g,
                )

            self["fpga1.lmc_gen.tx_demux"] = 2
            self["fpga2.lmc_gen.tx_demux"] = 2

        # Using dedicated 1G link
        elif mode.upper() == "1G":
            if dst_ip is not None:
                self._lmc_ip = dst_ip

            self.tpm.set_lmc_ip(self._lmc_ip, self._lmc_port)

            self["fpga1.lmc_gen.tx_demux"] = 1
            self["fpga2.lmc_gen.tx_demux"] = 1
        else:
            self.logger.warning("Supported modes are 1g, 10g")
            return

        self["fpga1.lmc_gen.payload_length"] = payload_length
        self["fpga2.lmc_gen.payload_length"] = payload_length

    @connected
    def set_lmc_integrated_download(
        self,
        mode,
        channel_payload_length,
        beam_payload_length,
        dst_ip=None,
        src_port=0xF0D0,
        dst_port=4660,
        netmask_40g=None,
        gateway_ip_40g=None
    ):
        """
        Configure link and size of control data for integrated LMC packets.

        :param mode: '1g' or '10g'
        :type mode: str
        :param channel_payload_length: SPEAD payload length for integrated channel data
        :type channel_payload_length: int
        :param beam_payload_length: SPEAD payload length for integrated beam data
        :type beam_payload_length: int
        :param dst_ip: Destination IP
        :type dst_ip: str
        :param src_port: Source port for integrated data streams
        :type src_port: int
        :param dst_port: Destination port for integrated data streams
        :type dst_port: int
        """
        # Using 10G lane
        if mode.upper() == "10G":

            # If dst_ip is None, use local lmc_ip
            if dst_ip is None:
                dst_ip = self._lmc_ip

            for core_id in range(len(self.tpm.tpm_10g_core)):
                self.configure_40g_core(
                    core_id=core_id,
                    arp_table_entry=1,
                    dst_ip=dst_ip,
                    src_port=src_port,
                    dst_port=dst_port,
                    netmask=netmask_40g,
                    gateway_ip=gateway_ip_40g,

                )
                # Also configure entry 3 with the same settings
                # Required for operation in single port mode
                # In Dual Port Mode each core uses arp table entry 1 for LMC transmission
                # In Single Port Mode Master FPGA uses arp table entry 1, Slave FPGA uses arp table entry 3
                self.configure_40g_core(
                    core_id=core_id,
                    arp_table_entry=3,
                    dst_ip=dst_ip,
                    src_port=src_port,
                    dst_port=dst_port,
                    netmask=netmask_40g,
                    gateway_ip=gateway_ip_40g,

                )

        # Using dedicated 1G link
        elif mode.upper() == "1G":
            pass
        else:
            self.logger.error("Supported mode are 1g, 10g")
            return

        # Setting payload lengths
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].configure_download(
                mode, channel_payload_length, beam_payload_length
            )

    @connected
    def check_arp_table(self, timeout=30.0):
        """
        Check that ARP table has been resolved for all used cores.
        40G interfaces use cores 0 (fpga0) and 1 (fpga1) and
        ARP ID 0 for beamformer, 1 for LMC.
        The procedure checks that all populated ARP entries have been
        resolved. If the QSFP has been disabled or link is not detected up,
        the check is skipped.

        :param timeout: Timeout in seconds
        :type timeout: float
        :return: ARP table status
        :rtype: bool
        """

        # polling time to check ARP table
        polling_time = 0.1
        checks_per_second = 1.0 / polling_time
        # sanity check on time. Between 1 and 100 seconds
        max_time = int(timeout)
        if max_time < 1:
            max_time = 1
        if max_time > 100:
            max_time = 100
        # wait UDP link up
        core_id = range(len(self.tpm.tpm_10g_core))
        arp_table_id = range(self.tpm.tpm_10g_core[0].get_number_of_arp_table_entries())

        self.logger.info("Checking ARP table...")

        linked_core_id = []
        for c in core_id:
            if self.tpm.tpm_10g_core[c].is_tx_disabled():
                self.logger.warning("Skipping ARP table check on FPGA" + str(c+1) + ". TX is disabled!")
            elif not self.active_40g_port[c]:
                self.logger.warning("Skipping ARP table check on FPGA" + str(c+1) + ". Port disabled for single active port mode!")
            elif self.tpm.tpm_10g_core[c].is_link_up():
                self.logger.info("Beginning ARP table check on FPGA" + str(c+1) + ".")
                linked_core_id.append(c)
            else:
                self.logger.warning("Skipping ARP table check on FPGA" + str(c+1) + ". Link is down!")

        if not linked_core_id:
            return False

        times = 0
        while True:
            not_ready_links = []
            for c in linked_core_id:
                core_inst = self.tpm.tpm_10g_core[c]
                core_errors = core_inst.check_errors()
                if core_errors:
                    not_ready_links.append(c)
                for a in arp_table_id:
                    core_status, core_mac = core_inst.get_arp_table_status(a, silent_mode=True)
                    # check if valid entry has been resolved
                    if core_status & 0x1 == 1 and core_status & 0x4 == 0:
                        not_ready_links.append(c)

            if not not_ready_links:
                self.logger.info("40G Link established! ARP table populated!")
                return True
            else:
                times += 1
                time.sleep(polling_time)
                for c in linked_core_id:
                    if c in not_ready_links:
                        if times % checks_per_second == 0:
                            self.logger.warning(
                                f"40G Link on FPGA{c} not established after {int(0.1 * times)} seconds! Waiting... "
                            )
                        if times == max_time * checks_per_second:
                            self.logger.warning(
                                f"40G Link on FPGA{c} not established after {int(0.1 * times)} seconds! ARP table not populated!"
                            )
                            return False

    def get_arp_table(self):
        """
        Check that ARP table has been populated in for all used cores.
        Returns a dictionary with an entry for each core present in the firmware
        Each entry contains a list of the ARP table IDs which have been resolved
        by the ARP state machine.

        :return: list of populated core ids and arp table entries
        :rtype: dict(list)
        """
        # wait UDP link up
        if self["fpga1.regfile.feature.xg_eth_implemented"] == 1:
            self.logger.debug("Checking ARP table...")

            if self.tpm.tpm_test_firmware[0].xg_40g_eth:
                core_ids = range(2)
                arp_table_ids = range(4)
            else:
                core_ids = range(8)
                arp_table_ids = [0]

            self._arp_table = {i: [] for i in core_ids}

            linkup = True
            for core_id in core_ids:
                for arp_table in arp_table_ids:
                    core_status, core_mac = self.tpm.tpm_10g_core[core_id].get_arp_table_status(
                        arp_table, silent_mode=True
                    )
                    if core_status & 0x4 == 0:
                        message = (
                            f"CoreID {core_id} with ArpID {arp_table} is not "
                            "populated"
                        )

                        self.logger.debug(message)
                        linkup = False
                    else:
                        self._arp_table[core_id].append(arp_table)

            if linkup:
                self.logger.debug("10G Link established! ARP table populated!")

        return self._arp_table

    @connected
    def set_station_id(self, station_id, tile_id):
        """
        Set station ID.

        :param station_id: Station ID
        :param tile_id: Tile ID within station
        """
        fpgas = ["fpga1", "fpga2"]
        if len(self.tpm.find_register("fpga1.regfile.station_id")) > 0:
            for f in fpgas:
                self[f + ".regfile.station_id"] = station_id
                self[f + ".regfile.tpm_id"] = tile_id
        else:
            for f in fpgas:
                self[f + ".dsp_regfile.config_id.station_id"] = station_id
                self[f + ".dsp_regfile.config_id.tpm_id"] = tile_id

    @connected
    def get_station_id(self):
        """
        Get station ID
        :return: station ID programmed in HW
        :rtype: int
        """
        if not self.tpm.is_programmed():
            return -1
        else:
            if len(self.tpm.find_register("fpga1.regfile.station_id")) > 0:
                tile_id = self["fpga1.regfile.station_id"]
            else:
                tile_id = self["fpga1.dsp_regfile.config_id.station_id"]
            return tile_id

    @connected
    def get_tile_id(self):
        """
        Get tile ID.

        :return: programmed tile id
        :rtype: int
        """
        if not self.tpm.is_programmed():
            return -1
        else:
            if len(self.tpm.find_register("fpga1.regfile.tpm_id")) > 0:
                tile_id = self["fpga1.regfile.tpm_id"]
            else:
                tile_id = self["fpga1.dsp_regfile.config_id.tpm_id"]
            return tile_id

    ###########################################
    # Time related methods
    ###########################################
    @connected
    def get_fpga_time(self, device):
        """
        Return time from FPGA.

        :param device: FPGA to get time from
        :type device: Device
        :return: Internal time for FPGA
        :rtype: int
        :raises LibraryError: Invalid value for device
        """
        if device == Device.FPGA_1:
            return self["fpga1.pps_manager.curr_time_read_val"]
        elif device == Device.FPGA_2:
            return self["fpga2.pps_manager.curr_time_read_val"]
        else:
            raise LibraryError("Invalid device specified")

    @connected
    def set_fpga_time(self, device, device_time):
        """
        Set Unix time in FPGA.

        :param device: FPGA to get time from
        :type device: Device
        :param device_time: Internal time for FPGA
        :type device_time: int
        :raises LibraryError: Invalid value for device
        """
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
        """
        Get timestamp from FPGA.

        :param device: FPGA to read timestamp from
        :type device: Device
        :return: PPS time
        :rtype: int
        :raises LibraryError: Invalid value for device
        """
        if device == Device.FPGA_1:
            return self["fpga1.pps_manager.timestamp_read_val"]
        elif device == Device.FPGA_2:
            return self["fpga2.pps_manager.timestamp_read_val"]
        else:
            raise LibraryError("Invalid device specified")

    @connected
    def get_phase_terminal_count(self):
        """
        Get PPS phase terminal count.

        :return: PPS phase terminal count
        :rtype: int
        """
        return self["fpga1.pps_manager.sync_tc.cnt_1_pulse"]

    @connected
    def set_phase_terminal_count(self, value):
        """
        Set PPS phase terminal count.

        :param value: PPS phase terminal count
        """
        self["fpga1.pps_manager.sync_tc.cnt_1_pulse"] = value
        self["fpga2.pps_manager.sync_tc.cnt_1_pulse"] = value

    @connected
    def get_pps_delay(self, enable_correction=True):
        """
        Get delay between PPS and 10 MHz clock.
        :param: enable_correction, enable PPS delay correction using value configured in the FPGA1
        :type: bool

        :return: delay between PPS and 10 MHz clock in 200 MHz cycles
        :rtype: int
        """
        if enable_correction:
            pps_correction = self["fpga1.pps_manager.sync_tc.cnt_2"]
            if pps_correction > 127:
                pps_correction -= 256
        else:
            pps_correction = 0
        return self["fpga1.pps_manager.sync_phase.cnt_hf_pps"] + pps_correction

    @connected
    def wait_pps_event(self):
        """
        Wait for a PPS edge. Added timeout feture to avoid method to stuck.

        :raises BoardError: Hardware PPS stuck
        """
        timeout = 1100
        t0 = self.get_fpga_time(Device.FPGA_1)
        while t0 == self.get_fpga_time(Device.FPGA_1):
            if timeout > 0:
                time.sleep(0.001)
                timeout = timeout - 1
                pass
            else:
                raise BoardError("TPM PPS counter does not advance")

    @connected
    def check_pending_data_requests(self):
        """
        Checks whether there are any pending data requests.

        :return: true if pending requests are present
        :rtype: bool
        """
        return (self["fpga1.lmc_gen.request"] + self["fpga2.lmc_gen.request"]) > 0

    ########################################################
    # channeliser
    ########################################################
    @connected
    def set_channeliser_truncation(self, trunc, signal=None):
        """
        Set channeliser truncation scale for the whole tile or for
        individual ADC channels.

        :param trunc: Truncted bits, channeliser output scaled down
            by specified number of bits. May be a single value (same for all
            frequency channels) or list of 512 values.
        :type trunc: int or list(int)
        :param signal: Input signal, 0 to 31. If None, apply to all
        :type signal: int
        """
        # if trunc is a single value, apply to all channels
        if type(trunc) == int:
            if 0 > trunc or trunc > 7:
                self.logger.warning(
                    f"Could not set channeliser truncation to {trunc}, setting to 0"
                )
                trunc = 0

            trunc_vec1 = 256 * [trunc]
            trunc_vec2 = 256 * [trunc]
        else:
            trunc_vec1 = trunc[0:256]
            trunc_vec2 = trunc[256:512]
            trunc_vec2.reverse()  # 2nd half of freq chans are in reverse order
        #
        # If signal is not specified, apply to all signals
        if signal is None:
            siglist = range(32)
        else:
            siglist = [signal]

        for i in siglist:
            if i >= 0 and i < 16:
                self["fpga1.channelizer.block_sel"] = 2 * i
                self["fpga1.channelizer.rescale_data"] = trunc_vec1
                self["fpga1.channelizer.block_sel"] = 2 * i + 1
                self["fpga1.channelizer.rescale_data"] = trunc_vec2
            elif i >= 16 and i < 32:
                i = i - 16
                self["fpga2.channelizer.block_sel"] = 2 * i
                self["fpga2.channelizer.rescale_data"] = trunc_vec1
                self["fpga2.channelizer.block_sel"] = 2 * i + 1
                self["fpga2.channelizer.rescale_data"] = trunc_vec2
            else:
                self.logger.warning("Signal " + str(i) + " is outside range (0:31)")

    @connected
    def set_time_delays(self, delays):
        """
        Set coarse zenith delay for input ADC streams.
        Delay specified in nanoseconds, nominal is 0.

        :param delays: Delay in samples, positive delay adds delay to the signal stream
        :type delays: list(float)

        :return: Parameters in range
        :rtype: bool
        """
        # Compute maximum and minimum delay
        frame_length = (1.0 / self._sampling_rate) * 1e9
        min_delay = frame_length * -124
        max_delay = frame_length * 127

        self.logger.debug(
            f"frame_length = {frame_length} , min_delay = {min_delay} , max_delay = {max_delay}"
        )

        # Check that we have the correct number of delays (one or 16)
        if type(delays) in [float, int]:
            # Check that we have a valid delay
            if min_delay <= delays <= max_delay:
                # possible problem to fix here :
                #                delays_hw = [int(round(delays / frame_length))] * 32
                # Test from Riccardo :
                delays_hw = [int(round(delays / frame_length) + 128)] * 32
            else:
                self.logger.warning(
                    f"Specified delay {delays} out of range [{min_delay}, {max_delay}], skipping"
                )
                return False

        elif type(delays) is list and len(delays) == 32:
            # Check that all delays are valid
            delays = np.array(delays, dtype=float)
            if np.all(min_delay <= delays) and np.all(delays <= max_delay):
                delays_hw = np.clip(
                    (np.round(delays / frame_length) + 128).astype(int), 4, 255
                ).tolist()
            else:
                self.logger.warning(
                    f"Specified delay {delays} out of range [{min_delay}, {max_delay}], skipping"
                )
                return False

        else:
            self.logger.warning(
                "Invalid delays specfied (must be a number or list of numbers of length 32)"
            )
            return False

        self.logger.info(f"Setting hardware delays = {delays_hw}")
        # Write delays to board
        self["fpga1.test_generator.delay_0"] = delays_hw[:16]
        self["fpga2.test_generator.delay_0"] = delays_hw[16:]
        return True

    # ----------------------------
    # Pointing and calibration routines
    # ---------------------------
    @connected
    def initialise_beamformer(self, start_channel, nof_channels):
        """
        Initialise tile and station beamformers for a simple single beam configuration.

        :param start_channel: Initial channel, must be even
        :type start_channel: int
        :param nof_channels: Number of beamformed spectral channels
        :type nof_channels: int
        :param is_first: True for first tile in beamforming chain
        :type is_first: bool
        :param is_last: True for last tile in beamforming chain
        :type is_last: bool
        """
        for _beamf_fd in self.tpm.beamf_fd:
            _beamf_fd.initialise_beamf()
            _beamf_fd.set_regions([[start_channel, nof_channels, 0]])
            _beamf_fd.antenna_tapering = [1.0] * 8
            _beamf_fd.compute_calibration_coefs()

        # Interface towards beamformer in FPGAs
        for _station_beamf in self.tpm.station_beamf:
            _station_beamf.initialise_beamf()
            _station_beamf.defineChannelTable([[start_channel, nof_channels, 0]])

    @connected
    def set_beamformer_regions(self, region_array):
        """
        Set frequency regions.
        Regions are defined in a 2-d array, for a maximum of 16 (48) regions.
        Each element in the array defines a region, with the form
        [start_ch, nof_ch, beam_index]

        - start_ch:    region starting channel (currently must be a
                       multiple of 2, LS bit discarded)
        - nof_ch:      size of the region: must be multiple of 8 chans
        - beam_index:  beam used for this region, range [0:8)

        Total number of channels must be <= 384
        The routine computes the arrays beam_index, region_off, region_sel,
        and the total number of channels nof_chans, and programs it in the HW.

        :param region_array: list of region array descriptors
        :type region_array: list(list(int))
        """
        for _beamf_fd in self.tpm.beamf_fd:
            _beamf_fd.set_regions(region_array)
        for _station_beamf in self.tpm.station_beamf:
            _station_beamf.define_channel_table(region_array)

    @connected
    def set_pointing_delay(self, delay_array, beam_index):
        """
        Specifies the delay in seconds and the delay rate in seconds/seconds.
        The delay_array specifies the delay and delay rate for each antenna.
        beam_index specifies which beam is described (range 0:7).
        Delay is updated inside the delay engine at the time specified
        by method load_delay.

        :param delay_array: delay and delay rate for each antenna
        :type delay_array: list(list(float))
        :param beam_index: specifies which beam is described (range 0:7)
        :type beam_index: int
        """
        self.tpm.beamf_fd[0].set_delay(delay_array[0:8], beam_index)
        self.tpm.beamf_fd[1].set_delay(delay_array[8:], beam_index)

    @connected
    def load_pointing_delay(self, load_time=0, load_delay=64):
        """
        Delay is updated inside the delay engine at the time specified.
        If load_time = 0 load immediately applying a delay defined by load_delay

        :param load_time: time (in ADC frames/256) for delay update
        :type load_time: int
        :param load_delay: delay in (in ADC frames/256) to apply when load_time == 0
        :type load_delay: int
        """
        if load_time == 0:
            load_time = self.current_tile_beamformer_frame() + load_delay

        for _beamf_fd in self.tpm.beamf_fd:
            _beamf_fd.load_delay(load_time)

    @connected
    def load_calibration_coefficients(self, antenna, calibration_coefficients):
        """
        Loads calibration coefficients.
        calibration_coefficients is a bi-dimensional complex array of the form
        calibration_coefficients[channel, polarization], with each element representing
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
        the parallitic angle), but do not include the geometric delay.

        :param antenna: Antenna number (0-15)
        :type antenna: int
        :param calibration_coefficients: Calibration coefficient array
        :type calibration_coefficients: list(float)
        """
        if antenna < 8:
            self.tpm.beamf_fd[0].load_calibration(antenna, calibration_coefficients)
        else:
            self.tpm.beamf_fd[1].load_calibration(antenna - 8, calibration_coefficients)

    @connected
    def load_antenna_tapering(self, beam, tapering_coefficients):
        """
        tapering_coefficients is a vector of 16 values, one per antenna.
        Default (at initialization) is 1.0.
        :todo: modify plugin to allow for different beams.

        :param beam: Beam index in range 0:47
        :type beam: int
        :param tapering_coefficients: Coefficients for each antenna
        :type tapering_coefficients: list(int)
        """
        if beam > 0:
            self.logger.warning("Tapering implemented only for beam 0")

        self.tpm.beamf_fd[0].load_antenna_tapering(tapering_coefficients[0:8])
        self.tpm.beamf_fd[1].load_antenna_tapering(tapering_coefficients[8:])

    @connected
    def load_beam_angle(self, angle_coefficients):
        """
        Angle_coefficients is an array of one element per beam, specifying a rotation
        angle, in radians, for the specified beam.
        The rotation is the same for all antennas. Default is 0 (no
        rotation). A positive pi/4 value transfers the X polarization to
        the Y polarization. The rotation is applied after regular
        calibration.

        :param angle_coefficients: Rotation angle, per beam, in radians
        :type angle_coefficients: list(float)
        """
        for _beamf_fd in self.tpm.beamf_fd:
            _beamf_fd.load_beam_angle(angle_coefficients)

    @connected
    def compute_calibration_coefficients(self):
        """Compute the calibration coefficients and load them in the hardware."""
        for _beamf_fd in self.tpm.beamf_fd:
            _beamf_fd.compute_calibration_coefs()

    @connected
    def switch_calibration_bank(self, switch_time=0):
        """
        Switches the loaded calibration coefficients at prescribed time
        If time = 0 switch immediately
        :param switch_time: time (in ADC frames/256) for delay update
        :type switch_time: int
        """
        if switch_time == 0:
            switch_time = self.current_tile_beamformer_frame() + 64

        for _beamf_fd in self.tpm.beamf_fd:
            _beamf_fd.switch_calibration_bank(switch_time)

    @connected
    def set_beamformer_epoch(self, epoch):
        """
        Set the Unix epoch in seconds since Unix reference time.

        :param epoch: Unix epoch for the reference time
        :return: Success status
        :rtype: bool
        """
        ret1 = self.tpm.station_beamf[0].set_epoch(epoch)
        ret2 = self.tpm.station_beamf[1].set_epoch(epoch)
        return ret1 and ret2

    @connected
    def set_csp_rounding(self, rounding):
        """
        Set output rounding for CSP.

        :param rounding: Number of bits rounded in final 8 bit requantization to CSP
        :return: success status
        :rtype: bool
        """
        ret1 = self.tpm.station_beamf[0].set_csp_rounding(rounding)
        ret2 = self.tpm.station_beamf[1].set_csp_rounding(rounding)
        return ret1 and ret2

    @connected
    def current_station_beamformer_frame(self):
        """
        Query time of packets at station beamformer input.
        :return: current frame, in units of 256 ADC frames (276,48 us)
        :rtype: int
        """
        return self.tpm.station_beamf[0].current_frame()

    @connected
    def current_tile_beamformer_frame(self):
        """
        Query time of packets at tile beamformer input.
        :return: current frame, in units of 256 ADC frames (276,48 us)
        :rtype: int
        """
        return self.tpm.beamf_fd[0].current_frame()

    @connected
    def set_first_last_tile(self, is_first, is_last):
        """
        Defines if a tile is first, last, both or intermediate.

        One, and only one tile must be first, and last, in a chain. A
        tile can be both (one tile chain), or none.

        :param is_first: True for first tile in beamforming chain
        :type is_first: bool
        :param is_last: True for last tile in beamforming chain
        :type is_last: bool
        :return: success status
        :rtype: bool
        """
        ret1 = self.tpm.station_beamf[0].set_first_last_tile(is_first, is_last)
        ret2 = self.tpm.station_beamf[1].set_first_last_tile(is_first, is_last)
        return ret1 and ret2

    @connected
    def define_spead_header(
        self, station_id, subarray_id, nof_antennas, ref_epoch=-1, start_time=0
    ):
        """
        Define SPEAD header for last tile.

        All parameters are specified by the LMC.

        :param station_id: Station ID
        :param subarray_id: Subarray ID
        :param nof_antennas: Number of antennas in the station
        :type nof_antennas: int
        :param ref_epoch: Unix time of epoch. -1 uses value defined in set_epoch
        :type ref_epoch: int
        :param start_time: start time (TODO describe better)
        :return: True if parameters OK, False for error
        :rtype: bool
        """
        ret1 = self.tpm.station_beamf[0].define_spead_header(
            station_id, subarray_id, nof_antennas, ref_epoch, start_time
        )
        ret2 = self.tpm.station_beamf[1].define_spead_header(
            station_id, subarray_id, nof_antennas, ref_epoch, start_time
        )
        return ret1 and ret2

    @connected
    def beamformer_is_running(self):
        """
        Check if station beamformer is running.

        :return: beamformer running status
        :rtype: bool
        """
        return self.tpm.station_beamf[0].is_running()

    @connected
    def start_beamformer(self, start_time=0, duration=-1, scan_id=0, mask=0xffffffffff):
        """
        Start the beamformer.
        Duration: if > 0 is a duration in frames * 256 (276.48 us)
        if == -1 run forever

        :param start_time: time (in ADC frames/256) for first frame sent
        :type start_time: int
        :param duration: duration in ADC frames/256. Multiple of 8
        :type duration: int
        :param scan_id: ID of the scan, to be specified in the CSP SPEAD header
        :type scan_id: int
        :param mask: Bitmask of the channels to be started. Unsupported by FW
        :type mask: int
        :return: False for error (e.g. beamformer already running)
        :rtype bool:
        """
        timestamp_mask = 0xFFFFFFF8  # Impose a time multiple of 8 frames
        if self.beamformer_is_running():
            return False

        if start_time == 0:
            start_time = self.current_station_beamformer_frame() + 256

        start_time &= mask  # Impose a start time multiple of 8 frames

        if duration != -1:
            duration = duration & timestamp_mask

        ret1 = self.tpm.station_beamf[0].start(
            start_time, 
            duration,
            scan_id = scan_id,
            mask = mask
        )
        ret2 = self.tpm.station_beamf[1].start(
            start_time, 
            duration,
            scan_id = scan_id,
            mask = mask
        )

        # check if synchronised operation is successful,
        # time now must be smaller than start_time
        time_now = self.current_station_beamformer_frame()
        if time_now >= start_time:
            logging.error("Tile start_beamformer error. Synchronised operation failed! Time difference: " +
            str(time_now - start_time))
            ret1 = False
            ret2 = False

        if ret1 and ret2:
            return True
        else:
            self.stop_beamformer()
            return False

    @connected
    def stop_beamformer(self):
        """Stop beamformer."""
        self.tpm.station_beamf[0].abort()
        self.tpm.station_beamf[1].abort()

    # ------------------------------------
    # Synchronisation routines
    # ------------------------------------
    @connected
    def sync_fpga_time(self, use_internal_pps=False):
        """Set UTC time to two FPGAs in the tile Returns when these are synchronised.

        :param use_internal_pps: use internally generated PPS, for test/debug
        :type use_internal_pps: bool
        """

        devices = ["fpga1", "fpga2"]

        # Setting internal PPS generator
        for f in devices:
            self.tpm[f + ".pps_manager.pps_gen_tc"] = int(100e6) - 1  # PPS generator runs at 100 Mhz
            self.tpm[f + ".pps_manager.sync_cnt_enable"] = 0x7
            self.tpm[f + ".pps_manager.sync_cnt_enable"] = 0x0
            if self.tpm.has_register("fpga1.pps_manager.pps_exp_tc"):
                self.tpm[f + ".pps_manager.pps_exp_tc"] = int(200e6) - 1  # PPS validation runs at 200 Mhz
            else:
                self.logger.info("FPGA Firmware does not support updated PPS validation. Status of PPS error flag should be ignored.")  

        # Setting internal PPS generator
        if use_internal_pps:
            for f in devices:
                self.tpm[f + ".regfile.spi_sync_function"] = 1
                self.tpm[f + ".pps_manager.pps_gen_sync"] = 0
                self.tpm[f + ".pps_manager.pps_gen_sync.enable"] = 1
            time.sleep(0.1)
            self.tpm["fpga1.pps_manager.pps_gen_sync.act"] = 1
            time.sleep(0.1)
            for f in devices:
                self.tpm[f + ".pps_manager.pps_gen_sync"] = 0
                self.tpm[f + ".regfile.spi_sync_function"] = 1
                self.tpm[f + ".pps_manager.pps_selection"] = 1
            logging.warning("Using Internal PPS generator!")
            logging.info("Internal PPS generator synchronised.")

        # Setting UTC time
        max_attempts = 5
        for _n in range(max_attempts):
            self.logger.info("Synchronising FPGA UTC time.")
            self.wait_pps_event()
            time.sleep(0.5)

            t = int(time.time())
            self.set_fpga_time(Device.FPGA_1, t)
            self.set_fpga_time(Device.FPGA_2, t)

            # configure the PPS sampler
            self.set_pps_sampling(20, 4)

            self.wait_pps_event()
            time.sleep(0.1)
            t0 = self.tpm["fpga1.pps_manager.curr_time_read_val"]
            t1 = self.tpm["fpga2.pps_manager.curr_time_read_val"]

            if t0 == t1:
                return

        self.logger.error("Not possible to synchronise FPGA UTC time after " + str(max_attempts) + " attempts!")

    @connected
    def set_pps_sampling(self, target, margin):
        """
        Set the PPS sampler terminal count

        :param target: target delay
        :type target: int
        :param margin: margin, target +- margin
        :type margin: int
        """

        current_tc = self.get_phase_terminal_count()
        current_delay = self.get_pps_delay()
        delay = self.calculate_delay(
            current_delay,
            current_tc,
            target,
            margin,
        )
        self.set_phase_terminal_count(delay)

    @connected
    def check_fpga_synchronization(self):
        """
        Checks various synchronization parameters.

        Output in the log

        :return: OK status
        :rtype: bool
        """
        result = True
        # check PLL status
        pll_status = self.tpm["pll", 0x508]
        if pll_status == 0xE7:
            self.logger.debug("PLL locked to external reference clock.")
        elif pll_status == 0xF2:
            self.logger.warning("PLL locked to internal reference clock.")
        else:
            self.logger.error(
                "PLL is not locked! - Status Readback 0 (0x508): " + hex(pll_status)
            )
            result = False

        # check PPS detection
        if self.tpm["fpga1.pps_manager.pps_detected"] == 0x1:
            self.logger.debug("FPGA1 is locked to external PPS")
        else:
            self.logger.warning("FPGA1 is not locked to external PPS")
        if self.tpm["fpga2.pps_manager.pps_detected"] == 0x1:
            self.logger.debug("FPGA2 is locked to external PPS")
        else:
            self.logger.warning("FPGA2 is not locked to external PPS")
        
        # Check PPS valid
        if self.tpm.has_register("fpga1.pps_manager.pps_exp_tc"):
            if self.tpm[f'fpga1.pps_manager.pps_errors.pps_count_error'] == 0x0:
                self.logger.debug("FPGA1 PPS period is as expected.")
            else:
                self.logger.error("FPGA1 PPS period is not as expected.")
                result = False
        else:
            self.logger.info("FPGA1 Firmware does not support updated PPS validation. Ignoring status of PPS error flag.")
        if self.tpm.has_register("fpga2.pps_manager.pps_exp_tc"):
            if self.tpm[f'fpga2.pps_manager.pps_errors.pps_count_error'] == 0x0:
                self.logger.debug("FPGA2 PPS period is as expected.")
            else:
                self.logger.error("FPGA2 PPS period is not as expected.")
                result = False
        else:
            self.logger.info("FPGA2 Firmware does not support updated PPS validation. Ignoring status of PPS error flag.")  

        # check FPGA time
        self.wait_pps_event()
        t0 = self.tpm["fpga1.pps_manager.curr_time_read_val"]
        t1 = self.tpm["fpga2.pps_manager.curr_time_read_val"]
        self.logger.info("FPGA1 time is " + str(t0))
        self.logger.info("FPGA2 time is " + str(t1))
        if t0 != t1:
            self.logger.error("Time different between FPGAs detected!")
            result = False

        # check FPGA timestamp
        t0 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        t1 = self.tpm["fpga2.pps_manager.timestamp_read_val"]
        self.logger.info("FPGA1 timestamp is " + str(t0))
        self.logger.info("FPGA2 timestamp is " + str(t1))
        if abs(t0 - t1) > 1:
            self.logger.warning("Timestamp different between FPGAs detected!")

        # Check FPGA ring beamfomrer timestamp
        t0 = self.tpm["fpga1.beamf_ring.current_frame"]
        t1 = self.tpm["fpga2.beamf_ring.current_frame"]
        self.logger.info("FPGA1 station beamformer timestamp is " + str(t0))
        self.logger.info("FPGA2 station beamformer timestamp is " + str(t1))
        if abs(t0 - t1) > 1:
            self.logger.warning(
                "Beamformer timestamp different between FPGAs detected!"
            )

        return result

    @connected
    def set_c2c_burst(self):
        """Setting C2C burst when supported by FPGAs and CPLD."""
        self.tpm["fpga1.regfile.c2c_stream_ctrl.idle_val"] = 0
        self.tpm["fpga2.regfile.c2c_stream_ctrl.idle_val"] = 0
        if len(self.tpm.find_register("fpga1.regfile.feature.c2c_linear_burst")) > 0:
            fpga_burst_supported = self.tpm["fpga1.regfile.feature.c2c_linear_burst"]
        else:
            fpga_burst_supported = 0
        if len(self.tpm.find_register("board.regfile.c2c_ctrl.mm_burst_enable")) > 0:
            self.tpm["board.regfile.c2c_ctrl.mm_burst_enable"] = 0
            cpld_burst_supported = 1
        else:
            cpld_burst_supported = 0

        if cpld_burst_supported == 1 and fpga_burst_supported == 1:
            self.tpm["board.regfile.c2c_ctrl.mm_burst_enable"] = 1
            self.logger.debug("C2C burst activated.")
            return
        if fpga_burst_supported == 0:
            self.logger.debug("C2C burst is not supported by FPGAs.")
        if cpld_burst_supported == 0:
            self.logger.debug("C2C burst is not supported by CPLD.")

    @connected
    def synchronised_data_operation(self, seconds=0.2, timestamp=None):
        """
        Synchronise data operations between FPGAs.

        :param seconds: Number of seconds to delay operation
        :param timestamp: Timestamp at which tile will be synchronised

        :return: timestamp written into FPGA timestamp request register
        :rtype: int
        """
        # Wait while previous data requests are processed
        while (
            self.tpm["fpga1.lmc_gen.request"] != 0
            or self.tpm["fpga2.lmc_gen.request"] != 0
        ):
            self.logger.info("Waiting for data request to be cleared by firmware...")
            time.sleep(0.05)

        self.logger.debug("Command accepted")

        # Read timestamp
        if timestamp is not None:
            t0 = timestamp
        else:
            t0 = max(
                self.tpm["fpga1.pps_manager.timestamp_read_val"],
                self.tpm["fpga2.pps_manager.timestamp_read_val"],
            )

        # Set arm timestamp
        # delay = number of frames to delay * frame time (shift by 8)
        delay = seconds * (1 / (1080 * 1e-9) / 256)
        t1 = t0 + int(delay)
        for fpga in self.tpm.tpm_fpga:
            fpga.fpga_apply_sync_delay(t1)
        return t1

    @connected
    def check_synchronised_data_operation(self, requested_timestamp=None):
        """
        Check if synchronise data operations between FPGAs is successful.

        :param requested_timestamp: Timestamp written into FPGA timestamp request register, if None it will be read
        from the FPGA register

        :return: Operation success
        :rtype: bool
        """
        if requested_timestamp is None:
            t_arm1 = self.tpm["fpga1.pps_manager.timestamp_req_val"]
            t_arm2 = self.tpm["fpga2.pps_manager.timestamp_req_val"]
        else:
            t_arm1 = requested_timestamp
            t_arm2 = requested_timestamp
        t_now1 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        t_now2 = self.tpm["fpga2.pps_manager.timestamp_read_val"]
        t_now_max = max(t_now1, t_now2)
        t_arm_min = min(t_arm1, t_arm2)
        t_margin = t_arm_min - t_now_max
        if t_margin <= 0:
            self.logger.error("Synchronised operation failed!")
            self.logger.error("Requested timestamp: " + str(t_arm_min))
            self.logger.error("Current timestamp: " + str(t_now_max))
            return False
        self.logger.debug("Synchronised operation successful!")
        self.logger.debug("Requested timestamp: " + str(t_arm_min))
        self.logger.debug("Current timestamp: " + str(t_now_max))
        self.logger.debug("Margin: " + str((t_arm_min - t_now_max) * 256 * 1.08e-6) + "s")
        return True

    @connected
    def synchronised_beamformer_coefficients(self, timestamp=None, seconds=0.2):
        """
        Synchronise beamformer coefficients download.

        :param timestamp: Timestamp to synchronise against
        :param seconds: Number of seconds to delay operation
        """
        # Read timestamp
        if timestamp is None:
            t0 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        else:
            t0 = timestamp

        # Set arm timestamp
        # delay = number of frames to delay * frame time (shift by 8)
        delay = seconds * (1 / (1080 * 1e-9) / 256)
        for f in ["fpga1", "fpga2"]:
            self.tpm[f + ".beamf.timestamp_req"] = t0 + int(delay)

    @connected
    def start_acquisition(self, start_time=None, delay=2, tpm_start_time=None):
        """
        Start data acquisition.

        :param start_time: Time for starting (seconds)
        :param delay: delay after start_time (seconds)
        :param tpm_start_time: TPM will act as if it is started at this time (seconds)
        """
        devices = ["fpga1", "fpga2"]
        for fpga in devices:
            self.tpm[f"{fpga}.regfile.eth10g_ctrl"] = 0x0

        # Temporary (moved here from TPM control)
        if len(self.tpm.find_register("fpga1.regfile.c2c_stream_header_insert")) > 0:
            self.tpm["fpga1.regfile.c2c_stream_header_insert"] = 0x1
            self.tpm["fpga2.regfile.c2c_stream_header_insert"] = 0x1
        else:
            self.tpm["fpga1.regfile.c2c_stream_ctrl.header_insert"] = 0x1
            self.tpm["fpga2.regfile.c2c_stream_ctrl.header_insert"] = 0x1

        if len(self.tpm.find_register("fpga1.regfile.lmc_stream_demux")) > 0:
            self.tpm["fpga1.regfile.lmc_stream_demux"] = 0x1
            self.tpm["fpga2.regfile.lmc_stream_demux"] = 0x1

        for fpga in devices:
            # Disable start force (not synchronised start)
            self.tpm[f"{fpga}.pps_manager.start_time_force"] = 0x0
            self.tpm[f"{fpga}.lmc_gen.timestamp_force"] = 0x0

        # Read current sync time
        if start_time is None:
            t0 = self.tpm["fpga1.pps_manager.curr_time_read_val"]
        else:
            t0 = start_time

        sync_time = int(t0 + delay)

        if tpm_start_time is None:
            tpm_sync_time = sync_time
        else:
            tpm_sync_time = int(tpm_start_time)
        
        clock_freq = 200e6 # ADC data clock
        frame_period =  1.08e-6 # 27/32 * 1024 * ADC sample rate
        time_diff = sync_time - tpm_sync_time
        start_frame = int(np.ceil(time_diff/frame_period))
        frame_offset = int(np.round((start_frame*frame_period - time_diff)*clock_freq))
        start_timestamp_hi = int(start_frame >> 32)
        start_timestamp_lo = start_frame & 0xffffffff

        # Write start time
        if self.tpm.tpm_test_firmware[0].station_beamformer_implemented:
            self.set_beamformer_epoch(sync_time)
        for fpga in devices:
            
            if not self.tpm.has_register(f"{fpga}.pps_manager.sync_time_actual_val") and tpm_start_time is not None:
                raise LibraryError(f"Syncing to other TPM's is not possible with this version of the firmware")
                
            if self.tpm.has_register(f"{fpga}.pps_manager.sync_time_actual_val"):
                self.tpm[f"{fpga}.pps_manager.sync_time_actual_val"] = sync_time
                # Set time TPM thinks the sync time happens
                self.tpm[f"{fpga}.pps_manager.sync_time_val"] = tpm_sync_time
                self.tpm[f"{fpga}.pps_manager.timestamp_rst_value_lo"] = start_timestamp_lo
                self.tpm[f"{fpga}.pps_manager.timestamp_rst_value_hi"] = start_timestamp_hi
                self.tpm[f"{fpga}.pps_manager.sync_time_val_fine"] = frame_offset
            else:
                self.tpm[f"{fpga}.pps_manager.sync_time_val"] = sync_time


    def check_communication(self):
        """
        Checks status of connection to TPM CPLD and FPGAs.
        Returns dictionary of connection status.
        Examples:
        - OK Status:
          {'CPLD': True, 'FPGA0': True, 'FPGA1': True}
        - TPM ON, FPGAs not programmed or TPM overtemperature self shutdown: 
          {'CPLD': True, 'FPGA0': False, 'FPGA1': False}
        - TPM OFF or Network Issue:
          {'CPLD': False, 'FPGA0': False, 'FPGA1': False}
        Non-destructive version of tile tpm_communication_check
        """
        status = {"CPLD": True, "FPGA0": True, "FPGA1": True}
        try:
            board_temp = self.get_temperature()
        except Exception as e:
            status["CPLD"] = False
            self.logger.error(f"Not able to communicate with CPLD: {str(e)}")
        try:
            magic0 = self[0x4]
            if magic0 != 0xA1CE55AD:
                self.logger.error(f"FPGA0 magic number is not correct {hex(magic0)}, expected: 0xA1CE55AD")
        except Exception as e:
            status["FPGA0"] = False
            self.logger.error(f"Not possible to communicate with the FPGA0: {str(e)}")
        try:
            magic1 = self[0x10000004]
            if magic1 != 0xA1CE55AD:
                self.logger.error(f"FPGA1 magic number is not correct {hex(magic1)}, expected: 0xA1CE55AD")
        except Exception as e:
            status["FPGA1"] = False
            self.logger.error(f"Not possible to communicate with the FPGA1: {str(e)}")
        return status
        
    @staticmethod
    def calculate_delay(current_delay, current_tc, target, margin):
        """
        Calculate delay for PPS pulse.

        :param current_delay: Current delay
        :type current_delay: int
        :param current_tc: Current phase register terminal count
        :type current_tc: int
        :param target: target delay
        :type target: int
        :param margin: marging, target +-margin
        :type margin: int
        :return: Modified phase register terminal count
        :rtype: int
        """
        ref_low = target - margin
        ref_hi = target + margin
        for n in range(5):
            if current_delay <= ref_low:
                new_delay = current_delay + int((n * 40) / 5)
                new_tc = (current_tc + n) % 5
                if new_delay >= ref_low:
                    return new_tc
            elif current_delay >= ref_hi:
                new_delay = current_delay - int((n * 40) / 5)
                new_tc = current_tc - n
                if new_tc < 0:
                    new_tc += 5
                if new_delay <= ref_hi:
                    return new_tc
            else:
                return current_tc

        raise ValueError("Unable to calculate delay for PPS pulse "
            f"current_delay {current_delay}, " 
            f"current_tc {current_tc}, "
            f"target {current_tc}, "
            f"margin {margin}"
        )

    # -----------------------------
    # Wrapper for data acquisition:
    # -----------------------------
    @connected
    def configure_integrated_channel_data(
        self, integration_time=0.5, first_channel=0, last_channel=512
    ):
        """
        Configure and start continuous integrated channel data.

        :param integration_time: integration time in seconds, defaults to 0.5
        :type integration_time: float, optional
        :param first_channel: first channel
        :type first_channel: int, optional
        :param last_channel: last channel
        :type last_channel: int, optional
        """
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].configure(
                "channel",
                integration_time,
                first_channel,
                last_channel,
                time_mux_factor=2,
                carousel_enable=0x1,
            )

    @connected
    def configure_integrated_beam_data(
        self, integration_time=0.5, first_channel=0, last_channel=192
    ):
        """
        Configure and start continuous integrated beam data.

        :param integration_time: integration time in seconds, defaults to 0.5
        :type integration_time: float, optional
        :param first_channel: first channel
        :type first_channel: int, optional
        :param last_channel: last channel
        :type last_channel: int, optional
        """
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].configure(
                "beamf",
                integration_time,
                first_channel,
                last_channel,
                time_mux_factor=1,
                carousel_enable=0x0,
            )

    @connected
    def stop_integrated_beam_data(self):
        """Stop transmission of integrated beam data."""
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].stop_integrated_beam_data()

    @connected
    def stop_integrated_channel_data(self):
        """Stop transmission of integrated channel data."""
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].stop_integrated_channel_data()

    @connected
    def stop_integrated_data(self):
        """Stop transmission of integrated data."""
        for i in range(len(self.tpm.tpm_integrator)):
            self.tpm.tpm_integrator[i].stop_integrated_data()

    # ------------------------------------------------------
    # Wrapper for valid timestamp request data acquisition
    # ------------------------------------------------------
    @connected
    def clear_timestamp_invalid_flag_register(
            self, daq_mode=None, fpga_id=None
    ):
        """
        Clear invalid timestamp request register for selected fpga and for
        selected LMC request mode . Default clears all registers for all modes

        :param daq_mode: string used to select which Flag register of the LMC to read
        :param fpga_id: FPGA_ID, 0 or 1. Default None will select both FPGAs
        """ 
        daq_modes_list = self.daq_modes_with_timestamp_flag if daq_mode is None else [daq_mode];
        fpga_list = range(len(self.tpm.tpm_test_firmware)) if fpga_id is None else [fpga_id]

        if daq_mode is not None and daq_mode not in self.daq_modes_with_timestamp_flag:
            raise LibraryError(f"Invalid daq_mode specified: {daq_mode} not supported")

        for selected_daq in daq_modes_list:
            for fpga in fpga_list:
                self[f"fpga{fpga + 1}.lmc_gen.timestamp_req_invalid.{selected_daq}"] = 0
                self.logger.info(f"Register fpga{fpga + 1}.lmc_gen.timestamp_req_invalid.{selected_daq} has been cleared!")

    @connected
    def check_valid_timestamp_request(
        self, daq_mode, fpga_id=None
    ):
        """
        Check valid timestamp request for various modes
        modes supported: raw_adc, channelizer and beamformer

        :param daq_mode: string used to select which Flag register of the LMC to read
        :param fpga_id: FPGA_ID, 0 or 1. Default None will select both FPGAs

        :return: boolean to indicate if the timestamp request is valid or not
        :rtype: boolean
        """
        C_VALID_TIMESTAMP_REQ = 0
        list_of_valid_timestamps = []
        fpga_list = range(len(self.tpm.tpm_test_firmware)) if fpga_id is None else [fpga_id]

        if daq_mode not in self.daq_modes_with_timestamp_flag:
            raise LibraryError(f"Invalid daq_mode specified: {daq_mode} not supported")

        for fpga in fpga_list:
            valid_request = self[f"fpga{fpga + 1}.lmc_gen.timestamp_req_invalid.{daq_mode}"] == C_VALID_TIMESTAMP_REQ
            list_of_valid_timestamps.append(valid_request)
            self.logger.debug(f"fpga{fpga + 1} {daq_mode} timestamp request is: {'VALID' if valid_request else 'INVALID'}")
        if not all(list_of_valid_timestamps):
            self.logger.error("INVALID LMC Data request")
            return False
        else:
            return True

    def select_method_to_check_valid_synchronised_data_request(
            self, daq_mode, t_request, fpga_id=None
    ):
        """
        Checks if Firmware contains the invalid flag register that raises a flag during synchronisation error.
        If the Firmware has the register then it will read it to check that the timestamp request was valid.
        If the register is not present, the software method will be used to calculate if the timestamp request was valid

        :param daq_mode: string used to select which Flag register of the LMC to read
        :param t_request: requested timestamp. Must be more than current timestamp to be synchronised successfuly
        :param fpga_id: FPGA_ID, 0 or 1. Default None
        """
        timestamp_invalid_flag_supported = self.tpm.has_register(f"fpga1.lmc_gen.timestamp_req_invalid.{daq_mode}")
        if timestamp_invalid_flag_supported:
            valid_request = self.check_valid_timestamp_request(daq_mode, fpga_id)
        else:
            self.logger.warning(
                "FPGA firmware doesn't support invalid data request flag, request will be validated by software"
            )
            valid_request = self.check_synchronised_data_operation(t_request)
        if valid_request:
            self.logger.info(f"Valid {daq_mode} Timestamp request")
            return
        self.clear_lmc_data_request()
        if timestamp_invalid_flag_supported:
            self.clear_timestamp_invalid_flag_register(daq_mode, fpga_id)
        self.logger.info("LMC Data request has been cleared")
        return

    # ------------------------------------
    # Wrapper for data acquisition: RAW
    # ------------------------------------
    @connected
    def send_raw_data(
        self, sync=False, timestamp=None, seconds=0.2, fpga_id=None
    ):
        """ Send raw data from the TPM
        :param sync: Synchronised flag
        :param timestamp: When to start
        :param seconds: Delay
        :param fpga_id: Specify which FPGA should transmit, 0,1, or None for both FPGAs"""

        self.stop_data_transmission()
        # Data transmission should be synchronised across FPGAs
        t_request = self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)

        # Send data from all FPGAs
        if fpga_id is None:
            fpgas = range(len(self.tpm.tpm_test_firmware))
        else:
            fpgas = [fpga_id]
        for i in fpgas:
            if sync:
                self.tpm.tpm_test_firmware[i].send_raw_data_synchronised()
            else:
                self.tpm.tpm_test_firmware[i].send_raw_data()

        # Check if synchronisation is successful
        self.select_method_to_check_valid_synchronised_data_request("raw_adc_mode", t_request, fpga_id)

    @connected
    def send_raw_data_synchronised(
        self, timestamp=None, seconds=0.2
    ):
        """  Send synchronised raw data
        :param timestamp: When to start
        :param seconds: Period"""
        self.send_raw_data(
            sync=True,
            timestamp=timestamp,
            seconds=seconds,
        )

    # ---------------------------- Wrapper for data acquisition: CHANNEL ------------------------------------
    @connected
    def send_channelised_data(
        self,
        number_of_samples=1024,
        first_channel=0,
        last_channel=511,
        timestamp=None,
        seconds=0.2,
    ):
        """ Send channelised data from the TPM
        :param number_of_samples: Number of spectra to send
        :param first_channel: First channel to send
        :param last_channel: Last channel to send
        :param timestamp: When to start transmission
        :param seconds: When to synchronise"""

        # Check if number of samples is a multiple of 32
        if number_of_samples % 32 != 0:
            new_value = (int(number_of_samples / 32) + 1) * 32
            self.logger.warning(
                f"{number_of_samples} is not a multiple of 32, using {new_value}"
            )
            number_of_samples = new_value

        self.stop_data_transmission()
        # Data transmission should be synchronised across FPGAs
        t_request = self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)

        # Send data from all FPGAs
        for i in range(len(self.tpm.tpm_test_firmware)):
            self.tpm.tpm_test_firmware[i].send_channelised_data(
                number_of_samples, first_channel, last_channel
            )

        # Check if synchronisation is successful
        self.select_method_to_check_valid_synchronised_data_request("channelized_mode", t_request)

    # ---------------------------- Wrapper for data acquisition: BEAM ------------------------------------
    @connected
    def send_beam_data(self, timeout=0, timestamp=None, seconds=0.2):
        """ Send beam data from the TPM
        :param timeout: When to stop
        :param timestamp: When to send
        :param seconds: When to synchronise"""

        self.stop_data_transmission()
        # Data transmission should be syncrhonised across FPGAs
        t_request = self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)

        # Send data from all FPGAs
        for i in range(len(self.tpm.tpm_test_firmware)):
            self.tpm.tpm_test_firmware[i].send_beam_data()

        # Check if synchronisation is successful
        self.select_method_to_check_valid_synchronised_data_request("beamformed_mode", t_request)

    # ---------------------------- Wrapper for data acquisition: CONT CHANNEL ----------------------------
    @connected
    def send_channelised_data_continuous(
        self,
        channel_id,
        number_of_samples=128,
        wait_seconds=0,
        timestamp=None,
        seconds=0.2,
    ):
        """ Continuously send channelised data from a single channel
        :param channel_id: Channel ID
        :param number_of_samples: Number of spectra to send
        :param wait_seconds: Wait time before sending data
        :param timestamp: When to start
        :param seconds: When to synchronise
        """
        time.sleep(wait_seconds)

        self.stop_data_transmission()
        # Data transmission should be synchronised across FPGAs
        t_request = self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)

        for i in range(len(self.tpm.tpm_test_firmware)):
            self.tpm.tpm_test_firmware[i].send_channelised_data_continuous(
                channel_id, number_of_samples
            )

        # Check if synchronisation is successful
        self.select_method_to_check_valid_synchronised_data_request("channelized_mode", t_request)

    # ---------------------------- Wrapper for data acquisition: NARROWBAND CHANNEL ----------------------------
    @connected
    def send_channelised_data_narrowband(
        self,
        frequency,
        round_bits,
        number_of_samples=128,
        wait_seconds=0,
        timestamp=None,
        seconds=0.2,
    ):
        """ Continuously send channelised data from a single channel
        :param frequency: Sky frequency to transmit
        :param round_bits: Specify which bits to round
        :param number_of_samples: Number of spectra to send
        :param wait_seconds: Wait time before sending data
        :param timestamp: When to start
        :param seconds: When to synchronise
        """
        time.sleep(wait_seconds)

        self.stop_data_transmission()
        # Data transmission should be synchronised across FPGAs
        t_request = self.synchronised_data_operation(timestamp=timestamp, seconds=seconds)

        for i in range(len(self.tpm.tpm_test_firmware)):
            self.tpm.tpm_test_firmware[i].send_channelised_data_narrowband(
                frequency, round_bits, number_of_samples
            )

        # Check if synchronisation is successful
        self.check_synchronised_data_operation(t_request)

    def stop_channelised_data_continuous(self):
        """ Stop sending channelised data """
        for i in range(len(self.tpm.tpm_test_firmware)):
            self.tpm.tpm_test_firmware[i].stop_channelised_data_continuous()

    def clear_lmc_data_request(self):
        """ Clear LMC data request register. This would be normally self-cleared by the firmware, however in case
        of failed synchronisation, the firmware will not clear the register. In that case the request register can
        be cleared by software to allow the next data request to be executed successfully."""
        for i in range(len(self.tpm.tpm_test_firmware)):
            self.tpm.tpm_test_firmware[i].clear_lmc_data_request()

    @connected
    def stop_data_transmission(self):
        """ Stop all data transmission from TPM"""
        self.logger.info("Stopping all transmission")
        # All data format transmission except channelised data continuous stops autonomously
        self.stop_channelised_data_continuous()

    # ---------------------------- Wrapper for multi channel acquisition ------------------------------------
    # -------------------- multichannel_tx is experimental - not needed in MCCS -----------------------------
    @connected
    def set_multi_channel_tx(self, instance_id, channel_id, destination_id):
        """ Set multichannel transmitter instance
        :param instance_id: Transmitter instance ID
        :param channel_id: Channel ID
        :param destination_id: 40G destination ID"""

        if not self.tpm.tpm_test_firmware[0].multiple_channel_tx_implemented:
            self.logger.error("Multichannel transmitter is not implemented in current FPGA firmware")

        # Data transmission should be synchronised across FPGAs
        self.tpm.multiple_channel_tx[0].set_instance(instance_id, channel_id, destination_id)
        self.tpm.multiple_channel_tx[1].set_instance(instance_id, channel_id, destination_id)

    @connected
    def start_multi_channel_tx(self, instances, timestamp=None, seconds=0.2):
        """ Start multichannel data transmission from the TPM
        :param instances: 64 bit integer, each bit addresses the corresponding TX transmitter
        :param seconds: synchronisation delay ID"""

        if not self.tpm.tpm_test_firmware[0].multiple_channel_tx_implemented:
            self.logger.error("Multichannel transmitter is not implemented in current FPGA firmware")

        if timestamp is None:
            t0 = max(
                self.tpm["fpga1.pps_manager.timestamp_read_val"],
                self.tpm["fpga2.pps_manager.timestamp_read_val"],
            )
        else:
            t0 = timestamp

        # Set arm timestamp
        # delay = number of frames to delay * frame time (shift by 8)
        delay = seconds * (1 / (1080 * 1e-9) / 256)
        t1 = t0 + int(delay)

        self.tpm.multiple_channel_tx[0].start(instances, t1)
        self.tpm.multiple_channel_tx[1].start(instances, t1)

        tn1 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
        tn2 = self.tpm["fpga2.pps_manager.timestamp_read_val"]
        if max(tn1, tn2) >= t1:
            self.logger.error("Synchronised operation failed!")

    @connected
    def stop_multi_channel_tx(self):
        """ Stop multichannel TX data transmission """
        if not self.tpm.tpm_test_firmware[0].multiple_channel_tx_implemented:
            self.logger.error("Multichannel transmitter is not implemented in current FPGA firmware")

        self.tpm.multiple_channel_tx[0].stop()
        self.tpm.multiple_channel_tx[1].stop()

    def set_multi_channel_dst_ip(self, dst_ip, destination_id):
        """ Set destination IP for a multichannel destination ID
                :param dst_ip: Destination IP address
                :param destination_id: 40G destination ID"""
        if not self.tpm.tpm_test_firmware[0].multiple_channel_tx_implemented:
            self.logger.error("Multichannel transmitter is not implemented in current FPGA firmware")

        for udp_core in self.tpm.tpm_10g_core:
            udp_core.set_dst_ip(dst_ip, destination_id)

    # ----------------------------
    # Wrapper for preadu methods
    # ----------------------------

    def has_preadu(self):
        """
        Check if tile has preADUs fitted.

        Gets preadu attribute "is_present" for each preADU.
        Returns True if both are present, else False.
        """
        fpgas = range(len(self.tpm.tpm_test_firmware))
        detected = []
        for fpga in fpgas:
            preadu_is_present = self.tpm.tpm_preadu[fpga].is_present
            detected.append(preadu_is_present)
            if preadu_is_present:
                self.logger.info(f"preADU {fpga} Detected")
            else:
                self.logger.info(f"preADU {fpga} Not Detected")
        return all(detected)

    def set_preadu_levels(self, levels):
        """
        Set preADU attenuation levels.

        :param levels: Desired attenuation levels for each ADC channel, in dB.
        """
        assert set(range(len(levels))) == set(self.preadu_signal_map)

        for preadu in self.tpm.tpm_preadu:
            if self.tpm_version == "tpm_v1_2":
                preadu.select_low_passband()
            preadu.read_configuration()

        for adc_channel, level in enumerate(levels):
            preadu_id = self.preadu_signal_map[adc_channel]["preadu_id"]
            preadu_ch = self.preadu_signal_map[adc_channel]["channel"]
            self.tpm.tpm_preadu[preadu_id].set_attenuation(level, [preadu_ch])

        for preadu in self.tpm.tpm_preadu:
            preadu.write_configuration()

    def get_preadu_levels(self):
        """
        Get preADU attenuation levels.

        :return: Attenuation levels corresponding to each ADC channel, in dB.
        """
        for preadu in self.tpm.tpm_preadu:
            if self.tpm_version == "tpm_v1_2":
                preadu.select_low_passband()
            preadu.read_configuration()

        levels = []
        for adc_channel in sorted(self.preadu_signal_map):
            preadu_id = self.preadu_signal_map[adc_channel]["preadu_id"]
            preadu_ch = self.preadu_signal_map[adc_channel]["channel"]
            attenuation = self.tpm.tpm_preadu[preadu_id].get_attenuation()[preadu_ch]
            levels.append(attenuation)
        return levels

    def equalize_preadu_gain(self, required_rms=20):
        """ Equalize the preadu gain to get target RMS"""

        # Get current preadu settings
        for preadu in self.tpm.tpm_preadu:
            if self.tpm_version == "tpm_v1_2":
                preadu.select_low_passband()
            preadu.read_configuration()

        # Get current RMS
        rms = self.get_adc_rms()

        # Loop over all signals
        for channel in list(self.preadu_signal_map.keys()):
            # Calculate required attenuation difference
            if rms[channel] / required_rms > 0:
                attenuation = 20 * math.log10(rms[channel] / required_rms)
            else:
                attenuation = 0

            # Apply attenuation
            pid = self.preadu_signal_map[channel]['preadu_id']
            channel = self.preadu_signal_map[channel]['channel']

            attenuation = self.tpm.tpm_preadu[pid].get_attenuation()[channel] + attenuation
            self.tpm.tpm_preadu[pid].set_attenuation(attenuation, [channel])

        for preadu in self.tpm.tpm_preadu:
            preadu.write_configuration()


    def set_preadu_attenuation(self, attenuation):
        """ Set same preadu attenuation in all preadus """

        # Get current preadu settings
        for preadu in self.tpm.tpm_preadu:
            if self.tpm_version == "tpm_v1_2":
                preadu.select_low_passband()
            preadu.read_configuration()
            preadu.set_attenuation(attenuation, list(range(16)))
            preadu.write_configuration()

    # ----------------------------
    # Wrapper for test generator
    # ----------------------------
    @connected
    def test_generator_set_tone(
        self, generator, frequency=100e6, amplitude=0.0, phase=0.0, load_time=0
    ):
        """
        Test generator tone setting.

        :param generator: generator select. 0 or 1
        :type generator: int
        :param frequency: Tone frequency in Hz
        :type frequency: float
        :param amplitude: Tone peak amplitude, normalized to 31.875 ADC units, resolution 0.125 ADU
        :type amplitude: float
        :param phase: Initial tone phase, in turns
        :type phase: float
        :param load_time: Time to start the tone.
        :type load_time: int
        """
        delay = 128
        if load_time == 0:
            t0 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
            load_time = t0 + delay
        self.tpm.test_generator[0].set_tone(
            generator, frequency, amplitude, phase, load_time
        )
        self.tpm.test_generator[1].set_tone(
            generator, frequency, amplitude, phase, load_time
        )

    @connected
    def test_generator_disable_tone(self, generator):
        """
        Test generator: disable tone. Set tone amplitude and frequency to 0

        :param generator: generator select. 0 or 1
        :type generator: int
        """
        self.test_generator_set_tone(generator, frequency=0.0, amplitude=0.0)

    @connected
    def test_generator_set_noise(self, amplitude=0.0, load_time=0):
        """
        Test generator Gaussian white noise setting.

        :param amplitude: Tone peak amplitude, normalized to 26.03 ADC units, resolution 0.102 ADU
        :type amplitude: float
        :param load_time: Time to start the tone.
        :type load_time: int
        """
        if load_time == 0:
            t0 = self.tpm["fpga1.pps_manager.timestamp_read_val"]
            load_time = t0 + 128
        self.tpm.test_generator[0].enable_prdg(amplitude, load_time)
        self.tpm.test_generator[1].enable_prdg(amplitude, load_time)

    @connected
    def set_test_generator_pulse(self, freq_code, amplitude=0.0):
        """
        Test generator Gaussian white noise setting.

        :param freq_code: Code for pulse frequency. Range 0 to 7: 16,12,8,6,4,3,2 times frame frequency
        :type freq_code: int
        :param amplitude: Tone peak amplitude, normalized to 127.5 ADC units, resolution 0.5 ADU
        :type amplitude: float
        """
        self.tpm.test_generator[0].set_pulse_frequency(freq_code, amplitude)
        self.tpm.test_generator[1].set_pulse_frequency(freq_code, amplitude)

    @connected
    def test_generator_input_select(self, inputs):
        """
        Specify ADC inputs which are substitute to test signal. Specified using a 32 bit
        mask, with LSB for ADC input 0.

        :param inputs: Bit mask of inputs using test signal
        :type inputs: int
        """
        self.tpm.test_generator[0].channel_select(inputs & 0xFFFF)
        self.tpm.test_generator[1].channel_select((inputs >> 16) & 0xFFFF)

    # ---------------------------------------
    # Wrapper for index and attribute methods
    # ---------------------------------------
    def __str__(self):
        """
        Produces list of tile information
        :return: Information string
        :rtype: str
        """
        info = self.info
        return f"\nTile Processing Module {info['hardware']['HARDWARE_REV']} Serial Number: {info['hardware']['SN']} \n"\
               f"{'_'*90} \n"\
               f"{' '*29}| \n"\
               f"Classification               | {info['hardware']['PN']}-{info['hardware']['BOARD_MODE']} \n"\
               f"Hardware Revision            | {info['hardware']['HARDWARE_REV']} \n"\
               f"Serial Number                | {info['hardware']['SN']} \n"\
               f"BIOS Revision                | {info['hardware']['bios']} \n"\
               f"Board Location               | {info['hardware']['LOCATION']} \n"\
               f"DDR Memory Capacity          | {info['hardware']['DDR_SIZE_GB']} GB per FPGA \n"\
               f"{'_'*29}|{'_'*60} \n"\
               f"{' '*29}| \n"\
               f"FPGA Firmware Design         | {info['fpga_firmware']['design']} \n"\
               f"FPGA Firmware Revision       | {info['fpga_firmware']['build']} \n"\
               f"FPGA Firmware Compile Time   | {info['fpga_firmware']['compile_time']} UTC \n"\
               f"FPGA Firmware Compile User   | {info['fpga_firmware']['compile_user']}  \n"\
               f"FPGA Firmware Compile Host   | {info['fpga_firmware']['compile_host']} \n"\
               f"FPGA Firmware Git Branch     | {info['fpga_firmware']['git_branch']} \n"\
               f"FPGA Firmware Git Commit     | {info['fpga_firmware']['git_commit']} \n"\
               f"{'_'*29}|{'_'*60} \n"\
               f"{' '*29}| \n"\
               f"1G (MGMT) IP Address         | {str(info['network']['1g_ip_address'])} \n"\
               f"1G (MGMT) MAC Address        | {info['network']['1g_mac_address']} \n"\
               f"1G (MGMT) Netmask            | {str(info['network']['1g_netmask'])} \n"\
               f"1G (MGMT) Gateway IP         | {str(info['network']['1g_gateway'])} \n"\
               f"EEP IP Address               | {str(info['hardware']['ip_address_eep'])} \n"\
               f"EEP Netmask                  | {str(info['hardware']['netmask_eep'])} \n"\
               f"EEP Gateway IP               | {str(info['hardware']['gateway_eep'])} \n"\
               f"40G Port 1 IP Address        | {str(info['network']['40g_ip_address_p1'])} \n"\
               f"40G Port 1 MAC Address       | {str(info['network']['40g_mac_address_p1'])} \n"\
               f"40G Port 1 Netmask           | {str(info['network']['40g_netmask_p1'])} \n"\
               f"40G Port 1 Gateway IP        | {str(info['network']['40g_gateway_p1'])} \n"\
               f"40G Port 2 IP Address        | {str(info['network']['40g_ip_address_p2'])} \n"\
               f"40G Port 2 MAC Address       | {str(info['network']['40g_mac_address_p2'])} \n"\
               f"40G Port 2 Netmask           | {str(info['network']['40g_netmask_p2'])} \n"\
               f"40G Port 2 Gateway IP        | {str(info['network']['40g_gateway_p2'])} \n"


    def __getitem__(self, key):
        """
        Read a register using indexing syntax: value=tile['registername']

        :param key: register address, symbolic or numeric
        :type key: str
        :return: indexed register content
        :rtype: int
        """
        return self.tpm[key]

    def __setitem__(self, key, value):
        """
        Set a register to a value.

        :param key: register address, symbolic or numeric
        :type key: str
        :param value: value to be written into register
        :type value: int
        """
        self.tpm[key] = value

    def __getattr__(self, name):
        """
        Handler for any requested attribute not found in the usual way; tries to return
        the corresponding attribute of the connected TPM.

        :param name: name of the requested attribute
        :type name: str

        :raises AttributeError: if neither this class nor the TPM has
            the named attribute.

        :return: the requested attribute
        :rtype: object
        """
        if name in dir(self.tpm):
            return getattr(self.tpm, name)
        else:
            raise AttributeError("'Tile' or 'TPM' object have no attribute " + name)

    # ------------------- Test methods

    @connected
    def start_40g_test(self, single_packet_mode=False, ipg=32):
        if not self.tpm.tpm_test_firmware[0].xg_40g_eth:
            self.logger.warning("40G interface is not implemented. Test not executed!")
            return 1

        self.stop_40g_test()

        eth0 = self.tpm.tpm_10g_core[0]
        eth1 = self.tpm.tpm_10g_core[1]

        eth0.test_start_rx(single_packet_mode)
        eth1.test_start_rx(single_packet_mode)

        ip0 = int(self.get_40g_core_configuration(0)["src_ip"])
        ip1 = int(self.get_40g_core_configuration(1)["src_ip"])

        ret = 0
        ret += eth0.test_start_tx(ip1, ipg=ipg)
        ret += eth1.test_start_tx(ip0, ipg=ipg)
        return ret

    def stop_40g_test(self):
        eth0 = self.tpm.tpm_10g_core[0]
        eth1 = self.tpm.tpm_10g_core[1]

        eth0.test_stop()
        eth1.test_stop()

    def check_40g_test_result(self):
        eth0 = self.tpm.tpm_10g_core[0]
        eth1 = self.tpm.tpm_10g_core[1]

        self.logger.info("FPGA1 result:")
        eth0.test_check_result()
        self.logger.info("FPGA2 result:")
        eth1.test_check_result()

    @connected
    def reset_eth_errors(self):
        if self["fpga1.regfile.feature.xg_eth_implemented"] == 1:
            for core in self.tpm.tpm_10g_core:
                core.reset_errors()

    def tpm_communication_check(self):
        """Brute force check to make sure we can communicate with programmed TPM."""

        # Re-try for max_attempts times before giving up
        max_attempts = 4
        for _n in range(max_attempts):
            try:
                self.tpm.calibrate_fpga_to_cpld()
                # read magic number from both FPGAs
                magic0 = self[0x4]
                magic1 = self[0x10000004]
                if magic0 == magic1 == 0xA1CE55AD:
                    return
                else:
                    self.logger.info(
                        "FPGA magic numbers are not correct "
                        + (hex(magic0) + ", " + hex(magic1))
                    )
            except Exception as e:  # noqa: F841
                pass

            self.logger.info(
                "Not possible to communicate with the FPGAs. Resetting CPLD..."
            )
            self.tpm.write_address(0x30000008, 0x8000, retry=False)  # Global Reset CPLD
            time.sleep(0.2)
            self.tpm.write_address(0x30000008, 0x8000, retry=False)  # Global Reset CPLD
            time.sleep(0.2)

    def get_firmware_list(self):
        """
        Get information for loaded firmware
        :return: Firmware information dictionary for each loaded firmware
        :rtype: list(dict)
        """
        # Got through all firmware information plugins and extract information
        # If firmware is not yet loaded, fill in some dummy information
        firmware = []
        if not hasattr(self.tpm, "tpm_firmware_information"):
            for _i in range(3):
                firmware.append(
                    {
                        "design": "unknown",
                        "major": 0,
                        "minor": 0,
                        "build": 0,
                        "time": "",
                        "author": "",
                        "board": "",
                    }
                )
        else:
            for plugin in self.tpm.tpm_firmware_information:
                # Update information
                plugin.update_information()
                # Check if design is valid:
                if plugin.get_design() is not None:
                    firmware.append(
                        {
                            "design": plugin.get_design(),
                            "major": plugin.get_major_version(),
                            "minor": plugin.get_minor_version(),
                            "build": plugin.get_build(),
                            "time": plugin.get_time(),
                            "author": plugin.get_user(),
                            "board": plugin.get_board(),
                        }
                    )
        return firmware

if __name__ == "__main__":
    tile = Tile(ip="10.0.10.2", port=10000)
    tile.connect()
