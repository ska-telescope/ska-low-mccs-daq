# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the features and scenarios for the daq configuration test."""

Feature: Daq Configuration
  As a developer,
  I want to configure MccsDaqReceiver,
  So that we can start receiving data as desired from the TPM.

@forked
Scenario: Check that DAQ can be configured
    Given A MccsDaqReceiver is available
    When We pass a configuration to the MccsDaqReceiver
    Then The DAQ_receiver interface has the expected configuration

@forked
Scenario: Check that when we configure with no value for the receiver_ip it is dealt with appropriatly
    Given A MccsDaqReceiver is available
    When We pass parameter "receiver_ip" of value "None" to the MccsDaqReceiver
    Then The DAQ receiver interface has a valid "receiver_ip"
