# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the GPL license.
# See LICENSE.txt for more info.
"""
Hardware plugins for the TPM 1.2 hardware.

This is a transcript of the corresponding class from the pyaavs library,
with code style modified for SKA coding conventions. It depends heavily
on the pyfabil low level software and specific hardware module plugins.
"""
from __future__ import annotations  # allow forward references in type hints

__author__ = "Alessio Magro"

import logging
import time
from typing import Any

from pyfabil.plugins.firmwareblock import FirmwareBlock
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
from time import sleep

__all__ = ["TpmTestFirmware"]


class TpmTestFirmware(FirmwareBlock):
    """FirmwareBlock tests class."""

    @firmware({"design": "tpm_test", "major": "1", "minor": ">1"})
    @compatibleboards(BoardMake.TpmBoard)
    @friendlyname("tpm_test_firmware")
    @maxinstances(2)
    def __init__(self: TpmTestFirmware, board: Any, **kwargs: Any) -> None:
        """
        Initialize a new TpmTestFirmware instance.

        :param board: Pointer to board instance
        :param kwargs: named arguments

        :raises PluginError: device argument must be specified
        """
        super(TpmTestFirmware, self).__init__(board)

        # Device must be specified in kwargs
        if "device" not in kwargs:
            raise PluginError("TpmTestFirmware requires device argument")
        self._device = kwargs["device"]

        if "fsample" not in kwargs:
            logging.info("TpmTestFirmware: Setting default sampling frequency 800 MHz.")
        self._fsample = kwargs.get("fsample", 800e6)
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

        if self.board["fpga1.dsp_regfile.feature.tile_beamformer_implemented"] == 1:
            self.tile_beamformer_implemented = True
        else:
            self.tile_beamformer_implemented = False

        if self.board["fpga1.dsp_regfile.feature.station_beamformer_implemented"] == 1:
            self.station_beamformer_implemented = True
        else:
            self.station_beamformer_implemented = False

        self.load_plugin()

        self._device_name = "fpga1" if self._device is Device.FPGA_1 else "fpga2"

    def load_plugin(self: TpmTestFirmware) -> None:
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
        self._f2f = [
            self.board.load_plugin("TpmFpga2Fpga", core=0),
            self.board.load_plugin("TpmFpga2Fpga", core=1),
        ]
        if self.tile_beamformer_implemented:
            self._beamf = self.board.load_plugin("BeamfFD", device=self._device)
        if self.station_beamformer_implemented:
            self._station_beamf = self.board.load_plugin(
                "StationBeamformer", device=self._device
            )
        self._testgen = self.board.load_plugin("TpmTestGenerator", device=self._device)
        self._sysmon = self.board.load_plugin("TpmSysmon", device=self._device)
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

    def fpga_clk_sync(self: TpmTestFirmware) -> None:
        """FPGA synchronise clock."""
        if self._device_name == "fpga1":

            fpga1_phase = self.board["fpga1.pps_manager.sync_status.cnt_hf_pps"]

            # restore previous counters status using PPS phase
            self.board["fpga1.pps_manager.sync_tc.cnt_1_pulse"] = 0
            time.sleep(1.1)
            for _n in range(5):
                fpga1_cnt_hf_pps = self.board["fpga1.pps_manager.sync_phase.cnt_hf_pps"]
                if abs(fpga1_cnt_hf_pps - fpga1_phase) <= 3:
                    logging.debug("FPGA1 clock synced to PPS phase!")
                    break
                else:
                    rd = self.board["fpga1.pps_manager.sync_tc.cnt_1_pulse"]
                    self.board["fpga1.pps_manager.sync_tc.cnt_1_pulse"] = rd + 1
                    time.sleep(1.1)

        if self._device_name == "fpga2":

            # Synchronize FPGA2 to FPGA1 using sysref phase
            fpga1_phase = self.board["fpga1.pps_manager.sync_phase.cnt_1_sysref"]

            self.board["fpga2.pps_manager.sync_tc.cnt_1_pulse"] = 0x0
            sleep(0.1)
            for _n in range(5):
                fpga2_phase = self.board["fpga2.pps_manager.sync_phase.cnt_1_sysref"]
                if fpga1_phase == fpga2_phase:
                    logging.debug("FPGA2 clock synced to SYSREF phase!")
                    break
                else:
                    rd = self.board["fpga2.pps_manager.sync_tc.cnt_1_pulse"]
                    self.board["fpga2.pps_manager.sync_tc.cnt_1_pulse"] = rd + 1
                    sleep(0.1)

            logging.debug(
                "FPGA1 clock phase before adc_clk alignment: "
                + hex(self.board["fpga1.pps_manager.sync_phase"])
            )
            logging.debug(
                "FPGA2 clock phase before adc_clk alignment: "
                + hex(self.board["fpga2.pps_manager.sync_phase"])
            )

    def start_ddr_initialisation(self: TpmTestFirmware) -> None:
        """Start DDR initialisation."""
        if self.board["board.regfile.ctrl.en_ddr_vdd"] == 0:
            self.board["board.regfile.ctrl.en_ddr_vdd"] = 1
            time.sleep(0.5)
        logging.debug(self._device_name + " DDR3 reset")
        self.board[self._device_name + ".regfile.reset.ddr_rst"] = 0x1
        self.board[self._device_name + ".regfile.reset.ddr_rst"] = 0x0

    def check_ddr_initialisation(self: TpmTestFirmware) -> None:
        """Check whether DDR has initialised."""
        if self.board.memory_map.has_register(
            self._device_name + ".regfile.stream_status.ddr_init_done"
        ):
            status = self.board[
                self._device_name + ".regfile.stream_status.ddr_init_done"
            ]
        else:
            status = self.board[self._device_name + ".regfile.status.ddr_init_done"]

        if status == 0x0:
            logging.debug("DDR3 " + self._device_name + " is not initialised")
            self.initialise_ddr()
        else:
            logging.debug("DDR3 " + self._device_name + " initialised!")
            return

    def initialise_ddr(self: TpmTestFirmware) -> None:
        """Initialise DDR."""
        if self.board["board.regfile.ctrl.en_ddr_vdd"] == 0:
            self.board["board.regfile.ctrl.en_ddr_vdd"] = 1
            time.sleep(0.5)

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

    def initialise_firmware(self: TpmTestFirmware) -> None:
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

    #######################################################################################


    def send_raw_data(self: TpmTestFirmware) -> None:
        """Send raw data from the TPM."""
        self.board[self._device_name + ".lmc_gen.raw_all_channel_mode_enable"] = 0x0
        self.board[self._device_name + ".lmc_gen.request.raw_data"] = 0x1

    def send_raw_data_synchronised(self: TpmTestFirmware) -> None:
        """Send raw data from the TPM."""
        self.board[self._device_name + ".lmc_gen.raw_all_channel_mode_enable"] = 0x1
        self.board[self._device_name + ".lmc_gen.request.raw_data"] = 0x1

    def send_channelised_data(
        self: TpmTestFirmware,
        number_of_samples: int = 128,
        first_channel: int = 0,
        last_channel: int = 511,
    ) -> None:
        """
        Send channelized data from the TPM.

        :param number_of_samples: contiguous time samples sent per channel
        :param first_channel: First channel transmitted
        :param last_channel: Last channel transmitted + 1 (python range convention)
        """
        self.board[self._device_name + ".lmc_gen.channelized_pkt_length"] = (
            number_of_samples - 1
        )
        self.board[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.id"
        ] = first_channel
        if (
            len(
                self.board.find_register(
                    self._device_name + ".lmc_gen.channelized_single_channel_mode.last"
                )
            )
            != 0
        ):
            self.board[
                self._device_name + ".lmc_gen.channelized_single_channel_mode.last"
            ] = last_channel
        else:
            if last_channel != 511:
                logging.warning(
                    "Burst channel data in chunk mode is not supported by the running FPGA firmware"
                )
        if (
            len(
                self.board.find_register(
                    self._device_name + ".lmc_gen.channelized_ddc_mode"
                )
            )
            != 0
        ):
            self.board[self._device_name + ".lmc_gen.channelized_ddc_mode"] = 0x0
        self.board[self._device_name + ".lmc_gen.request.channelized_data"] = 0x1

    def send_channelised_data_continuous(
        self: TpmTestFirmware, channel_id: int, number_of_samples: int = 128
    ) -> None:
        """
        Continuously send channelised data from a single channel.

        :param channel_id: Channel ID
        :param number_of_samples: contiguous time samples sent per channel
        """
        self.board[self._device_name + ".lmc_gen.channelized_single_channel_mode"] = (
            channel_id & 0x1FF
        ) | 0x80000000
        self.board[self._device_name + ".lmc_gen.channelized_pkt_length"] = (
            number_of_samples - 1
        )
        self.board[self._device_name + ".lmc_gen.request.channelized_data"] = 0x1
        if (
            len(
                self.board.find_register(
                    self._device_name + ".lmc_gen.channelized_ddc_mode"
                )
            )
            != 0
        ):
            self.board[self._device_name + ".lmc_gen.channelized_ddc_mode"] = 0x0

    def send_channelised_data_narrowband(
        self: TpmTestFirmware,
        band_frequency: int,
        round_bits: int,
        number_of_samples: int = 128,
    ) -> None:
        """
        Continuously send channelised data from a single channel in narrowband mode.

        :param band_frequency: central frequency (in Hz) of narrowband
        :param round_bits: number of bits rounded after filter
        :param number_of_samples: samples per lmc packet
        """
        channel_spacing = 800e6 / 1024
        downsampling_factor = 128
        # Number of LO steps in the channel spacing
        lo_steps_per_channel = 2.0 ** 24 / 32.0 * 27
        if band_frequency < 50e6 or band_frequency > 350e6:
            logging.error(
                "Invalid frequency for narrowband lmc. Must be between 50e6 and 350e6"
            )
            return
        hw_frequency = band_frequency / channel_spacing
        channel_id = int(round(hw_frequency))
        lo_frequency = (
            int(round((hw_frequency - channel_id) * lo_steps_per_channel)) & 0xFFFFFF
        )
        self.board[self._device_name + ".lmc_gen.channelized_single_channel_mode"] = (
            channel_id & 0x1FF
        ) | 0x80000000
        self.board[self._device_name + ".lmc_gen.channelized_pkt_length"] = (
            number_of_samples * downsampling_factor - 1
        )
        if (
            len(
                self.board.find_register(
                    self._device_name + ".lmc_gen.channelized_ddc_mode"
                )
            )
            != 0
        ):
            self.board[self._device_name + ".lmc_gen.channelized_ddc_mode"] = (
                0x90000000 | ((round_bits & 0x7) << 24) | lo_frequency
            )
        self.board[self._device_name + ".lmc_gen.request.channelized_data"] = 0x1

    def stop_channelised_data_narrowband(self: TpmTestFirmware) -> None:
        """Stop transmission of narrowband channel data."""
        self.stop_channelised_data_continuous()

    def stop_channelised_data_continuous(self: TpmTestFirmware) -> None:
        """Stop transmission of continuous channel data."""
        self.board[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.enable"
        ] = 0x0

    def stop_channelised_data(self: TpmTestFirmware) -> None:
        """Stop sending channelised data."""
        self.board[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.enable"
        ] = 0x0

    def send_beam_data(self: TpmTestFirmware) -> None:
        """Send beam data from the TPM."""
        self.board[self._device_name + ".lmc_gen.request.beamformed_data"] = 0x1

    def stop_integrated_channel_data(self: TpmTestFirmware) -> None:
        """Stop receiving integrated beam data from the board."""
        self._integrator.stop_integrated_channel_data()

    def stop_integrated_beam_data(self: TpmTestFirmware) -> None:
        """Stop receiving integrated beam data from the board."""
        self._integrator.stop_integrated_beam_data()

    def stop_integrated_data(self) -> None:
        """Stop transmission of integrated data."""
        self._integrator.stop_integrated_data()

    def download_beamforming_weights(
        self: TpmTestFirmware, weights: list[float], antenna: int
    ) -> None:
        """
        Apply beamforming weights.

        :param weights: Weights array
        :param antenna: Antenna ID
        """
        address = self._device_name + ".beamf.ch%02dcoeff" % antenna  # noqa: FS001
        self.board[address] = weights

    # Superclass method implementations

    def initialise(self: TpmTestFirmware) -> bool:
        """
        Initialise TpmTestFirmware.

        :return: success status
        """
        logging.info("TpmTestFirmware has been initialised")
        return True

    def status_check(self: TpmTestFirmware) -> Any:
        """
        Perform status check.

        :return: Status
        """
        logging.info("TpmTestFirmware : Checking status")
        return Status.OK

    def clean_up(self: TpmTestFirmware) -> bool:
        """
        Perform cleanup.

        :return: Success
        """
        logging.info("TpmTestFirmware : Cleaning up")
        return True
