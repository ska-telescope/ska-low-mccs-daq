from __future__ import absolute_import
from pydaq import daq_receiver as receiver
from offline_correlator import *
from datetime import datetime, timedelta
from pyaavs import station
from time import sleep
from sys import stdout
import threading
import logging
import sched
import time
import sys
import os

# Global variables
daq_config = None
stop = False


def stop_observation():
    global stop
    stop = True


def run_observation(config, duration, channel):
    global stop

    # Load station configuration file
    station.load_configuration_file(config)
    
    # Create station
    station_config = station.configuration
    station_config['station']['program'] = opts.program
    station_config['station']['initialise'] = opts.program
    aavs_station = station.Station(station.configuration)
    aavs_station.connect()

    if not aavs_station.properly_formed_station:
        logging.error("Station not properly formed, exiting")
        exit()

    logging.info("Starting DAQ")

    # Start DAQ
    daq_config['nof_tiles'] = len(aavs_station.tiles)
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_correlator()

    # Wait for DAQ to initialise
    sleep(2)

    logging.info("Setting timer to stop observation in %ds" % duration)
    timer = threading.Timer(duration, stop_observation)
    timer.start()

    # Start sending data
    aavs_station.stop_data_transmission()
    aavs_station.send_channelised_data_continuous(channel, daq_config['nof_correlator_samples'])

    # Wait for observation to finish
    logging.info("Observation started")
    while not stop:
        time.sleep(5)
    stop = False

    # All done, clear everything
    logging.info("Observation ended")
    aavs_station.stop_data_transmission()

    try:
        receiver.stop_daq()
    except Exception as e:
        logging.error("Failed to stop DAQ cleanly: {}".format(e))


def run_observation_burst(config):
    global stop

    # Load station configuration file
    station.load_configuration_file(config)
    
    # Create station
    station_config = station.configuration
    station_config['station']['program'] = opts.program
    station_config['station']['initialise'] = opts.program
    aavs_station = station.Station(station.configuration)
    aavs_station.connect()

    if not aavs_station.properly_formed_station:
        logging.error("Station not properly formed, exiting")
        exit()

    logging.info("Starting DAQ")

    # Start DAQ
    daq_config['nof_tiles'] = len(aavs_station.tiles)
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_correlator()

    # Wait for DAQ to initialise
    sleep(2)

    logging.info("Setting timer to stop observation in %d" % (1.5 * 512 * 1.5))
    timer = threading.Timer(1.5 * 512 * 1.5, stop_observation)
    timer.start()

    # Start sending data
    aavs_station.stop_data_transmission()
    aavs_station.send_channelised_data(daq_config['nof_correlator_samples'])

    # Wait for observation to finish
    logging.info("Observation started")
    while not stop:
        time.sleep(5)
    stop = False

    # All done, clear everything
    logging.info("Observation ended")
    aavs_station.stop_data_transmission()

    try:
        receiver.stop_daq()
    except Exception as e:
        logging.error("Failed to stop DAQ cleanly: {}".format(e))


def run_observation_station(duration):
    global stop

    logging.info("Starting DAQ")

    # Start DAQ
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_station_beam_data_consumer()

    # Wait for DAQ to initialise
    sleep(2)

    logging.info("Setting timer to stop observation in %ds" % duration)
    timer = threading.Timer(duration, stop_observation)
    timer.start()

    # Wait for observation to finish
    logging.info("Observation started")
    while not stop:
        time.sleep(5)
    stop = False

    # All done, clear everything
    logging.info("Observation ended")

    try:
        receiver.stop_daq()
    except Exception as e:
        logging.error("Failed to stop DAQ cleanly: {}".format(e))


if __name__ == "__main__":

    # Command line options
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('source_observation.py [options] INPUT_FILE')
    p.set_description(__doc__)

    p.add_option("--config", action="store", dest="config",
                 default=None, help="Station configuration file to use")
    p.add_option("--lmc_ip", action="store", dest="lmc_ip",
                 default="10.0.10.200", help="IP [default: 10.0.10.200]")
    p.add_option("-P", "--program", action="store_true", dest="program",
                 default=False, help="Program and initialise station")
    p.add_option('-d', '--directory', dest='directory', action='store', default=".",
                 help="Data directory (default: '.')")
    p.add_option("-i", "--receiver_interface", action="store", dest="receiver_interface",
                 default="eth3", help="Receiver interface [default: eth3]")
    p.add_option("--samples", action="store", dest="nof_samples",
                 default=1835008, type="int", help="Number of samples to correlate. Default: 1835008")
    p.add_option("-s", "--starttime", action="store", dest="starttime",
                 default="now",
                 help="Time at which to start observation. For multi-channel observations, each channel will start"
                      "at the specified on subsequent days. Format: dd/mm/yyyy_hh:mm. Default: now")
    p.add_option("-l", "--duration", action="store", dest="duration",
                 type="int", default="120", help="Observation length [default: 120]")
    p.add_option("-c", "--channels", action="store", dest="channels",
                 default="204", help="Channels to be observed (in separate observations) [default: 204]")
    p.add_option("-S", "--station", action="store_true", dest="station",
                 default=False, help="Run in station beam mode [default: False]")

    opts, args = p.parse_args(sys.argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(format)
    log.addHandler(ch)

    # Check if a configuration file was defined
    if opts.config is None:
        log.error("A station configuration file is required, exiting")
        exit()

    # Check if directory exists
    if not (os.path.exists(opts.directory) and os.path.isdir(opts.directory)):
        logging.error("Specified directory (%s) does not exist or is not a directory" %opts.directory)
        exit(0)

    # Check if directory was specified
    if opts.starttime is None:
        logging.error("Start time must be specified")
        exit(0)

    # Check that start time is valid
    start_time = 0
    curr_time = 0
    if opts.starttime != "now":
        start_time = datetime.strptime(opts.starttime, "%d/%m/%Y_%H:%M")
        curr_time = datetime.fromtimestamp(int(time.time()))
        wait_seconds = (start_time - curr_time).total_seconds()
        if wait_seconds < 10:
            logging.error("Scheduled start time must be at least 10s in the future")
            exit()

    if opts.station:

        # Populate DAQ configuration
        daq_config = {"nof_beam_channels": 8,
                      "nof_station_samples": 262144 * 2,
                      "directory": opts.directory,
                      "receiver_interface": opts.receiver_interface,
                      "receiver_frame_size": 9000}

        if opts.starttime == "now":
            run_observation_station(opts.duration)
        else:
            logging.info("Setting scheduler to run at {}".format(start_time))
            s = sched.scheduler(time.time, time.sleep)
            s.enter((start_time - curr_time).total_seconds(), 0, run_observation_station, [opts.duration, ])
            s.run()

        exit()

    if opts.channels == "burst":

        # Populate DAQ configuration
        daq_config = {"nof_correlator_channels": 512,
                      "nof_correlator_samples": opts.nof_samples,
                      "directory": opts.directory,
                      "receiver_interface": opts.receiver_interface,
                      "receiver_frame_size": 9000}

        if opts.starttime == "now":
            run_observation_burst(opts.config)
        else:
            logging.info("Setting scheduler to run at {}".format(start_time))
            s = sched.scheduler(time.time, time.sleep)
            s.enter((start_time - curr_time).total_seconds(), 0, run_observation_burst, [opts.config, ])
            s.run()

        exit()

    # Extract channels
    channels = [int(channel) for channel in opts.channels.split(',')]

    # Populate DAQ configuration
    daq_config = {"nof_channels": 1,
                  "nof_correlator_samples": opts.nof_samples,
                  "directory": opts.directory,
                  "receiver_interface": opts.receiver_interface,
                  "receiver_frame_size": 9000}

    # If we're just observing one channel, schedule normally
    if len(channels) == 1:
        if opts.starttime == "now":
            run_observation(opts.config, opts.duration, channels[0])
        else:
            logging.info("Setting scheduler to run at {}".format(start_time))
            s = sched.scheduler(time.time, time.sleep)
            s.enter((start_time - curr_time).total_seconds(), 0, run_observation,
                    [opts.config, opts.duration, channels[0]])
            s.run()

    # Otherwise, schedule each channel one after the other
    else:
        # Loop over all channels
        for i, channel in enumerate(channels):

            # Create directory for channel
            directory = os.path.join(opts.directory, "channel_{}".format(channel))
            if not os.path.exists(directory):
                os.mkdir(directory)

            # Update daq config
            daq_config["directory"] = directory

            # Sleep for required period of time if required
            if opts.starttime != 'now':
                start_time = datetime.strptime(opts.starttime, "%d/%m/%Y_%H:%M") + timedelta(days=i)
                curr_time = datetime.fromtimestamp(int(time.time()))

                wait_seconds = (start_time - curr_time).total_seconds()
                if wait_seconds < 10:
                    logging.warning("Cannot schedule observation for channel {} in the past, skipping".format(channel))
                    continue

                logging.info("Setting scheduler to run at {} for channel {}".format(start_time, channel))
                s = sched.scheduler(time.time, time.sleep)
                s.enter((start_time - curr_time).total_seconds(), 0, run_observation,
                        [opts.config, opts.duration, channel])
                s.run()

            else:
                # Run observation
                logging.info("Starting observation for channel {}".format(channel))
                run_observation(opts.config, opts.duration, channel)
