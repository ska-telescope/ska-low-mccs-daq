from __future__ import division
from builtins import range
from past.utils import old_div
import numpy as np
import threading
import datetime
import tempfile
import logging
import signal
import glob
import time
import os

try:
    from pydaq.persisters.channel import ChannelFormatFileManager
    from pydaq import daq_receiver as receiver
    from pydaq.persisters import FileDAQModes
    from pyaavs.station import Station
    from pymongo import MongoClient
except ImportError:
    pass

# Mongo db parameters
mongodb_database_name = "aavs_metrics"
mongodb_collection_name = "metrics"
mongodb_host = 'localhost'
mongodb_port = 27017

# Station configuration
tpms = ["tpm-{}".format(i) for i in range(1, 17)]
lmc_ip = "10.0.10.200"

# DAQ configuration
daq_config = {"nof_channel_samples": 1024,
              "receiver_interface": "eth3",
              "receiver_frame_size": 9000}

# Global parameters
data_directory = None
data_processed = 0
station = None

# Stopping clauses
stop_event = threading.Event()


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


def data_callback(data_type, filename, tile):
    """ Data callback to process data
    :param data_type: Type of data that was generated
    :param filename: Filename of data file where data was saved """

    global data_processed
    data_processed += 1


def generate_spectra(tile_id):
    """ Generate spectra for current tile
    :param tile_id: Tile ID """

    # Read data
    channel_file_mgr = ChannelFormatFileManager(root_path=data_directory, daq_mode=FileDAQModes.Burst)
    data, timestamps = channel_file_mgr.read_data(tile_id=tile_id,
                                                  antennas=list(range(16)),
                                                  polarizations=list(range(2)),
                                                  channels=list(range(512)),
                                                  n_samples=daq_config['nof_channel_samples'])

    # Convert to complex
    data = (data['real'] + 1j * data['imag']).astype(np.complex64)

    # Check if there was any clipping
    rfi = np.zeros((16, 2))
    for i in range(2):
        for j in range(16):
            rfi[j,i] = np.any(data[:, j, i, :].real == -128) or np.any(data[:, j, i, :].imag == -128)

    # Generate spectrum
    data = np.abs(data)**2
    data[np.where(data < 0.0000001)] = 0.00001
    data = 10 * np.log10(old_div(np.sum(data, axis=3), daq_config['nof_channel_samples']))

    # Return data
    return data, rfi


def create_station():
    """ Create and connect to station """
    global station

    # Create station
    station = Station(0)
    for t in tpms:
        station.add_tile(t)

    # Try to connect until successful
    connected = False
    while not connected:
        # If service was interrupted, break
        if stop_event.is_set():
            break

        try:
            station.connect(initialise=False, program=False)
            if not station.properly_formed_station or not all([tile.is_programmed() for tile in station.tiles]):
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


def monitor_rms(period, reset):
    """ Insert new RMS values
    :param period: RMS update period
    :param reset: Reset database"""

    global data_processed
    global data_directory

    # Connect to Mongo database
    client = MongoClient(mongodb_host,
                         mongodb_port,
                         username='aavs',
                         password='aavsaavs')

    db = client[mongodb_database_name]
    collection = db[mongodb_collection_name]

    if reset:
        collection.drop()

    # Create temporary directory for sotring data
    data_directory = tempfile.mkdtemp()

        # Start DAQ
    daq_config['nof_tiles'] = len(tpms)
    daq_config['directory'] = data_directory
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_channel_data_consumer(callback=data_callback)

    # Repeat forver
    while not stop_event.is_set():

        # Get time to be used as a timestamp
        date = datetime.datetime.utcnow()

        # JSON document for each tile
        values = []

        try:
            # Loop over tiles
            for t, tile in enumerate(station.tiles):
                # Create dictionary for storing tile metric and include timestamp
                tile_metrics = {'datetime': date, 'tile_id': t}

                # Get temperatures, current and voltage
                tile_metrics['fpga0_temp'] = tile.get_fpga0_temperature()
                tile_metrics['fpga1_temp'] = tile.get_fpga1_temperature()
                # tile_metrics['current']    = tile.get_current()
                tile_metrics['current']    = tile.get_voltage()

                # Get RMS values
                rms = tile.get_adc_rms()

                # For each antenna/pol pair, create a separate dict
                for antenna in range(16):
                    key = 'antenna_{}_pol_0'.format(antenna)
                    tile_metrics[key] = {'rms': rms[antenna*2]}

                    key = 'antenna_{}_pol_1'.format(antenna)
                    tile_metrics[key] = {'rms': rms[antenna*2 + 1] }

                # Add tile metrics to list
                values.append(tile_metrics)

            # send channelised data
            station.send_channelised_data(daq_config['nof_channel_samples'])

            # Wait for data to be processed
            while data_processed < len(tpms) and not stop_event.is_set():
                logging.info("Waiting for data")
                time.sleep(2)

            if stop_event.is_set():
                break
            data_processed = False

            # For each TPM, grab data and store
            for tile in range(len(tpms)):
                data, rfi = generate_spectra(t)
                for antenna in range(16):
                    key = 'antenna_{}_pol_0'.format(antenna)
                    values[tile][key]['bandpass'] = data[:, antenna, 0].tolist()
                    values[tile][key]['rfi'] = rfi[antenna, 0]
                    key = 'antenna_{}_pol_1'.format(antenna)
                    values[tile][key]['bandpass'] = data[:, antenna, 1].tolist()
                    values[tile][key]['rfi'] = rfi[antenna, 1]

        except Exception as e:
            logging.info("Station status changed, re-create station {}".format(e.message))
            create_station()
            continue

        # Inset into collection
        result = collection.insert_many(values)

        # Clear temporary directory contents
        filelist = glob.glob(os.path.join(data_directory, '*'))
        for f in filelist:
            os.remove(f)

        logging.info("Inserted new values")

        # Sleep for period time
        # stop_event.wait(30)


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

    p.add_option("--reset", action="store_true", dest="reset",
                 default=False, help="Reset database [default: False]")
    p.add_option("--period", action="store", dest="period", type="int",
                 default=60, help="Antenna RMS update period [default: 60]")
    opts, args = p.parse_args(argv[1:])

    # Create station
    create_station()

    # Start monitoring
    monitor_rms(opts.period, opts.reset)
