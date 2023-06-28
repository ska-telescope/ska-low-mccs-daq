# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains pytest-specific test harness for MCCS unit tests."""
from typing import Iterator

import pytest
from ska_low_mccs_daq_interface.server import server_context

from ska_low_mccs_daq.daq_handler import DaqHandler


@pytest.fixture(name="daq_address")
def daq_address_fixture() -> Iterator[str]:
    """
    Yield the address of a running DAQ server.

    :yield: the DAQ server address.
    """
    with server_context(DaqHandler()) as port:
        yield f"localhost:{port}"
