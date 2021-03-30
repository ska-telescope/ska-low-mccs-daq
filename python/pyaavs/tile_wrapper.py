import functools
import logging
import socket
import threading
import os

from datetime import datetime
from sys import stdout
import numpy as np
import time
import struct

from pyfabil.base.definitions import *
from pyfabil.base.utils import ip2long
from pyfabil.boards.tpm_generic import TPMGeneric

from pyaavs.tile import Tile as Tile_1_2
from pyaavs.tile_1_6 import Tile_1_6


class Tile(object):
    def __new__(cls, ip="10.0.10.2", port=10000, lmc_ip="10.0.10.1", lmc_port=4660, sampling_rate=800e6):
        _tpm = TPMGeneric()
        _tpm_version = _tpm.get_tpm_version(socket.gethostbyname(ip), port)
        del _tpm

        if _tpm_version == "tpm_v1_2":
            return Tile_1_2(ip, port, lmc_ip, lmc_port, sampling_rate)
        elif _tpm_version == "tpm_v1_5":
            return Tile_1_6(ip, port, lmc_ip, lmc_port, sampling_rate)
        else:
            raise LibraryError("TPM version not supported" % _tpm_version)

    def __init__(self, ip="10.0.10.2", port=10000, lmc_ip="10.0.10.1", lmc_port=4660, sampling_rate=800e6):
        pass
