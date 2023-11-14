Feature: Test bandpass monitor
    Test that antenna bandpasses can be received and plots of them can be produced

    Scenario: Not listening for integrated channel data
        Given the DAQ is available
        And no consumers are running
        And the DAQ is properly configured for bandpass monitoring
        When the DAQ is commanded to start monitoring for bandpasses with `auto_handle_daq` set to `False`
        Then the DAQ rejects the command and reports that the integrated channel data consumer must be running to monitor for bandpasses

    Scenario: Stop bandpass monitor
        Given the DAQ is available
        And the integrated channel data consumer is running
        And the bandpass monitor is running
        When the DAQ is commanded to stop monitoring bandpasses
        Then the DAQ reports that it is stopping monitoring bandpasses

    Scenario: Receive bandpass data
        Given the DAQ is available
        And the Tile is available
        And the Tile is routed to the DAQ
        And the DAQ is properly configured for bandpass monitoring
        And the integrated channel data consumer is running
        And the Tile is commanded to send integrated channel data
        When the DAQ has been commanded to start monitoring for bandpasses
        Then the DAQ reports that it has received integrated channel data
        And the DAQ saves bandpass data to its relevant attributes