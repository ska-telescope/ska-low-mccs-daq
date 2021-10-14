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
Hardware functions for the TPM 1.6 hardware.
"""
import functools
import logging
import os

from pyfabil.base.definitions import Device, LibraryError, BoardError
from pyfabil.base.utils import ip2long
from pyfabil.boards.tpm_1_6 import TPM_1_6
from pyaavs.tile import Tile


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
            logging.warn("Cannot call function " + f.__name__ + " on unconnected TPM")
            raise LibraryError(
                "Cannot call function " + f.__name__ + " on unconnected TPM"
            )
        else:
            return f(self, *args, **kwargs)

    return wrapper


class Tile_1_6(Tile):
    """
    Tile hardware interface library. Methods specific for TPM 1.6.
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
        Initialize a new instance.

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
        super(Tile_1_6, self).__init__(
            ip, port, lmc_ip, lmc_port, sampling_rate, logger
        )

    # Main functions ------------------------------------
    def tpm_version(self):
        """
        Determine whether this is a TPM V1.2 or TPM V1.6
        :return: TPM hardware version
        :rtype: string
        """
        return "tpm_v1_6"

    def connect(
        self,
        initialise=False,
        load_plugin=True,
        enable_ada=False,
        enable_adc=True,
        dsp_core=True,
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
        """
        # Try to connect to board, if it fails then set tpm to None
        self.tpm = TPM_1_6()

        # Add plugin directory (load module locally)
        tf = __import__("pyaavs.plugins.tpm_1_6.tpm_test_firmware", fromlist=[None])
        self.tpm.add_plugin_directory(os.path.dirname(tf.__file__))

        try:
            self.tpm.connect(
                ip=self._ip,
                port=self._port,
                initialise=initialise,
                simulator=not load_plugin,
                enable_ada=enable_ada,
                enable_adc=enable_adc,
                fsample=self._sampling_rate,
            )
        except (BoardError, LibraryError):
            self.tpm = None
            self.logger.error("Failed to connect to board at " + self._ip)
            return
        # Load tpm test firmware for both FPGAs (no need to load in simulation)
        if load_plugin and self.tpm.is_programmed():
            self.tpm.load_plugin(
                "Tpm_1_6_TestFirmware",
                device=Device.FPGA_1,
                fsample=self._sampling_rate,
                dsp_core=dsp_core,
            )
            self.tpm.load_plugin(
                "Tpm_1_6_TestFirmware",
                device=Device.FPGA_2,
                fsample=self._sampling_rate,
                dsp_core=dsp_core,
            )
        elif not self.tpm.is_programmed():
            logging.warning("TPM is not programmed! No plugins loaded")

    def initialise(self, enable_ada=False, enable_test=False, enable_adc=True):
        """
        Connect and initialise.

        :param enable_ada: enable adc amplifier, Not present in most TPM versions
        :type enable_ada: bool
        :param enable_test: setup internal test signal generator instead of ADC
        :param enable_adc: Enable ADC
        :type enable_adc: bool
        :type enable_test: bool
        """
        # Connect to board
        self.connect(initialise=True, enable_ada=enable_ada, enable_adc=enable_adc)

        # Before initialing, check if TPM is programmed
        if not self.tpm.is_programmed():
            logging.error("Cannot initialise board which is not programmed")
            return

        # Disable debug UDP header
        self.tpm["board.regfile.ena_header"] = 0x1

        # Initialise firmware plugin
        for firmware in self.tpm.tpm_test_firmware:
            firmware.initialise_firmware()

        # Set LMC IP
        self.tpm.set_lmc_ip(self._lmc_ip, self._lmc_port)

        # Enable C2C streaming
        self.tpm["board.regfile.ena_stream"] = 0x1
        # self.tpm['board.regfile.ethernet_pause']=10000
        self.set_c2c_burst()

        # Synchronise FPGAs
        self.sync_fpgas()

        # Initialize f2f link
        for f2f in self.tpm.tpm_f2f:
            f2f.assert_reset()
        for f2f in self.tpm.tpm_f2f:
            f2f.deassert_reset()

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
        self.set_default_eth_configuration()

        for firmware in self.tpm.tpm_test_firmware:
            firmware.check_ddr_initialisation()

    def f2f_aurora_test_start(self):
        """Start test on Aurora f2f link."""
        for f2f in self.tpm.tpm_f2f:
            f2f.start_tx_test()
        for f2f in self.tpm.tpm_f2f:
            f2f.start_rx_test()

    def f2f_aurora_test_check(self):
        """Get test results for Aurora f2f link Tests printed on stdout."""
        for f2f in self.tpm.tpm_f2f:
            f2f.get_test_result()

    def f2f_aurora_test_stop(self):
        """Stop test on Aurora f2f link."""
        for f2f in self.tpm.tpm_f2f:
            f2f.stop_test()
