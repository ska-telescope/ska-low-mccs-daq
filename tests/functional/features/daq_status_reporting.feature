# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""This module contains the features and scenarios for the daq status reporting test."""

Feature: Daq Status Reporting
    As a developer,
    I want the MccsDaqReceiver to report its status,
    So that we know what state it is in.

@forked 
Scenario Outline: HealthState Transitions
    Given an MccsDaqReceiver
    And MccsDaqReceiver AdminMode is set to 'ONLINE'
    And communications are <initial_communication_state>
    And the fault bit is <initial_fault_state>
    And the MccsDaqReceiver HealthState is <initial_health_state>
    When <method> is called
    Then the MccsDaqReceiver HealthState is <final_health_state>

    Examples: tbl_healthstate
        |   initial_communication_state |   initial_fault_state |   initial_health_state    |   method                  |   final_health_state  |
        |   'disabled'                  |   'not_set'           |   'UNKNOWN'               |   'set_fault_bit'         |   'FAILED'            | 
        |   'disabled'                  |   'not_set'           |   'UNKNOWN'               |   'establish_comms'       |   'OK'                | 
        |   'established'               |   'not_set'           |   'OK'                    |   'unestablish_comms'     |   'UNKNOWN'           | 
        |   'established'               |   'not_set'           |   'OK'                    |   'set_fault_bit'         |   'FAILED'            | 
        |   'established'               |   'set'               |   'FAILED'                |   'unset_fault_bit'       |   'OK'                | 
        |   'disabled'                  |   'set'               |   'FAILED'                |   'unset_fault_bit'       |   'UNKNOWN'           | 
#       -----------------------------------------------------------------------------------------------------------------------------------------

@forked 
Scenario Outline: Consumers Starting Up
    Given an MccsDaqReceiver
    And MccsDaqReceiver AdminMode is set to 'ONLINE'
    And communications are 'established'
    And no consumers are running
    When <consumer> is started
    Then consumer_status attribute shows <consumer> as running

    Examples: tbl_consumers_up
        |   consumer                    |
        |   'RAW_DATA'                  |
        |   'CHANNEL_DATA'              |
        |   'BEAM_DATA'                 |
        |   'CONTINUOUS_CHANNEL_DATA'   |
        |   'INTEGRATED_BEAM_DATA'      |
        |   'STATION_BEAM_DATA'         |
        |   'CORRELATOR_DATA'           |
        |   'ANTENNA_BUFFER'            |          
#       ---------------------------------

@forked 
Scenario: Consumers Stopping
    Given an MccsDaqReceiver
    And MccsDaqReceiver AdminMode is set to 'ONLINE'
    And communications are 'established'
    And all consumers are running
    And consumer_status attribute shows all consumers are running
    When 'stop_daq' is called
    Then consumer_status attribute shows no consumers are running

@forked 
Scenario Outline: Report Status
    Given an MccsDaqReceiver
    And the MccsDaqReceiver has a particular <configuration>
    When 'daq_status' is called
    Then it returns the <expected_status>

    Examples: config_status
        |   configuration       |   expected_status     |
        |   'configuration_1'   |   'expected_status_1' |
        |   'configuration_2'   |   'expected_status_2' |
