Feature: Testing Metadata Recording in DAQ Output
    Test that metadata stored correctly

    Scenario: Metadata is recorded as expected in the output file
    Given the DAQ system is running
    And DAQ has been configured with the following metadata:
      | Metadata Key    | Metadata Value              |
      | Observation ID  | OBS-123456                  |
    And DAQ is collecting data
    When data is saved to an output file
    Then the output file should contain the recorded metadata:
      | Metadata Key    | Metadata Value              |
      | Observation ID  | OBS-123456                  |
      
    Scenario: Missing metadata in the observation
    Given the DAQ system is running
    And DAQ has not been configured with additional metadata
    And DAQ is collecting data
    When data is saved to an output file
    Then the output file should contain default values for missing metadata:
      | Metadata Key    | Metadata Value              |
      | Observation ID  | Default_Observation_ID      |

    Scenario: Daq receiver configuration is passed through subarray and station
    Given a Subarray is ready to be configured
    And a Station is ready to be configured
    And DAQ is ready to be configured
    When the Subarray is configured
    Then the Subarray configuration will contain a unique ID
    And the Station configuration will contain the same unique ID
    And the DAQ configuration will contain the same unique ID

    Scenario: Daq recorded data contains configuration 
    Given the Subarray is configured
    And the Subarray configuration contains a unique ID
    And the Station configuration contains the same unique ID
    And the DAQ configuration contains the same unique ID
    When DAQ records data to file
    Then the same unique ID will be stored to the file's metadata