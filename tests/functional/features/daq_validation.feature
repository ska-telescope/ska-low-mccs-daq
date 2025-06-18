@XTP-21188
Feature: DAQ validation As a developer I want to be able to validate data that is passing through the DAQ

    @XTP-21190
    Scenario: Validate raw data through the DAQ
        Given DAQ is available
        And DAQ state is ON
        And DAQ is configured to receive raw data
        And we have a known data package
        When I send the known data package through the DAQ
        Then the outgoing data should be the same as the known incoming data

    @XTP-21191
    Scenario: DAQ channalised valiation
        Given DAQ is available
        And DAQ state is ON state
        And DAQ is configured to receive channalised data
        And we have a known data package
        When I send the known data package through the DAQ
        Then the outgoing data should be the same as the known incoming data