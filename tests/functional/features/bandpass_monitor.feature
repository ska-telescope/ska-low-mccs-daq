@XTP-34301
Feature: Test bandpass monitor
    Test that antenna bandpasses can be received and plots of them can be produced

    Background:
        Given interface eth0

    @XTP-34297
    Scenario: Not listening for integrated channel data
        Given the DAQ is available
        And no consumers are running
        And the bandpass monitor is not running
        And the DAQ is configured
        When the DAQ is commanded to start monitoring for bandpasses with `auto_handle_daq` set to `False`
        Then the DAQ rejects the command and reports that the integrated channel data consumer must be running to monitor for bandpasses

    XTP-34299
    Scenario: Stop bandpass monitor
        Given the DAQ is available
        And no consumers are running
        And the DAQ is configured
        And the DAQ is started with the integrated channel data consumer
        And the bandpass monitor is running
        When the DAQ is commanded to stop monitoring bandpasses
        Then the DAQ reports that it is stopping monitoring bandpasses

    @XTP-34300
    Scenario: Receive bandpass data
        Given the DAQ is available
        And no consumers are running
        And the Tile is available
        And the Subrack is available
        And the DAQ is configured
        And the DAQ is started with the integrated channel data consumer
        And the bandpass monitor is running
        And the Tile is routed to the DAQ
        When the Tile is commanded to send integrated channel data
        Then the DAQ reports that it has received integrated channel data
        And the DAQ saves bandpass data to its relevant attributes

