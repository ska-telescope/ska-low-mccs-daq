Feature: DAQ PCAP bandpass test
    As a developer, I want to test the DAQ bandpass functionality using PCAP files
    So that we can validate the bandpass with a tone in the right channel for the right antennas

    Scenario Outline: Validate bandpass test using PCAP replay
        Given the bandpass test PCAP file is available
        And this test is running against station <expected_station>
        And the DAQ is available
        And the DAQ is configured to receive data
        And the DAQ is in the ON state
        And the DAQ is in health state OK
        And the DAQ is in adminMode ONLINE
        And the DAQ start command has been called
        And we are subscribed to changes to the received results attribute
        When we replay the bandpass PCAP file to the DAQ
        Then the DAQ should receive the bandpass data

        Examples:
            | expected_station    |
            | ci-1-bandpass       |
            | real-daq-1-bandpass |
