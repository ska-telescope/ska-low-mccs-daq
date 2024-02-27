# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""An implementation of a health model for a DAQ receiver."""
from __future__ import annotations

from typing import Callable

from ska_control_model import HealthState
from ska_low_mccs_common.health import HealthModel

__all__ = ["DaqHealthModel"]


class DaqHealthModel(HealthModel):
    """A health model for a Daq receiver."""
