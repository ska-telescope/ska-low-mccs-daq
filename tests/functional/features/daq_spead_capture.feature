# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the features and scenarios for the daq SPEAD capture test."""

Feature: Receiving SPEAD packets.
    As a MCCS developer who want to capture SPEAD data using daq
    when i send simulated SPEAD data
    DAQ reports it has received it.

    # Acceptance Criteria:
    #  - I will be able to configure the DAQ to listen on a specific port interface.
    #  - I will be able to start DAQ for capturing data.
    #  - I will have a simulated SPEAD data sending to a specific IP:PORT 
    #  - Daq will receive these packets. 

    # Issues
    #  - Finding it difficult to pass both deployment and development environments at the same time


  Background:
    Given interface eth0
    Given port 4660
    
  @xfail
  Scenario Outline: Sending SPEAD packets to be captured by DAQ
      Given an MccsDaqReceiver
      And the daq receiver is stopped
      And Daq is configured to listen on specified interface:port
      And The daq is started with <daq_modes_of_interest>
      When Simulated data from <no_of_tiles> of type <daq_modes_of_interest> is sent
      Then Daq reports that is has captured data <daq_modes_of_interest>
      And Daq writes to a file.

      Examples: modes of interest
          |   daq_modes_of_interest       |  no_of_tiles      |
          |   'INTEGRATED_CHANNEL_DATA'   |      16           |
          # |   'RAW_DATA'                  |      16           | # no simulator exists yet
  #       ---------------------------------

