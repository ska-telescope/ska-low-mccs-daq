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

__version__ = "4.1.0"
__version_info__ = (
    "ska-low-mccs-daq",
    __version__,
    "This package implements SKA Low's MCCS DAQ subsystem.",
)

__all__ = [
    "MccsDaqReceiver",
    "version",
    "daq_device_server",
]

import sys

import tango.server

from .daq_receiver import MccsDaqReceiver
from .version import version_info

__version__ = version_info["version"]


def daq_device_server() -> int:  # pragma: no cover
    """
    Entry point that runs a Tango device server for DAQ devices.

    :return: exit code
    """
    print(f"Launching DAQ device server with arguments:\n\t{' '.join(sys.argv)}")
    return tango.server.run((MccsDaqReceiver,))


if __name__ == "__main__":
    print(__version__)
