__author__ = 'Alessio Magro'

import logging
from time import sleep

from pyaavs.tpm_test_firmware import TpmTestFirmware
from pyfabil.base.definitions import *


class Tpm_1_6_TestFirmware(TpmTestFirmware):
    """ FirmwareBlock tests class """

    @firmware({'design': 'tpm_test', 'major': '1', 'minor': '>1'})
    @compatibleboards(BoardMake.Tpm16Board)
    @friendlyname('tpm_test_firmware')
    @maxinstances(2)
    def __init__(self, board, **kwargs):
        """ Tpm_1_6_TestFirmware initializer
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
            self._teng = [self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=0, mii_prefix="xg_udp"),
                          self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=1, mii_prefix="xg_udp"),
                          self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=2, mii_prefix="xg_udp"),
                          self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=3, mii_prefix="xg_udp")]
        else:
            self._teng = []
                        # self.board.load_plugin("TpmTenGCore", device=self._device, core=0),
                        # self.board.load_plugin("TpmTenGCore", device=self._device, core=1),
                        # self.board.load_plugin("TpmTenGCore", device=self._device, core=2),
                        # self.board.load_plugin("TpmTenGCore", device=self._device, core=3)]
        self._f2f = [self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=0, nof_cores=8, mii_prefix="f2f"),
                     self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=1, nof_cores=8, mii_prefix="f2f"),
                     self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=2, nof_cores=8, mii_prefix="f2f"),
                     self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=3, nof_cores=8, mii_prefix="f2f"),
                     self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=4, nof_cores=8, mii_prefix="f2f"),
                     self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=5, nof_cores=8, mii_prefix="f2f"),
                     self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=6, nof_cores=8, mii_prefix="f2f"),
                     self.board.load_plugin("TpmTenGCoreXg", device=self._device, core=7, nof_cores=8, mii_prefix="f2f")]
        # self._beamf = self.board.load_plugin("BeamfFD", device=self._device)
        # self._station_beamf = self.board.load_plugin("StationBeamformer", device=self._device)
        # self._testgen = self.board.load_plugin("TpmTestGenerator", device=self._device)
        # self._sysmon = self.board.load_plugin("TpmSysmon", device=self._device)
        # self._patterngen = self.board.load_plugin("TpmPatternGenerator", device=self._device, fsample=self._fsample)
        self._power_meter = self.board.load_plugin("AdcPowerMeter", device=self._device, fsample=self._fsample)
        # self._integrator = self.board.load_plugin("TpmIntegrator", device=self._device, fsample=self._fsample)
        # self._spead_gen = [self.board.load_plugin("SpeadTxGen", device=self._device, core=0),
        #                    self.board.load_plugin("SpeadTxGen", device=self._device, core=1),
        #                    self.board.load_plugin("SpeadTxGen", device=self._device, core=2),
        #                    self.board.load_plugin("SpeadTxGen", device=self._device, core=3)]


        self._device_name = "fpga1" if self._device is Device.FPGA_1 else "fpga2"

    def start_ddr_initialisation(self):
        """ Start DDR initialisation """
        # In TPM 1.6 ddr_vdd is controled with en_fpga so it's already enabled to program FPGAs
        # if self.board['board.regfile.ctrl.en_ddr_vdd'] == 0:
        #     self.board['board.regfile.ctrl.en_ddr_vdd'] = 1
        #     time.sleep(0.5)
        logging.debug("%s DDR4 reset" % self._device_name)
        self.board["%s.regfile.reset.ddr_rst" % self._device_name] = 0x1
        self.board["%s.regfile.reset.ddr_rst" % self._device_name] = 0x0

    def initialise_ddr(self):
        """ Initialise DDR """
        return
        # if self.board['board.regfile.ctrl.en_ddr_vdd'] == 0:
        #     self.board['board.regfile.ctrl.en_ddr_vdd'] = 1
        #     time.sleep(0.5)
        #
        # for n in range(3):
        #     logging.debug("%s DDR3 reset" % self._device_name)
        #     self.board["%s.regfile.reset.ddr_rst" % self._device_name] = 0x1
        #     self.board["%s.regfile.reset.ddr_rst" % self._device_name] = 0x0
        #
        #     for m in range(5):
        #         if self.board.memory_map.has_register("%s.regfile.stream_status.ddr_init_done" % self._device_name):
        #             status = self.board["%s.regfile.stream_status.ddr_init_done" % self._device_name]
        #         else:
        #             status = self.board["%s.regfile.status.ddr_init_done" % self._device_name]
        #
        #         if status == 0x0:
        #             logging.debug("Wait DDR3 %s init" % self._device_name)
        #             time.sleep(0.2)
        #         else:
        #             logging.debug("DDR3 %s initialised!" % self._device_name)
        #             return
        #
        # logging.error("Cannot initilaise DDR3 %s" % self._device_name)

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
            self._fpga.fpga_start(range(16), range(16))

            retries += 1
            sleep(0.2)

        if retries == max_retries:
            raise BoardError("TpmTestFirmware: Could not configure JESD cores")

        # Initialise DDR
        self.start_ddr_initialisation()

        # Initialise power meter
        self._power_meter.initialise()

        # Initialise 10G cores
        #for teng in self._teng:
        #    teng.initialise_core()
    #######################################################################################
