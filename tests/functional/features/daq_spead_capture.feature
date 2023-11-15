# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the features and scenarios for the daq SPEAD capture test."""

Feature: Receiving SPEAD packets.
    As a MCCS developer i want to ensure DAQ is capable of capturing SPEAD data.

    # Acceptance Criteria:
    #  - I will be able to configure the DAQ to listen on a specific port interface.
    #  - I will be able to start DAQ for capturing data.
    #  - I can send simulated SPEAD data to a specific IP:PORT 
    #  - Daq will receive these packets. 

    # Notes:
    # - This test is skipped if not a true context

  Background:
    Given interface eth0
    
  Scenario Outline: Sending SPEAD packets to be captured by DAQ
      Given this test is running against station <station_name>.
      And the DAQ is available
      And the Tile is available
      And the Subrack is available
      And DAQ is ready to receive <daq_modes_of_interest> data type.
      And MccsTile is routed to daq
      When MccsTile sends <data_type> data type
      Then Daq receives data <daq_modes_of_interest>

      Examples: modes of interest
      |    daq_modes_of_interest    |  data_type  |  no_of_tiles    |    station_name    | 
      |   INTEGRATED_CHANNEL_DATA   |    channel  |      16         |     real-daq-1     |



