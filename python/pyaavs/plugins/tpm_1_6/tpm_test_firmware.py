# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
# Distributed under the terms of the GPL license.
# See LICENSE.txt for more info.
"""
Hardware functions for the TPM 1.6 hardware.

This is a transcript of the corresponding class from the pyaavs library,
with code style modified for SKA coding conventions. It depends heavily
on the pyfabil low level software and specific hardware module plugins.
"""
from __future__ import annotations  # allow forward references in type hints

__author__ = "Alessio Magro"

import logging
import time
from typing import Any, Optional

from pyfabil.base.definitions import (
    Status,
    PluginError,
    BoardError,
	BoardMake,
    Device,
    firmware,
    compatibleboards,
    friendlyname,
    maxinstances,
)
from pyaavs.plugins.tpm.tpm_test_firmware import TpmTestFirmware
from time import sleep

__all__ = ["Tpm_1_6_TestFirmware"]


class Tpm_1_6_TestFirmware(TpmTestFirmware):
    """FirmwareBlock tests class."""

    @firmware({"design": "tpm_test", "major": "1", "minor": ">1"})
    @compatibleboards(BoardMake.Tpm16Board)
    @friendlyname("tpm_test_firmware")
    @maxinstances(2)
    def __init__(self: Tpm_1_6_TestFirmware, board: Any, **kwargs: Any) -> None:
        """
        Initialize a new Tpm_1_6_TestFirmware instance.

        :param board: Pointer to board instance
        :param kwargs: named arguments

        :raises PluginError: Device argument must be specified
        """
        super(TpmTestFirmware, self).__init__(board)

        # Device must be specified in kwargs
        if kwargs.get("device", None) is None:
            raise PluginError("TpmTestFirmware requires device argument")
        self._device = kwargs["device"]

        if kwargs.get("fsample", None) is None:
            logging.info("TpmTestFirmware: Setting default sampling frequency 800 MHz.")
            self._fsample = 800e6
        else:
            self._fsample = float(kwargs["fsample"])

        self._dsp_core: Optional[bool] = kwargs.get("dsp_core")
        if self._dsp_core is None:
            logging.debug(
                "TpmTestFirmware: Setting default value True to dsp_core flag."
            )
            self._dsp_core = True
        if not self._dsp_core:
            logging.info(
                "TpmTestFirmware: dsp_core flag is False."
            )

        self._device_name = "fpga1" if self._device is Device.FPGA_1 else "fpga2"

        # retrieving firmware features from feature register
        self.xg_eth = False
        self.xg_40g_eth = False
        self.tile_beamformer_implemented = False
        self.station_beamformer_implemented = False
        self.antenna_buffer_implemented = False
        self.multiple_channel_tx_implemented = False
        self.multiple_channel_tx_nof_channels = 0

        if self.board.memory_map.has_register("fpga1.regfile.feature.xg_eth_implemented"):
            if self.board["fpga1.regfile.feature.xg_eth_implemented"] == 1:
                self.xg_eth = True

        if self.board.memory_map.has_register("fpga1.regfile.feature.xg_eth_40g_implemented"):
            if self.board["fpga1.regfile.feature.xg_eth_40g_implemented"] == 1:
                self.xg_40g_eth = True

        if self.board.memory_map.has_register("fpga1.dsp_regfile.feature.tile_beamformer_implemented"):
            if self.board["fpga1.dsp_regfile.feature.tile_beamformer_implemented"] == 1:
                self.tile_beamformer_implemented = True
        
        if self.board.memory_map.has_register("fpga1.dsp_regfile.feature.station_beamformer_implemented"):
            if self.board["fpga1.dsp_regfile.feature.station_beamformer_implemented"] == 1:
                self.station_beamformer_implemented = True

        if self.board.memory_map.has_register("fpga1.dsp_regfile.feature.antenna_buffer_implemented"):
            if self.board["fpga1.dsp_regfile.feature.antenna_buffer_implemented"] == 1:
                self.antenna_buffer_implemented = True

        if self.board.memory_map.has_register("fpga1.dsp_regfile.feature.multiple_channels_mode_implemented"):
            if self.board["fpga1.dsp_regfile.feature.multiple_channels_mode_implemented"] == 1:
                self.multiple_channel_tx_implemented = True
                self.multiple_channel_tx_nof_channels = self.board["fpga1.dsp_regfile.feature.nof_multiple_channels"]

        # plugins
        self._jesd1 = None
        self._jesd2 = None
        self._fpga = None
        self._teng = []
        self._f2f = []
        self._spead_gen = []
        self._fortyg = None
        self._sysmon = None
        self._clock_monitor = None
        self._beamf = None
        self._testgen = None
        self._patterngen = None
        self._power_meter = None
        self._integrator = None
        self._station_beamf = None
        self._antenna_buffer = None
        self._multiple_channel_tx = None

        self.load_plugin()

    def load_plugin(self: Tpm16TestFirmware) -> None:
        """Load required plugin."""
        self._jesd1 = self.board.load_plugin("TpmJesd", device=self._device, core=0, frame_length=216)
        self._jesd2 = self.board.load_plugin("TpmJesd", device=self._device, core=1, frame_length=216)
        self._fpga = self.board.load_plugin("TpmFpga", device=self._device)
        if self.xg_eth and not self.xg_40g_eth:
            self._teng = [
                self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=0),
                self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=1),
                self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=2),
                self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=3),
            ]
        elif self.xg_eth and self.xg_40g_eth:
            self._fortyg = self.board.load_plugin(
                "TpmFortyGCoreXg", device=self._device, core=0
            )
        else:
            self._teng = [
                self.board.load_plugin("TpmTenGCore", device=self._device, core=0),
                self.board.load_plugin("TpmTenGCore", device=self._device, core=1),
                self.board.load_plugin("TpmTenGCore", device=self._device, core=2),
                self.board.load_plugin("TpmTenGCore", device=self._device, core=3),
            ]
        self._f2f = self.board.load_plugin(
            "TpmFpga2FpgaAurora", device=self._device, core=0
        )
        self._sysmon = self.board.load_plugin("TpmSysmon", device=self._device)
        self._clock_monitor = self.board.load_plugin("TpmClockmon", device=self._device)
        if self._dsp_core:
            if self.tile_beamformer_implemented:
                self._beamf = self.board.load_plugin("BeamfFD", device=self._device)
            if self.station_beamformer_implemented:
                self._station_beamf = self.board.load_plugin(
                    "StationBeamformer", device=self._device
                )
            if self.antenna_buffer_implemented:
                self._antenna_buffer = self.board.load_plugin(
                    "AntennaBuffer", device=self._device
                )
            self._testgen = self.board.load_plugin(
                "TpmTestGenerator", device=self._device, fsample=self._fsample
            )
            self._patterngen = self.board.load_plugin(
                "TpmPatternGenerator", device=self._device, fsample=self._fsample
            )
            self._power_meter = self.board.load_plugin(
                "AdcPowerMeter", device=self._device, fsample=self._fsample
            )
            self._integrator = self.board.load_plugin(
                "TpmIntegrator", device=self._device, fsample=self._fsample
            )
            self._spead_gen = [
                self.board.load_plugin("SpeadTxGen", device=self._device, core=0),
                self.board.load_plugin("SpeadTxGen", device=self._device, core=1),
                self.board.load_plugin("SpeadTxGen", device=self._device, core=2),
                self.board.load_plugin("SpeadTxGen", device=self._device, core=3),
            ]
            if self.multiple_channel_tx_implemented:
                self._multiple_channel_tx = self.board.load_plugin(
                    "MultipleChannelTx", device=self._device
                )

    def initialise_firmware(self: Tpm16TestFirmware) -> None:
        """
        Initialise firmware components.

        :raises BoardError: cannot configure JESD core
        """
        max_retries = 4
        retries = 0

        while (
            self.board[self._device_name + ".jesd204_if.regfile_status"] & 0x1F != 0x1E
            and retries < max_retries
        ):
            # Reset FPGA
            self._fpga.fpga_global_reset()

            self._fpga.fpga_mmcm_config(self._fsample)
            self._fpga.fpga_jesd_gth_config(self._fsample)

            self._fpga.fpga_reset()

            # Start JESD cores
            self._jesd1.jesd_core_start()
            self._jesd2.jesd_core_start()

            # Initialise FPGAs
            # I have no idea what these ranges are
            self._fpga.fpga_start(range(16), range(16))

            retries += 1
            sleep(0.2)
            logging.debug(
                "Retrying JESD cores configuration of " + self._device_name.upper()
            )

        if retries == max_retries:
            raise BoardError("TpmTestFirmware: Could not configure JESD cores")

        # Initialise DDR
        self.start_ddr_initialisation()

        # Initialise power meter
        self._power_meter.initialise()

        # Initialise 10G/40G cores
        if self.board["fpga1.regfile.feature.xg_eth_implemented"] == 1:
            if self.xg_40g_eth:
                self._fortyg.initialise_core()
            else:
                for teng in self._teng:
                    teng.initialise_core()

        self._patterngen.initialise()

    def configure_40g_core_flyover_test(self):
        """
        Configure 40G cable polarity for SAMTEC board-to-board cable ARC6-08-07.0-LU-LD-2R-1,
        it can be activated using qsfp_detection = "flyover_test"
        """
        if self._device is Device.FPGA_1:
            self.board['fpga1.xg_udp.phy_ctrl.rx_polarity'] = 0xc
            self.board['fpga1.xg_udp.phy_ctrl.tx_polarity'] = 0xc
