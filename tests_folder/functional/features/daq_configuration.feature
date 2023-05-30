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

@forked @xfail
Scenario Outline: Check that when a configuration is sent to the MccsDaqReceiver, the DAQ_receiver interface is configured correctly
    Given A MccsDaqReceiver is available
    When We pass a <configuration> to the MccsDaqReceiver
    Then The DAQ_receiver interface has a <configuration_expected>

    Examples: input variables
        |configuration     |configuration_expected  |
        #This first test checks all configuration parameters are written as expected and dont overwrite other values
        | {"nof_antennas": 16, "nof_channels": 512, "nof_beams": 1, "nof_polarisations": 2, "nof_tiles": 1, "nof_raw_samples": 32768, "raw_rms_threshold": -1, "nof_channel_samples": 1024, "nof_correlator_samples": 1835008, "nof_correlator_channels": 1, "continuous_period": 0, "nof_beam_samples": 42, "nof_beam_channels": 384, "nof_station_samples": 262144, "append_integrated": True, "sampling_time": 1.1325, "sampling_rate": (800e6 / 2.0) * (32.0 / 27.0) / 512.0, "oversampling_factor": 32.0 / 27.0, "receiver_ports": "4660", "receiver_interface": "eth0", "receiver_ip": "8080", "receiver_frame_size": 8500, "receiver_frames_per_block": 32, "receiver_nof_blocks": 256, "receiver_nof_threads": 1, "directory": ".", "logging": True, "write_to_disk": True, "station_config": None, "max_filesize": None, "acquisition_duration": -1, "acquisition_start_time": -1, "description": ""}                                                      |{"nof_antennas": 16, "nof_channels": 512, "nof_beams": 1, "nof_polarisations": 2, "nof_tiles": 1, "nof_raw_samples": 32768, "raw_rms_threshold": -1, "nof_channel_samples": 1024, "nof_correlator_samples": 1835008, "nof_correlator_channels": 1, "continuous_period": 0, "nof_beam_samples": 42, "nof_beam_channels": 384, "nof_station_samples": 262144, "append_integrated": True, "sampling_time": 1.1325, "sampling_rate": (800e6 / 2.0) * (32.0 / 27.0) / 512.0, "oversampling_factor": 32.0 / 27.0, "receiver_ports": "4660", "receiver_interface": "eth0", "receiver_ip": "8080", "receiver_frame_size": 8500, "receiver_frames_per_block": 32, "receiver_nof_blocks": 256, "receiver_nof_threads": 1, "directory": ".", "logging": True, "write_to_disk": True, "station_config": None, "max_filesize": None, "acquisition_duration": -1, "acquisition_start_time": -1, "description": ""} |
        #Here we check whether we can actually change values
        | {"nof_antennas": 8}|{"nof_antennas": 8}|
        | {"nof_beams": 2}|{"nof_antennas": 2}|
        #Here we check that input types are casted as desired.
        | {"nof_antennas": "16", "nof_channels": "512", "nof_beams": "1", "nof_polarisations": "2", "nof_tiles": "1", "nof_raw_samples": "32768", "raw_rms_threshold": "-1", "nof_channel_samples": "1024", "nof_correlator_samples": "1835008", "nof_correlator_channels": "1", "continuous_period": "0", "nof_beam_samples": "42", "nof_beam_channels": "384", "nof_station_samples": "262144", "append_integrated": "True", "sampling_time": "1.1325", "sampling_rate": "(800e6 / 2.0) * (32.0 / 27.0) / 512.0", "oversampling_factor": "32.0 / 27.0", "receiver_ports": 4660, "receiver_interface": eth0, "receiver_ip": 8080, "receiver_frame_size": "8500", "receiver_frames_per_block": "32", "receiver_nof_blocks": "256", "receiver_nof_threads": "1", "directory": ".", "logging": "True", "write_to_disk": "True", "station_config": "None", "max_filesize": "None", "acquisition_duration": "-1", "acquisition_start_time": "-1", "description": ""}    |{"nof_antennas": 16, "nof_channels": 512, "nof_beams": 1, "nof_polarisations": 2, "nof_tiles": 1, "nof_raw_samples": 32768, "raw_rms_threshold": -1, "nof_channel_samples": 1024, "nof_correlator_samples": 1835008, "nof_correlator_channels": 1, "continuous_period": 0, "nof_beam_samples": 42, "nof_beam_channels": 384, "nof_station_samples": 262144, "append_integrated": True, "sampling_time": 1.1325, "sampling_rate": (800e6 / 2.0) * (32.0 / 27.0) / 512.0, "oversampling_factor": 32.0 / 27.0, "receiver_ports": "4660", "receiver_interface": "eth0", "receiver_ip": "8080", "receiver_frame_size": 8500, "receiver_frames_per_block": 32, "receiver_nof_blocks": 256, "receiver_nof_threads": 1, "directory": ".", "logging": True, "write_to_disk": True, "station_config": None, "max_filesize": None, "acquisition_duration": -1, "acquisition_start_time": -1, "description": ""} |
        #Here are some edge cases
        | {"receiver_ports": "9000"}                  |{"receiver_ports": [9000]}                 |
        | {"receiver_ports": 9000}                    |{"receiver_ports": [9000]}                 |
        | {"receiver_ports": ["9999","8080", "2000"]} |{"receiver_ports": [9999,8080, 2000]}      |
        | {"receiver_ports": [9999,8080, 2000]}       |{"receiver_ports": [9999,8080, 2000]}      |

@forked @xfail
Scenario: Check that when we configure with no value for the receiver_ip it is dealt with appropriatly
    Given A MccsDaqReceiver is available
    When We pass parameter "receiver_ip" of value "None" to the MccsDaqReceiver
    Then The DAQ receiver interface has a valid "receiver_ip"



