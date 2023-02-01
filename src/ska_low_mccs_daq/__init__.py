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

__all__ = [
    # devices
    "MccsDaqReceiver",
    "MccsDaqServer",
    # device subpackages
    "daq_receiver",
    "gRPC_server",
]

from .daq_receiver import MccsDaqReceiver
from .gRPC_server.daq_grpc_server import MccsDaqServer
