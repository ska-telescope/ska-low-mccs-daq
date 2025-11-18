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

__version__ = "5.0.0"
__version_info__ = str(
    (
        "ska-low-mccs-daq",
        __version__,
        "This package implements SKA Low's MCCS DAQ subsystem.",
    )
).replace("'", "")

__all__ = [
    "MccsDaqReceiver",
    "version",
    "main",
]

import tango.server

from .daq_receiver import MccsDaqReceiver
from .version import version_info

__version__ = version_info["version"]


def main(*args: str, **kwargs: str) -> int:  # pragma: no cover
    """
    Entry point for module.

    :param args: positional arguments
    :param kwargs: named arguments

    :return: exit code
    """
    return tango.server.run(classes=(MccsDaqReceiver,), args=args or None, **kwargs)


if __name__ == "__main__":
    print(__version__)
