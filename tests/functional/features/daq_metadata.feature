Feature: Testing Metadata Recording in DAQ Output
    Test that metadata stored correctly

    Scenario: Metadata is recorded as expected in the output file
    Given the DAQ system is running and collecting data
    When an observation is recorded with the following metadata:
      | Metadata Key    | Metadata Value              |
      | Observation ID  | OBS-123456                  |
    And the observation is saved to the output file
    Then the output file should contain the recorded metadata:
      | Metadata Key    | Metadata Value              |
      | Observation ID  | OBS-123456                  |
      
  Scenario: Missing metadata in the observation
    Given the DAQ system is running and collecting data
    When an observation is recorded without certain metadata
    And the observation is saved to the output file
    Then the output file should contain default values for missing metadata:
      | Metadata Key    | Metadata Value              |
      | Observation ID  | Default_Observation_ID      |
      
    