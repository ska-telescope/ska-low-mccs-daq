from builtins import str
from builtins import range
import datetime
import json
import os

from pyaavs import station
import threading
import logging
import signal

# Stopping clauses
stop_event = threading.Event()

data_directory = '.'

aavs_station = None

# Signal handler
def signal_handler(signum, frame):
    global stop_event
    logging.info("Service interrupted")
    stop_event.set()


def assign_signal_handlers():
    """ Assign signal handlers """
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def create_station(config):
    """ Create and connect to station """
    global aavs_station

    # Create station
    station.load_configuration_file(config)
    aavs_station = station.Station(station.configuration)
    aavs_station.connect()

    # Try to connect until successful
    connected = False
    while not connected:
        # If service was interrupted, break
        if stop_event.is_set():
            break

        try:
            aavs_station.connect()
            if not all([tile.is_programmed() for tile in aavs_station.tiles]):
                raise Exception()
            connected = True
        except:
            assign_signal_handlers()
            logging.warning("Could not form station, re-attempting in 120 seconds")
            stop_event.wait(120)

    # If stop event is set, stop
    if stop_event.is_set():
        logging.info("Service interrupted, exiting")
        exit()

    # Set signal handlers
    assign_signal_handlers()

    logging.info("Station connected")


def monitor_rms(period):
    """ Insert new RMS values
    :param period: RMS update period"""

    # Repeat forver
    while not stop_event.is_set():

        # Get time to be used as a timestamp
        date = datetime.datetime.now()

        # JSON document for each tile
        values = []

        try:
            # Loop over tiles
            for t, tile in enumerate(aavs_station.tiles):

                # Create dictionary for storing tile metric and include timestamp
                tile_metrics = {'datetime': str(date),
                                'tile_id': t}

                # Get RMS values
                rms = tile.get_adc_rms()

                # For each antenna/pol pair, create a separate dict
                for antenna in range(16):
                    key = 'antenna_{}_pol_0'.format(antenna)
                    tile_metrics[key] = {'rms': rms[antenna * 2]}

                    key = 'antenna_{}_pol_1'.format(antenna)
                    tile_metrics[key] = {'rms': rms[antenna * 2 + 1]}

                # Add tile metrics to list
                values.append(tile_metrics)

        except Exception as e:
            logging.info("Station status changed, re-create station {}".format(e.message))
            create_station()
            continue

        logging.info("Writing metrics to disk")

        with open(os.path.join(data_directory, "{}.json".format(str(date))), 'w') as f:
            json.dump(values, f)

        # Sleep for period time
        stop_event.wait(period)


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    line_format = logging.Formatter("%(asctime)s - %(levelname)s - %(threadName)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(line_format)
    log.addHandler(ch)

    # Command line options
    p = OptionParser()
    p.set_usage('monitor_metrics.py [options] INPUT_FILE')
    p.set_description(__doc__)
    p.add_option("--config", action="store", dest="config",
                      default=None, help="Station configuration file to use")
    p.add_option("--period", action="store", dest="period", type="float",
                 default=0.2, help="Antenna RMS update period [default: 0.2]")
    p.add_option("--directory", action="store", dest="directory", default='.',
                 help="Directory to store readings [default: '.']")
    opts, args = p.parse_args(argv[1:])

    if not os.path.exists(opts.directory):
        logging.error("Invalid directory")
        exit(-1)

    # Check if a configuration file was defined
    if opts.config is None:
        log.error("A station configuration file is required, exiting")
        exit()

    data_directory = opts.directory

    # Create station
    create_station(opts.config)

    # Start monitoring
    monitor_rms(opts.period)
