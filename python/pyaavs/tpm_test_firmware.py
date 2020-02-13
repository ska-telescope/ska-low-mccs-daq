from __future__ import division
from builtins import hex
from builtins import range
from past.utils import old_div
from math import ceil

__author__ = 'Alessio Magro'

import logging
import time

from pyfabil.plugins.firmwareblock import FirmwareBlock
from pyfabil.base.definitions import *
from time import sleep
from math import log, ceil


class TpmTestFirmware(FirmwareBlock):
    """ FirmwareBlock tests class """

    @firmware({'design': 'tpm_test', 'major': '1', 'minor': '>1'})
    @compatibleboards(BoardMake.TpmBoard)
    @friendlyname('tpm_test_firmware')
    @maxinstances(2)
    def __init__(self, board, **kwargs):
        """ TpmTestFirmware initializer
        :param board: Pointer to board instance
        """
        super(TpmTestFirmware, self).__init__(board)

        # Device must be specified in kwargs
        if kwargs.get('device', None) is None:
            raise PluginError("TpmTestFirmware requires device argument")
        self._device = kwargs['device']

        if kwargs.get('fsample', None) is None:
            logging.info("TpmTestFirmware: Setting default sampling frequency 800 MHz.")
            self._fsample = 800e6
        else:
            self._fsample = float(kwargs['fsample'])

        try:
            if self.board['fpga1.regfile.feature.xg_eth_implemented'] == 1:
                xg_eth = True
            else:
                xg_eth = False
        except:
            xg_eth = False

        # Load required plugins
        self._jesd1 = self.board.load_plugin("TpmJesd", device=self._device, core=0)
        self._jesd2 = self.board.load_plugin("TpmJesd", device=self._device, core=1)
        self._fpga = self.board.load_plugin('TpmFpga', device=self._device)
        if xg_eth:
            self._teng = [self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=0),
                          self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=1),
                          self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=2),
                          self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=3)]
        else:
            self._teng = [self.board.load_plugin("TpmTenGCore", device=self._device, core=0),
                          self.board.load_plugin("TpmTenGCore", device=self._device, core=1),
                          self.board.load_plugin("TpmTenGCore", device=self._device, core=2),
                          self.board.load_plugin("TpmTenGCore", device=self._device, core=3)]
        self._f2f = [self.board.load_plugin("TpmFpga2Fpga", core=0),
                     self.board.load_plugin("TpmFpga2Fpga", core=1)]
        self._beamf = self.board.load_plugin("BeamfFD", device=self._device)
        self._station_beamf = self.board.load_plugin("StationBeamformer", device=self._device)
        self._testgen = self.board.load_plugin("TpmTestGenerator", device=self._device)
        self._sysmon = self.board.load_plugin("TpmSysmon", device=self._device)
        self._patterngen = self.board.load_plugin("TpmPatternGenerator", device=self._device, fsample=self._fsample)
        self._power_meter = self.board.load_plugin("AdcPowerMeter", device=self._device, fsample=self._fsample)
        self._integrator = self.board.load_plugin("TpmIntegrator", device=self._device, fsample=self._fsample)
        self._spead_gen = [self.board.load_plugin("SpeadTxGen", device=self._device, core=0),
                           self.board.load_plugin("SpeadTxGen", device=self._device, core=1),
                           self.board.load_plugin("SpeadTxGen", device=self._device, core=2),
                           self.board.load_plugin("SpeadTxGen", device=self._device, core=3)]


        self._device_name = "fpga1" if self._device is Device.FPGA_1 else "fpga2"

    def fpga_clk_sync(self):
        """ FPGA synchronise clock"""

        if self._device_name == 'fpga1':

            fpga0_phase = self.board['fpga1.pps_manager.sync_status.cnt_hf_pps']

            # restore previous counters status using PPS phase
            self.board['fpga1.pps_manager.sync_tc.cnt_1_pulse'] = 0
            time.sleep(1.1)
            for n in range(5):
                fpga0_cnt_hf_pps = self.board['fpga1.pps_manager.sync_phase.cnt_hf_pps']
                if abs(fpga0_cnt_hf_pps - fpga0_phase) <= 3:
                    logging.debug("FPGA1 clock synced to PPS phase!")
                    break
                else:
                    rd = self.board['fpga1.pps_manager.sync_tc.cnt_1_pulse']
                    self.board['fpga1.pps_manager.sync_tc.cnt_1_pulse'] = rd + 1
                    time.sleep(1.1)

        if self._device_name == 'fpga2':

            # Synchronize FPGA2 to FPGA1 using sysref phase
            fpga0_phase = self.board['fpga1.pps_manager.sync_phase.cnt_1_sysref']

            self.board['fpga2.pps_manager.sync_tc.cnt_1_pulse'] = 0x0
            sleep(0.1)
            for n in range(5):
                fpga1_phase = self.board['fpga2.pps_manager.sync_phase.cnt_1_sysref']
                if fpga0_phase == fpga1_phase:
                    logging.debug("FPGA2 clock synced to SYSREF phase!")
                    break
                else:
                    rd = self.board['fpga2.pps_manager.sync_tc.cnt_1_pulse']
                    self.board['fpga2.pps_manager.sync_tc.cnt_1_pulse'] = rd + 1
                    sleep(0.1)

            logging.debug("FPGA1 clock phase before adc_clk alignment: " + hex(self.board['fpga1.pps_manager.sync_phase']))
            logging.debug("FPGA2 clock phase before adc_clk alignment: " + hex(self.board['fpga2.pps_manager.sync_phase']))

    def start_ddr_initialisation(self):
        """ Start DDR initialisation """
        if self.board['board.regfile.ctrl.en_ddr_vdd'] == 0:
            self.board['board.regfile.ctrl.en_ddr_vdd'] = 1
            time.sleep(0.5)
        logging.debug("%s DDR3 reset" % self._device_name)
        self.board["%s.regfile.reset.ddr_rst" % self._device_name] = 0x1
        self.board["%s.regfile.reset.ddr_rst" % self._device_name] = 0x0

    def check_ddr_initialisation(self):
        """ Check whether DDR has initialised """
        if self.board.memory_map.has_register("%s.regfile.stream_status.ddr_init_done" % self._device_name):
            status = self.board["%s.regfile.stream_status.ddr_init_done" % self._device_name]
        else:
            status = self.board["%s.regfile.status.ddr_init_done" % self._device_name]

        if status == 0x0:
            logging.debug("DDR3 %s is not initialised" % self._device_name)
            self.initialise_ddr()
        else:
            logging.debug("DDR3 %s initialised!" % self._device_name)
            return

    def initialise_ddr(self):
        """ Initialise DDR """

        if self.board['board.regfile.ctrl.en_ddr_vdd'] == 0:
            self.board['board.regfile.ctrl.en_ddr_vdd'] = 1
            time.sleep(0.5)

        for n in range(3):
            logging.debug("%s DDR3 reset" % self._device_name)
            self.board["%s.regfile.reset.ddr_rst" % self._device_name] = 0x1
            self.board["%s.regfile.reset.ddr_rst" % self._device_name] = 0x0

            for m in range(5):
                if self.board.memory_map.has_register("%s.regfile.stream_status.ddr_init_done" % self._device_name):
                    status = self.board["%s.regfile.stream_status.ddr_init_done" % self._device_name]
                else:
                    status = self.board["%s.regfile.status.ddr_init_done" % self._device_name]

                if status == 0x0:
                    logging.debug("Wait DDR3 %s init" % self._device_name)
                    time.sleep(0.2)
                else:
                    logging.debug("DDR3 %s initialised!" % self._device_name)
                    return

        logging.error("Cannot initilaise DDR3 %s" % self._device_name)

    def initialise_firmware(self):
        """ Initialise firmware components """
        max_retries = 4
        retries = 0

        while self.board['%s.jesd204_if.regfile_status' % self._device_name] & 0x1F != 0x1E and retries < max_retries:
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
            self._fpga.fpga_start(list(range(16)), list(range(16)))

            retries += 1
            sleep(0.2)

        if retries == max_retries:
            raise BoardError("TpmTestFirmware: Could not configure JESD cores")

        # Initialise DDR
        self.start_ddr_initialisation()

        # Initialise power meter
        self._power_meter.initialise()

        # Initialise 10G cores
        for teng in self._teng:
            teng.initialise_core()

    #######################################################################################

    def initialize_spead(self):
        """ Initialize SPEAD  """
        self.board["%s.lmc_spead_tx.control" % self._device_name] = 0x0400100C

    def send_raw_data(self):
        """ Send raw data from the TPM """
        self.board["%s.lmc_gen.raw_all_channel_mode_enable" % self._device_name] = 0x0
        self.board["%s.lmc_gen.request.raw_data" % self._device_name] = 0x1

    def send_raw_data_synchronised(self):
        """ Send raw data from the TPM """
        self.board["%s.lmc_gen.raw_all_channel_mode_enable" % self._device_name] = 0x1
        self.board["%s.lmc_gen.request.raw_data" % self._device_name] = 0x1

    def send_channelised_data(self, number_of_samples=128, first_channel=0, last_channel=511):
        """ Send channelized data from the TPM """
        self.board["%s.lmc_gen.channelized_pkt_length" % self._device_name] = number_of_samples - 1
        self.board["%s.lmc_gen.channelized_single_channel_mode.id" % self._device_name] = first_channel
        try:
            self.board["%s.lmc_gen.channelized_single_channel_mode.last" % self._device_name] = last_channel
        except:
            if last_channel != 511:
                logging.warning("Burst channel data in chunk mode is not supported by the running FPGA firmware")
        if len(self.board.find_register("%s.lmc_gen.channelized_ddc_mode" % self._device_name)) != 0:
            self.board["%s.lmc_gen.channelized_ddc_mode" % self._device_name] = 0x0 
        self.board["%s.lmc_gen.request.channelized_data" % self._device_name] = 0x1

    def send_channelised_data_continuous(self, channel_id, number_of_samples=128):
        """ Continuously send channelised data from a single channel
        :param channel_id: Channel ID
        """
        # self.board["%s.lmc_gen.channelized_single_channel_mode.enable" % self._device_name] = 1
        # self.board["%s.lmc_gen.channelized_single_channel_mode.id" % self._device_name] = channel_id
        self.board["%s.lmc_gen.channelized_single_channel_mode" % self._device_name] = (channel_id & 0x1FF) | 0x80000000
        self.board["%s.lmc_gen.channelized_pkt_length" % self._device_name] = number_of_samples - 1
        self.board["%s.lmc_gen.request.channelized_data" % self._device_name] = 0x1
        if len(self.board.find_register("%s.lmc_gen.channelized_ddc_mode" % self._device_name)) != 0:
            self.board["%s.lmc_gen.channelized_ddc_mode" % self._device_name] = 0x0 

    def send_channelised_data_narrowband(self, band_frequency, round_bits, number_of_samples=128):
        """ Continuously send channelised data from a single channel in narrowband mode
        :param band_frequency: central frequency (in Hz) of narrowband 
        :param round_bits: number of bits rounded after filter
        :param number_of_samples: samples per lmc packet
        """
        channel_spacing = old_div(800e6,1024)
        downsampling_factor = 128
        # Number of LO steps in the channel spacing
        lo_steps_per_channel = 2.**24/32.*27    
        if band_frequency < 50e6 or band_frequency > 350e6: 
            logging.error("Invalid frequency for narrowband lmc. Must be between 50e6 and 350e6")
            return
        hw_frequency = old_div(band_frequency,channel_spacing)
        channel_id = int(round(hw_frequency))
        lo_frequency = int(round((hw_frequency - channel_id)*lo_steps_per_channel)) &0xffffff
        # self.board["%s.lmc_gen.channelized_single_channel_mode.enable" % self._device_name] = 1
        # self.board["%s.lmc_gen.channelized_single_channel_mode.id" % self._device_name] = channel_id
        self.board["%s.lmc_gen.channelized_single_channel_mode" % self._device_name] = (channel_id & 0x1FF) | 0x80000000
        self.board["%s.lmc_gen.channelized_pkt_length" % self._device_name] = number_of_samples * downsampling_factor - 1
        if len(self.board.find_register("%s.lmc_gen.channelized_ddc_mode" % self._device_name)) != 0:
            self.board["%s.lmc_gen.channelized_ddc_mode" % self._device_name] = 0x90000000 | ((round_bits & 0x7)<<24) | lo_frequency
        self.board["%s.lmc_gen.request.channelized_data" % self._device_name] = 0x1

    def stop_channelised_data_narrowband(self):
        """ Stop transmission of narrowband channel data """
        self.stop_channelised_data_continuous()

    def stop_channelised_data_continuous(self):
        """ Stop transmission of continuous channel data """
        self.board["%s.lmc_gen.channelized_single_channel_mode.enable" % self._device_name] = 0x0

    def stop_channelised_data(self):
        """ Stop sending channelised data """
        self.board["%s.lmc_gen.channelized_single_channel_mode.enable" % self._device_name] = 0x0

    def send_beam_data(self):
        """ Send beam data from the TPM """
        self.board["%s.lmc_gen.request.beamformed_data" % self._device_name] = 0x1

    def stop_integrated_channel_data(self):
        """ Stop receiving integrated beam data from the board """
        self._integrator.stop_integrated_channel_data()

    def stop_integrated_beam_data(self):
        """ Stop receiving integrated beam data from the board """
        self._integrator.stop_integrated_beam_data()

    def stop_integrated_data(self):
        """ Stop transmission of integrated data"""
        self._integrator.stop_integrated_data()

    #######################################################################################

    def download_beamforming_weights(self, weights, antenna):
        """ Apply beamforming weights
        :param weights: Weights array
        :param antenna: Antenna ID
        """
        self.board["%s.beamf.ch%02dcoeff" % (self._device_name, antenna)] = weights

    ##################### Superclass method implementations #################################

    def initialise(self):
        """ Initialise TpmTestFirmware """
        logging.info("TpmTestFirmware has been initialised")
        return True

    def status_check(self):
        """ Perform status check
        :return: Status
        """
        logging.info("TpmTestFirmware : Checking status")
        return Status.OK

    def clean_up(self):
        """ Perform cleanup
        :return: Success
        """
        logging.info("TpmTestFirmware : Cleaning up")
        return True
