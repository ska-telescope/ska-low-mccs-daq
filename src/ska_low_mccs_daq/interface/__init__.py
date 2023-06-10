# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""
This subpackage implements the monitoring and control interface to DAQ.

That is, the interface by which the DAQ Tango device communicates
with the DAQ itself.
"""


__all__ = [
    "DaqClient",
    # "DaqServer",
]

from .client import DaqClient

# from .server import DaqServer
