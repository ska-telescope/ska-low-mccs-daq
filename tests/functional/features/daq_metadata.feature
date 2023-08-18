Feature: Test metadata
    Test that metadata stored  correctly

    Scenario: DAQ receiver data file is tagged to a configuration
        Given the Station is ready to be configured

        When the Station is configured to collect a data stream to a file

        Then the configuration will be tagged with a unique ID recorded to the EDA
        And the same unique ID will be stored to the file's metadata

