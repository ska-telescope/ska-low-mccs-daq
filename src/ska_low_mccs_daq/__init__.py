# -*- coding: utf-8 -*-
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

__version__ = "0.6.0"
__version_info__ = (
    "ska-low-mccs-daq",
    "0.6.0",
    "This package implements SKA Low's MCCS's DAQ Receiver.",
)

__all__ = ["DaqHandler"]

from .daq_handler import DaqHandler
