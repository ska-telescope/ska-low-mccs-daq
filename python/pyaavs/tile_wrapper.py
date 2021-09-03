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
Hardware functions for the TPM hardware. Factory around the Tile_1_2 and Tile_1_6
modules: Queries the board version and selects the correct object.

This depends heavily on the
pyfabil low level software and specific hardware module plugins.
"""
import socket

from pyfabil.base.definitions import LibraryError
from pyfabil.boards.tpm_generic import TPMGeneric

from pyaavs.tile import Tile as Tile_1_2
from pyaavs.tile_1_6 import Tile_1_6


class Tile(object):
    """
    Wrapper for Tile12 and Tile16.

    Returns the right object depending on magic number in hardware.
    """

    def __new__(
        cls,
        ip="10.0.10.2",
        port=10000,
        lmc_ip="10.0.10.1",
        lmc_port=4660,
        sampling_rate=800e6,
        logger=None,
        tpm_version=None,

    ):
        """
        Create a new HwTile instance.

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
        :param tpm_version: TPM version: "tpm_v1_2" or "tpm_v1_6"
        :type tpm_version: str
        :return: Tile object for the correct board type
        :raises LibraryError: Invalid board type
        """
        if tpm_version is None:
            _tpm = TPMGeneric()
            _tpm_version = _tpm.get_tpm_version(socket.gethostbyname(ip), port)
            del _tpm
        else:
            _tpm_version = tpm_version
        # tpm_v1_5 and tpm_v1_6 are synonimous
        if _tpm_version == "tpm_v1_5":
            _tpm_version = "tpm_v1_6"

        if _tpm_version == "tpm_v1_2":
            return Tile_1_2(ip, port, lmc_ip, lmc_port, sampling_rate, logger)
        elif _tpm_version == "tpm_v1_6":
            return Tile_1_6(ip, port, lmc_ip, lmc_port, sampling_rate, logger)
        else:
            raise LibraryError("TPM version not supported: " + _tpm_version)

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
        Initialise a new HwTile instance.

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
        pass
