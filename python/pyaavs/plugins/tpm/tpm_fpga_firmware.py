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
from pyfabil.plugins.firmwareblock import FirmwareBlock
from time import sleep

__all__ = ["TpmFpgaFirmware"]


class TpmFpgaFirmware(FirmwareBlock):
    """ TpmFpgaFirmware plugin """

    @firmware({"design": "tpm_test", "major": "1", "minor": ">1"})
    @compatibleboards(BoardMake.Tpm16Board)
    @friendlyname("tpm_test_firmware")  # TODO: Maybe one day we can rename this but its a huge refactor
    @maxinstances(2)
    def __init__(self: TpmFpgaFirmware, board: Any, **kwargs: Any) -> None:
        """
        Initialize a new TpmFpgaFirmware instance.

        :param board: Pointer to board instance
        :param kwargs: named arguments

        :raises PluginError: Device argument must be specified
        """
        super(TpmFpgaFirmware, self).__init__(board)

        # Device must be specified in kwargs
        if kwargs.get("device", None) is None:
            raise PluginError("TpmFpgaFirmware requires device argument")
        self._device = kwargs["device"]

        if kwargs.get("fsample", None) is None:
            logging.info("TpmFpgaFirmware: Setting default sampling frequency 800 MHz.")
            self._fsample = 800e6
        else:
            self._fsample = float(kwargs["fsample"])

        self._dsp_core: Optional[bool] = kwargs.get("dsp_core")
        if self._dsp_core is None:
            logging.debug(
                "TpmFpgaFirmware: Setting default value True to dsp_core flag."
            )
            self._dsp_core = True
        if not self._dsp_core:
            logging.info(
                "TpmFpgaFirmware: dsp_core flag is False."
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
            raise BoardError("TpmFpgaFirmware: Could not configure JESD cores")

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
    
    #######################################################################################

    def check_ddr_voltage(self: TpmFpgaFirmware) -> None:
        """Check if DDR voltage regulator is enabled, if not enable it. TPM 1.2 only"""
        if self.board.memory_map.has_register("board.regfile.ctrl.en_ddr_vdd"):
            if self.board["board.regfile.ctrl.en_ddr_vdd"] == 0:
                self.board["board.regfile.ctrl.en_ddr_vdd"] = 1
                time.sleep(0.5)

    def start_ddr_initialisation(self: TpmFpgaFirmware) -> None:
        """Start DDR initialisation."""
        self.check_ddr_voltage()
        logging.debug(self._device_name + " DDR reset")
        self.board[self._device_name + ".regfile.reset.ddr_rst"] = 0x1
        self.board[self._device_name + ".regfile.reset.ddr_rst"] = 0x0

    # TODO: Move to a DDR plugin
    def check_ddr_initialisation(self: TpmFpgaFirmware) -> bool:
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
            logging.debug("DDR of " + self._device_name.upper() + " is not initialised")
            return False
        else:
            logging.debug("DDR of " + self._device_name.upper() + " initialised!")
            return True

    # TODO: Move to a DDR plugin
    def check_ddr_user_reset_counter(self: TpmFpgaFirmware, show_result=True) -> int:
        """
        Return value of DDR user reset counter - increments each falling edge 
        of the DDR generated user logic reset.
        """
        count = self.board[f'{self._device_name}.ddr_if.status.ddr_user_rst_cnt']
        if show_result:
            logging.info(f'{self._device_name.upper()} error count {count}')
        return count
    
    # TODO: Move to a DDR plugin
    def clear_ddr_user_reset_counter(self: TpmFpgaFirmware) -> None:
        """Reset value of DDR reset counter"""
        self.board[f'{self._device_name}.ddr_if.status.ddr_monitoring_reset'] = 1

    def initialise_ddr(self: TpmFpgaFirmware) -> None:
        """Initialise DDR."""
        for _n in range(3):
            self.start_ddr_initialisation()
            for _m in range(5):
                time.sleep(0.2)
                if self.check_ddr_initialisation():
                    return
        logging.error("Cannot initialise DDR of " + self._device_name.upper())

    def check_data_router_status(self: TpmFpgaFirmware) -> int:
        """Returns value of data router error register."""
        if not self.board.memory_map.has_register(f'{self._device_name}.data_router.errors'):
            return None
        return self.board[f'{self._device_name}.data_router.errors']
    
    def clear_data_router_status(self: TpmFpgaFirmware) -> None:
        """Reset value of data router errors."""
        if not self.board.memory_map.has_register(f'{self._device_name}.data_router.errors'):
            return
        self.board[f'{self._device_name}.data_router.control.error_rst'] = 1
        return

    def check_data_router_discarded_packets(self: TpmFpgaFirmware) -> list:
        """Returns value of data router nof discarded packets registers."""
        if not self.board.memory_map.has_register(f'{self._device_name}.data_router.discarded_corrupt_spead_count'):
            return None
        return [self.board[f'{self._device_name}.data_router.discarded_corrupt_spead_count'],
                self.board[f'{self._device_name}.data_router.discarded_backpressure_spead_count']]

    def check_pps_status(self: TpmFpgaFirmware) -> bool:
        """Check PPS detected and error free"""
        pps_detect = self.board[f'{self._device_name}.pps_manager.pps_detected']
        pps_error = self.board[f'{self._device_name}.pps_manager.pps_errors.pps_count_error']
        return True if pps_detect and not pps_error else False
    
    def clear_pps_status(self: TpmFpgaFirmware) -> None:
        """Clear PPS errors"""
        self.board[f'{self._device_name}.pps_manager.pps_errors.pps_errors_rst'] = 1
        return

    def send_raw_data(self: TpmFpgaFirmware) -> None:
        """Send raw data from the TPM."""
        self.board[self._device_name + ".lmc_gen.raw_all_channel_mode_enable"] = 0x0
        self.board[self._device_name + ".lmc_gen.request.raw_data"] = 0x1

    def send_raw_data_synchronised(self: TpmFpgaFirmware) -> None:
        """Send raw data from the TPM."""
        self.board[self._device_name + ".lmc_gen.raw_all_channel_mode_enable"] = 0x1
        self.board[self._device_name + ".lmc_gen.request.raw_data"] = 0x1

    def send_channelised_data(
        self: TpmFpgaFirmware,
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

        # get bitfiled configuration of single_channel_mode register
        single_channel_mode_enable_shift = self.board.memory_map.register_list[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.enable"].shift
        single_channel_mode_last_shift = self.board.memory_map.register_list[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.last"].shift
        single_channel_mode_last_id = self.board.memory_map.register_list[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.id"].shift

        # build register value
        single_channel_mode_register = (0 << single_channel_mode_enable_shift) | \
                                       (last_channel << single_channel_mode_last_shift) | \
                                       (first_channel << single_channel_mode_last_id)

        # write register value into firmware register
        self.board[
            self._device_name + ".lmc_gen.channelized_single_channel_mode"
        ] = single_channel_mode_register

        self.board[self._device_name + ".lmc_gen.channelized_pkt_length"] = (
            number_of_samples - 1
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
        self: TpmFpgaFirmware, channel_id: int, number_of_samples: int = 128
    ) -> None:
        """
        Continuously send channelised data from a single channel.

        :param channel_id: Channel ID
        :param number_of_samples: contiguous time samples sent per channel
        """

        # get bitfiled configuration of single_channel_mode register
        single_channel_mode_enable_shift = self.board.memory_map.register_list[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.enable"].shift
        single_channel_mode_last_shift = self.board.memory_map.register_list[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.last"].shift
        single_channel_mode_last_id = self.board.memory_map.register_list[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.id"].shift

        # build register value
        single_channel_mode_register = (1 << single_channel_mode_enable_shift) | \
                                       (0x1FF << single_channel_mode_last_shift) | \
                                       (channel_id << single_channel_mode_last_id)

        # write register value into firmware register
        self.board[
            self._device_name + ".lmc_gen.channelized_single_channel_mode"
            ] = single_channel_mode_register

        self.board[self._device_name + ".lmc_gen.channelized_pkt_length"] = (
            number_of_samples - 1
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

    def send_channelised_data_narrowband(
        self: TpmFpgaFirmware,
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

        if (
                len(
                    self.board.find_register(
                        self._device_name + ".lmc_gen.channelized_ddc_mode"
                    )
                )
                == 0
        ):
            logging.error(
                "Narrowband channelizer is not implemented in current FPGA firmware!"
            )
            return

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

        # get bitfiled configuration of single_channel_mode register
        single_channel_mode_enable_shift = self.board.memory_map.register_list[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.enable"].shift
        single_channel_mode_last_shift = self.board.memory_map.register_list[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.last"].shift
        single_channel_mode_last_id = self.board.memory_map.register_list[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.id"].shift

        # build register value
        single_channel_mode_register = (1 << single_channel_mode_enable_shift) | \
                                       (0x1FF << single_channel_mode_last_shift) | \
                                       (channel_id << single_channel_mode_last_id)

        # write register value into firmware register
        self.board[
            self._device_name + ".lmc_gen.channelized_single_channel_mode"
            ] = single_channel_mode_register
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

    def stop_channelised_data_narrowband(self: TpmFpgaFirmware) -> None:
        """Stop transmission of narrowband channel data."""
        self.stop_channelised_data_continuous()

    def stop_channelised_data_continuous(self: TpmFpgaFirmware) -> None:
        """Stop transmission of continuous channel data."""
        self.board[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.enable"
        ] = 0x0

    def stop_channelised_data(self: TpmFpgaFirmware) -> None:
        """Stop sending channelised data."""
        self.board[
            self._device_name + ".lmc_gen.channelized_single_channel_mode.enable"
        ] = 0x0

    def clear_lmc_data_request(self: TpmFpgaFirmware) -> None:
        """Stop transmission of all LMC data."""
        self.board[self._device_name + ".lmc_gen.request"] = 0

    def send_beam_data(self: TpmFpgaFirmware) -> None:
        """Send beam data from the TPM."""
        self.board[self._device_name + ".lmc_gen.request.beamformed_data"] = 0x1

    def stop_integrated_channel_data(self: TpmFpgaFirmware) -> None:
        """Stop receiving integrated beam data from the board."""
        self._integrator.stop_integrated_channel_data()

    def stop_integrated_beam_data(self: TpmFpgaFirmware) -> None:
        """Stop receiving integrated beam data from the board."""
        self._integrator.stop_integrated_beam_data()

    def stop_integrated_data(self) -> None:
        """Stop transmission of integrated data."""
        self._integrator.stop_integrated_data()

    def download_beamforming_weights(
        self: TpmFpgaFirmware, weights: list[float], antenna: int
    ) -> None:
        """
        Apply beamforming weights.

        :param weights: Weights array
        :param antenna: Antenna ID
        """
        address = self._device_name + ".beamf.ch%02dcoeff" % antenna  # noqa: FS001
        self.board[address] = weights

    # Superclass method implementations

    def initialise(self: TpmFpgaFirmware) -> bool:
        """
        Initialise TpmFpgaFirmware.

        :return: success status
        """
        logging.info("TpmFpgaFirmware has been initialised")
        return True

    def status_check(self: TpmFpgaFirmware) -> Any:
        """
        Perform status check.

        :return: Status
        """
        logging.info("TpmFpgaFirmware : Checking status")
        return Status.OK

    def clean_up(self: TpmFpgaFirmware) -> bool:
        """
        Perform cleanup.

        :return: Success
        """
        logging.info("TpmFpgaFirmware : Cleaning up")
        return True

