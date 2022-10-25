

Feature: Daq Configuration
  As a developer,
  I want to configure MccsDaqReciever,
  So that we can start receiving data from the TPM.


Scenario Outline: Check that when a configuration is sent to the MccsDaqReciever it is configured correctly
    Given A MccsDaqReceiver is available
    When We pass a <configuration> to the MccsDaqReceiver
    Then The DAQ_reciever interface has that <configuration>



    Examples: input variables
        |configuration     |
        | {"nof_antennas": 16, "nof_channels": 512, "nof_beams": 1, "nof_polarisations": 2, "nof_tiles": 1, "nof_raw_samples": 32768, "raw_rms_threshold": -1, "nof_channel_samples": 1024, "nof_correlator_samples": 1835008, "nof_correlator_channels": 1, "continuous_period": 0, "nof_beam_samples": 42, "nof_beam_channels": 384, "nof_station_samples": 262144, "append_integrated": True, "sampling_time": 1.1325, "sampling_rate": (800e6 / 2.0) * (32.0 / 27.0) / 512.0, "oversampling_factor": 32.0 / 27.0, "receiver_ports": "4660", "receiver_interface": "eth0", "receiver_ip": "", "receiver_frame_size": 8500, "receiver_frames_per_block": 32, "receiver_nof_blocks": 256, "receiver_nof_threads": 1, "directory": ".", "logging": True, "write_to_disk": True, "station_config": None, "max_filesize": None, "acquisition_duration": -1, "acquisition_start_time": -1, "description": ""}    |


