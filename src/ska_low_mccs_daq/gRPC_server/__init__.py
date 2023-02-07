# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This subpackage implements Daq gRPC Server functionality for MCCS."""


__all__ = [
    "MccsDaqServer",
    "daq_pb2",
    "daq_pb2_grpc",
]

from .daq_grpc_server import MccsDaqServer
from .generated_code import daq_pb2, daq_pb2_grpc
