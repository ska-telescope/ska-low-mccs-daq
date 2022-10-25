Feature: Daq Configuration
  As a developer,
  I want to configure MccsDaqReciever,
  So that we can start receiving data as desired from the TPM.

Scenario Outline: Check that when a configuration is sent to the MccsDaqReciever, the DAQ_reciever interface is configured correctly
    Given A MccsDaqReceiver is available
    When We pass a <configuration> to the MccsDaqReceiver
    Then The DAQ_reciever interface has that <configuration>

    Examples: input variables
        |configuration     |
        #TODO: the values passed in here are made up. Change
        | {"nof_antennas": 16, "nof_channels": 512, "nof_beams": 1, "nof_polarisations": 2, "nof_tiles": 1, "nof_raw_samples": 32768, "raw_rms_threshold": -1, "nof_channel_samples": 1024, "nof_correlator_samples": 1835008, "nof_correlator_channels": 1, "continuous_period": 0, "nof_beam_samples": 42, "nof_beam_channels": 384, "nof_station_samples": 262144, "append_integrated": True, "sampling_time": 1.1325, "sampling_rate": (800e6 / 2.0) * (32.0 / 27.0) / 512.0, "oversampling_factor": 32.0 / 27.0, "receiver_ports": "4660", "receiver_interface": "eth0", "receiver_ip": "8080", "receiver_frame_size": 8500, "receiver_frames_per_block": 32, "receiver_nof_blocks": 256, "receiver_nof_threads": 1, "directory": ".", "logging": True, "write_to_disk": True, "station_config": None, "max_filesize": None, "acquisition_duration": -1, "acquisition_start_time": -1, "description": ""}    |
        | {"nof_antennas": 17, "nof_channels": 513, "nof_beams": 2, "nof_polarisations": 1, "nof_tiles": 3, "nof_raw_samples": 32769, "raw_rms_threshold": -2, "nof_channel_samples": 1025, "nof_correlator_samples": 1835009, "nof_correlator_channels": 2, "continuous_period": 1, "nof_beam_samples": 41, "nof_beam_channels": 385, "nof_station_samples": 262144, "append_integrated": False, "sampling_time": 1.1326, "sampling_rate": 5000, "oversampling_factor": 32.0 / 27.0, "receiver_ports": "4660", "receiver_interface": "eth0", "receiver_ip": "8080", "receiver_frame_size": 8500, "receiver_frames_per_block": 32, "receiver_nof_blocks": 256, "receiver_nof_threads": 1, "directory": ".", "logging": True, "write_to_disk": False, "station_config": None, "max_filesize": None, "acquisition_duration": -1, "acquisition_start_time": -1, "description": "iuhdsaf i"}    |

Scenario Outline: Check that when we configure the MccsDaqReciever with values we expect to be overridden, they are!
    Given A MccsDaqReceiver is available
    When We pass an <configuration_param> of <value> <type_cast> to the MccsDaqReceiver
    Then The DAQ_reciever interface overrides the value when passed <configuration_param> of <value>

    Examples: input_key_value
    |configuration_param|value|type_cast|
    |receiver_ports     |9999 |string   |
    |receiver_ports|9999|int|
    |receiver_ip|None|string|
    |observation_metadata|None|string|