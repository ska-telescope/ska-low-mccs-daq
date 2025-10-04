#  -*- coding: utf-8 -*
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""
This package implements SKA Low's MCCS DAQ subsystem.

The Monitoring Control and Calibration (MCCS) subsystem is responsible
for, amongst other things, monitoring and control of LFAA.
"""

__version__ = "4.1.1"
__version_info__ = (
    "ska-low-mccs-daq",
    __version__,
    "This package implements SKA Low's MCCS DAQ subsystem.",
)

__all__ = [
    "MccsDaqReceiver",
    "version",
    "main",
]

import sys

import tango.server

from .daq_receiver import MccsDaqReceiver
from .version import version_info

__version__ = version_info["version"]


def main() -> int:  # pragma: no cover
    """
    Entry point for module.

    :return: exit code
    """
    print("Launching DAQ device server with arguments")
    print(" ".join(sys.argv))
    return tango.server.run(classes=(MccsDaqReceiver,))


if __name__ == "__main__":
    print(__version__)
