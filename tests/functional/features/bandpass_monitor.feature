Feature: Test bandpass monitor
    Test that antenna bandpasses can be received and plots of them can be produced

    Scenario: Not listening for integrated channel data
        Given the DAQ is available
        And the DAQ has been commanded to start monitoring for bandpasses
        Then the DAQ reports that it needs to be able to receive integrated channel data to monitor for bandpasses

    Scenario: Stop bandpass monitor
        Given the DAQ is available
        And the DAQ is ready to receive integrated channel data
        And the DAQ has been commanded to start monitoring for bandpasses
        When the DAQ is commanded to stop monitoring bandpasses
        Then the DAQ reports that it is stopping monitoring bandpasses

    Scenario: Receive bandpass data
        Given the DAQ is available
        And the Tile is available
        And the Tile is routed to the DAQ
        And the DAQ is ready to receive integrated channel data
        And the DAQ has been commanded to start monitoring for bandpasses
        When the Tile is commanded to send integrated channel data
        Then the DAQ reports that it has received integrated channel data
        And the DAQ saves bandpass data to the EDA
        And a bandpass plot is produced