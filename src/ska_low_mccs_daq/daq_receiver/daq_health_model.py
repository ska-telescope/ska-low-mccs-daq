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

    def __init__(
        self: DaqHealthModel,
        component_state_callback: Callable[..., None],
    ) -> None:
        """
        Initialise a new instance.

        :param component_state_callback: callback to be called whenever
            there is a change to this component's state, including the health
            model's evaluated health state.
        """
        super().__init__(component_state_callback)

    def evaluate_health(
        self: DaqHealthModel,
    ) -> HealthState:
        """
        Compute overall health of the Daq receiver.

        :return: an overall health of the Daq receiver.
        """
        daq_health = super().evaluate_health()

        for health in [
            HealthState.FAILED,
            HealthState.UNKNOWN,
            HealthState.DEGRADED,
        ]:
            if daq_health == health:
                return health

        return HealthState.OK
