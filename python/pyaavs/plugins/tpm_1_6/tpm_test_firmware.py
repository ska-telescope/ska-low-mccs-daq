# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
# Distributed under the terms of the GPL license.
# See LICENSE.txt for more info.
"""
Hardware functions for the TPM 1.6 hardware.

This is derived from pyaavs object and depends heavily on the pyfabil
low level software and specific hardware module plugins.
"""
from __future__ import annotations  # allow forward references in type hints

__author__ = "Alessio Magro"

import logging
import time
from typing import Any, Optional

from pyfabil.base.definitions import (
    firmware,
    compatibleboards,
    friendlyname,
    maxinstances,
    BoardMake,
    PluginError,
    BoardError,
    Device,
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
        Tpm_1_6_TestFirmware initializer.

        :param board: Pointer to board instance
        :param kwargs: named arguments

        :raises PluginError: Device parameter must be specified
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
            logging.info(
                "TpmTestFirmware: Setting default value True to dsp_core flag."
            )
            self._dsp_core = True

        try:
            if self.board["fpga1.regfile.feature.xg_eth_implemented"] == 1:
                self.xg_eth = True
            else:
                self.xg_eth = False
            if self.board["fpga1.regfile.feature.xg_eth_40g_implemented"] == 1:
                self.xg_40g_eth = True
            else:
                self.xg_40g_eth = False
        except Exception:
            self.xg_eth = False
            self.xg_40g_eth = False

        self._jesd1 = None
        self._jesd2 = None
        self._fpga = None
        self._teng = []
        self._f2f = []
        self._spead_gen = []
        self._fortyg = None
        self._sysmon = None
        self._beamf = None
        self._testgen = None
        self._patterngen = None
        self._power_meter = None
        self._integrator = None
        self._station_beamf = None
        self.load_plugin()

        self._device_name = "fpga1" if self._device is Device.FPGA_1 else "fpga2"

    def load_plugin(self: Tpm16TestFirmware) -> None:
        """Load required plugin."""
        self._jesd1 = self.board.load_plugin("TpmJesd", device=self._device, core=0)
        self._jesd2 = self.board.load_plugin("TpmJesd", device=self._device, core=1)
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
        if self._dsp_core:
            self._beamf = self.board.load_plugin("BeamfFD", device=self._device)
            self._station_beamf = self.board.load_plugin(
                "StationBeamformer", device=self._device
            )
            self._testgen = self.board.load_plugin(
                "TpmTestGenerator", device=self._device
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

    def start_ddr_initialisation(self: Tpm16TestFirmware) -> None:
        """Start DDR initialisation."""
        logging.debug(self._device_name + " DDR4 reset")
        self.board[self._device_name + ".regfile.reset.ddr_rst"] = 0x1
        self.board[self._device_name + ".regfile.reset.ddr_rst"] = 0x0

    def initialise_ddr(self: Tpm16TestFirmware) -> None:
        """Initialise DDR."""
        for _n in range(3):
            logging.debug(self._device_name + " DDR3 reset")
            self.board[self._device_name + ".regfile.reset.ddr_rst"] = 0x1
            self.board[self._device_name + ".regfile.reset.ddr_rst"] = 0x0

            for _m in range(5):
                if self.board.memory_map.has_register(
                    self._device_name + ".regfile.stream_status.ddr_init_done"
                ):
                    status = self.board[
                        self._device_name + ".regfile.stream_status.ddr_init_done"
                    ]
                else:
                    status = self.board[
                        self._device_name + ".regfile.status.ddr_init_done"
                    ]

                if status == 0x0:
                    logging.debug("Wait DDR3 " + self._device_name + " init")
                    time.sleep(0.2)
                else:
                    logging.debug("DDR3 " + self._device_name + " initialised!")
                    return

        logging.error("Cannot initilaise DDR3 " + self._device_name)

    def initialise_firmware(self: Tpm16TestFirmware) -> None:
        """
        Initialise firmware components.

        :raises BoardError: if JESD204 cannot be initialised
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
            logging.warning(
                "Retrying JESD cores configuration of " + self._device_name.upper()
            )

        if retries == max_retries:
            raise BoardError("TpmTestFirmware: Could not configure JESD cores")

        # Initialise DDR
        self.start_ddr_initialisation()

        # Initialise power meter
        self._power_meter.initialise()

        # Initialise 10G/40G cores
        if self.xg_40g_eth:
            self._fortyg.initialise_core()
        else:
            for teng in self._teng:
                teng.initialise_core()

        self._patterngen.initialise()
