from __future__ import division
from builtins import input
from builtins import zip
from builtins import range
from past.utils import old_div
from builtins import object
from aavs_calibration.common import *

from datetime import datetime, timedelta
from astropy.coordinates import Angle
from multiprocessing import Pool
import matplotlib.pyplot as plt
from math import log10
from enum import Enum
import numpy as np
import logging
import signal
import pytz
import h5py
import time
import glob
import os
import re


# Define an enumeration for pointing
from pyaavs.point_station import Pointing


class OfflinePointing(object):
    """ Class representing pointing options """

    # Static values
    galaxy_ra = '17h45m40.04s'
    galaxy_dec = '-29d00m28.2s'

    virgo_ra = '12h30m49.42338s'
    virgo_dec = '12d23m28.0439s'

    hydra_ra = '9h18m05.73s'
    hydra_dec = '-12d05m43.9s'

    cent_ra = '13h25m27.62s'
    cent_dec = '-43d01m08.8s'

    class Source(Enum):
        """ List of pre-defined sources """
        SUN = 1
        GALAXY = 2
        VIRGO = 3
        HYDRA = 4
        CENTAURUS = 5

    def __init__(self, pointing_option, channel, station_id, nof_tiles):
        """ Constructor 
        :param pointing_option: The pointing option string passed in a argument. Can have several values:
            name: The name of a pre-defined source
            coord: A coordinate pair in astropy format. The coord pair should be prefixed with E (for equatorial) or C (for celestial)
                   and separated by a comma
            """

        # Convert to upper case
        pointing_option = pointing_option.upper()

        self._known_source, self._ra, self._dec, self._az, self._alt = None, None, None, None, None
        # Check if pointing option is known source
        if pointing_option in list(self.Source.__members__.keys()):
            self._known_source = pointing_option

        # Otherwise it should be coordinate pair
        elif pointing_option.startswith('E:'):
            self._ra, self._dec = self.extract_angles(pointing_option[2:])
        elif pointing_option.startswith('C:'):
            self._az, self._alt = self.extract_angles(pointing_option[2:])
        else:
            raise Exception(
                "Uknown poitingin option {}".format(pointing_option))

        # Create pointing object
        self._pointing = Pointing(station_id)
        self._channel = channel

    def get_pointing_coefficients(self, pointing_time):
        """ Get pointing coefficients for the required pointing time """

        if self._known_source is not None:
            if self._known_source == self.Source.SUN.name:
                self._pointing.point_to_sun(pointing_time)
            elif self._known_source == self.Source.GALAXY.name:
                self._pointing.point_array(right_ascension=self.galaxy_ra,
                                           declination=self.galaxy_dec,
                                           pointing_time=pointing_time,
                                           delta_time=0)
            elif self._known_source == self.Source.VIRGO.name:
                self._pointing.point_array(right_ascension=self.virgo_ra,
                                           declination=self.virgo_dec,
                                           pointing_time=pointing_time,
                                           delta_time=0)
            elif self._known_source == self.Source.HYDRA.name:
                self._pointing.point_array(right_ascension=self.hydra_ra,
                                           declination=self.hydra_dec,
                                           pointing_time=pointing_time,
                                           delta_time=0)
            elif self._known_source == self.Source.CENTAURUS.name:
                self._pointing.point_array(right_ascension=self.cent_ra,
                                           declination=self.cent_dec,
                                           pointing_time=pointing_time,
                                           delta_time=0)
        elif self._ra is not None:
            self._pointing.point_array(right_ascension=self._ra,
                                       declination=self._dec,
                                       pointing_time=pointing_time,
                                       delta_time=0)
        else:
            self._pointing.point_array_static(azimuth=self._az, altitude=self._alt)

        return self._pointing.get_pointing_coefficients(self._channel, 1)

    @staticmethod
    def extract_angles(option_string):
        """ Extract astropy angles from option string """
        angles = option_string.lower().split(',')
        if len(angles) != 2:
            raise Exception("Invalid pointing option, two angles are required")

        try:
            return Angle(angles[0]), Angle(angles[1])
        except:
            raise Exception("Could not convert angle options")


class ProcessArguments(object):
    directory = None
    timestamp = None
    total_tiles = None
    tiles = None
    nof_samples = None
    coeffs = None
    use_burst = False
    channel = None
    pointing_coeffs = None


# Global stopping variable (set by signal handler)
stop_operation = False


def _signal_handler(signum, frame):
    global stop_operation
    if not stop_operation:
        stop_operation = True
        logging.info("Received interrupt, stopping after current buffer")


def process_timestamp(args):
    """ Processes tiles in parallel
    @param args: Should be a tuple containing directory, timestamp, tile, nof_samples and coeffs"""

    # If pointing coeffs are all 0, do not process and return 0
    if np.all(args.pointing_coeffs == 0+0j):
        return args.timestamp, 0, 0

    # Load data
    data = np.zeros(
        (args.nof_samples, args.total_tiles * 16, 2), dtype=np.complex64)
    d = datetime.fromtimestamp(args.timestamp)
    date = d.strftime("%Y%m%d")
    seconds = '{:0=5d}'.format((d.hour * 60 + d.minute) * 60 + d.second)

    # Grab data from all tiles
    for tile in range(args.total_tiles):
        if tile not in args.tiles:
            continue

        # Use burst channel data 
        if args.use_burst:
            filename = r"channel_burst_{}_{}_{}_0.hdf5".format(tile, date, seconds)
            with h5py.File(os.path.join(args.directory, filename), 'r') as f:
                read_data = f['chan_']['data'][:args.nof_samples, args.channel * 32: (args.channel + 1) * 32]
                read_data = read_data.reshape((args.nof_samples, 16, 2))
                data[:, tile * 16: (tile+1) * 16, :] = read_data['real'] + read_data['imag'] * 1j

        # Use continuous channel data
        else:
            filename = r"channel_cont_{}_{}_{}_0.hdf5".format(tile, date, seconds)
            with h5py.File(os.path.join(args.directory, filename), 'r') as f:
                read_data = f['chan_']['data'][:args.nof_samples, :].reshape((args.nof_samples, 16, 2))
                data[:, tile * 16: (tile+1) * 16, :] = read_data['real'] + read_data['imag'] * 1j

    # Apply coefficients (if required) and sum current antennas
    if args.coeffs is None:
        x = np.sum(np.power(np.abs(np.sum(data[:, :, 0], axis=1)), 2))
        y = np.sum(np.power(np.abs(np.sum(data[:, :, 1], axis=1)), 2))
    else:
        if len(args.coeffs.shape) == 1:
            x = np.sum(np.power(np.abs(np.dot(data[:, :, 0], np.multiply(
                args.coeffs, args.pointing_coeffs[:, 0]))), 2))
            y = 0
        else:
            coeffs_x = np.multiply(args.coeffs[:, 0], args.pointing_coeffs[:, 0])
            coeffs_y = np.multiply(args.coeffs[:, 1], args.pointing_coeffs[:, 0])

            x = np.sum(np.power(np.abs(np.dot(data[:, :, 0], coeffs_x)), 2))
            y = np.sum(np.power(np.abs(np.dot(data[:, :, 1], coeffs_y)), 2))

    return args.timestamp, old_div(x, args.nof_samples), old_div(y, args.nof_samples)


def process_timestamp_multifreq(args):
    """ Processes tiles in parallel for multiple frequencies
    @param args: Should be a tuple containing directory, timestamp, tile, nof_samples and coeffs"""

    # If pointing coeffs are all 0, do not process and return 0
    if np.all(args.pointing_coeffs == 0+0j):
        return args.timestamp, 0, 0

    # Load data
    data = np.zeros((args.nof_samples, 512, args.total_tiles * 16, 2), dtype=np.complex64)
    d = datetime.fromtimestamp(args.timestamp)
    date = d.strftime("%Y%m%d")
    seconds = '{:0=5d}'.format((d.hour * 60 + d.minute) * 60 + d.second)

    # Grab data from all tiles
    for tile in range(args.total_tiles):
        if tile not in args.tiles:
            continue

        # Use burst channel data 
        filename = r"channel_burst_{}_{}_{}_0.hdf5".format(tile, date, seconds)
        with h5py.File(os.path.join(args.directory, filename), 'r') as f:
            read_data = f['chan_']['data'][:args.nof_samples, :]
            read_data = read_data.reshape((args.nof_samples, 512, 16, 2))
            data[:, :, tile * 16: (tile+1) * 16, :] = read_data['real'] + read_data['imag'] * 1j

    # Loop over all frequency channels
    x, y = np.zeros(512), np.zeros(512)
    for i in range(512):
        # Apply coefficients (if required) and sum current antennas
        coeffs_x = args.coeffs[:, 0, i]
        coeffs_y = args.coeffs[:, 1, i]

        x[i] = np.sum(np.power(np.abs(np.dot(data[:, i, :, 0], coeffs_x)), 2))
        y[i] = np.sum(np.power(np.abs(np.dot(data[:, i, :, 1], coeffs_y)), 2))

    return args.timestamp, old_div(x, args.nof_samples), old_div(y, args.nof_samples)


class OfflineStationBeamformer(object):
    def __init__(self, directory, station_id,  channel, nof_samples, ignore_amplitude=True,
                 calibrate=False, coefficient_file=None, tiles=None, nof_processes=1,
                 plot=False, pointing=None, skip_timesteps=0, use_burst=False, all_band=False):
        self._directory = directory
        self._station_id = station_id
        self._channel = channel
        self._nof_samples = nof_samples
        self._ignore_amplitude = ignore_amplitude
        self._nof_processes = nof_processes
        self._calibrate = calibrate
        self._use_burst = use_burst
        self._all_band = all_band
        self._coeffs_file = coefficient_file
        self._plot = plot

        # Grab list of files in provided directory
        logging.info("Listing files to process")
        found_tiles, timestamps, dirs = self._list_available_files(
            self._directory)
        self._nof_tiles = len(set(found_tiles))
        self._times = sorted(zip(timestamps, dirs))
        logging.info("Found data from {} tiles, {} timesteps".format(
            self._nof_tiles, len(self._times)))

        if skip_timesteps != 0:
            self_times = self_times[::skip_timesteps]

        # Process tiles
        if type(tiles) is str:
            try:
                self._tiles = [int(x) for x in tiles.split(',')]
                logging.info("Using tiles {}".format(self._tiles))
            except:
                logging.warning(
                    "Error processing {}, using all tiles".format(tiles))
        else:
            self._tiles = list(range(self._nof_tiles))

        # Check whether we have data from all times
        self._check_station()

        # Create pointing object
        self._pointing = None
        if pointing is not None:
            self._pointing = OfflinePointing(pointing, channel, station_id, self._nof_tiles)

    def process(self):
        """ Start calibrating and beamforming the data """
        global stop_operation

        # Station beam placeholder
        station_beam = []

        # Get calibration solutions and convert to complex coefficients
        coeffs = None

        if self._calibrate:
            if self._coeffs_file:
                try:
                    # Coefficients file should have the shape [pols, antennas]
                    coeffs = np.load(self._coeffs_file).T
                except Exception as e:
                    logging.error(
                        "Could not load coefficients from file {}. Exiting".format(self._coeffs_file))
                    exit()

                if len(coeffs.shape) == 1:
                    logging.warning(
                        "Coeffs file only contains coefficients for a single pol, assuming X, ignoring Y")

                if coeffs.shape[0] != len(self._tiles) * 16:
                    logging.error("Coeffs file does not contain enough coefficients ({} != {}). Exiting".format(
                        coeffs.shape[0], len(self._tiles) * 16))
            else:
                # Load from database. Amplitudes and phases are in antenna/pol/channel order. Phases are in degrees
                timestamp = self._times[0][0] 
                amplitude, phase = get_calibration_solution(self._station_id, timestamp - 3600*24*2)

                # Select channel and convert to radians
                if not self._all_band:
                    phase = np.deg2rad(phase[:, :, self._channel])
                    amplitude = amplitude[:, :, self._channel]

                # Remove spurious amplitudes
                amplitude[np.where(amplitude > 2)] = 1

                # Compute calibration coefficients
                if self._ignore_amplitude:
                    coeffs = np.cos(phase) + 1j * np.sin(phase)
                else:
                    coeffs = amplitude * (np.cos(phase) + 1j * np.sin(phase))

        # Start plot
        if self._plot:
            plt.ion()
            plt.figure(figsize=(10, 8))

        default_pointing_coeffs = np.ones((self._nof_tiles * 16, 1), dtype=np.complex)

        # Go through all time steps
        for i in range(0, len(self._times), self._nof_processes):
            t0 = time.time()

            # Create arguments for each process
            arguments = []
            for value in self._times[i: i + self._nof_processes]:
                timestamp, directory = value
                p_args = ProcessArguments()
                p_args.directory = directory
                p_args.timestamp = timestamp
                p_args.total_tiles = self._nof_tiles
                p_args.tiles = self._tiles
                p_args.nof_samples = self._nof_samples
                p_args.coeffs = coeffs
                p_args.channel = self._channel
                p_args.use_burst = self._use_burst
                p_args.all_band = self._all_band
                p_args.pointing_coeffs = default_pointing_coeffs

                if coeffs is not None and self._pointing is not None:

                    # Convert time to format which pointing object can understand
                    pointing_time = datetime.fromtimestamp(
                        timestamp) + timedelta(seconds=time.timezone)

                    p_args.pointing_coeffs = self._pointing.get_pointing_coefficients(pointing_time).copy()

                arguments.append(p_args)

            # Set interrupt signal handler
            signal.signal(signal.SIGINT, _signal_handler)

            # Remove any lock files
            for f in glob.glob(os.path.join(directory, "channel*.lock")):
                os.remove(f)

            # Point to appropriate function
            p = process_timestamp
            if self._all_band:
                p = process_timestamp_multifreq

            # Processes tiles in parallel
            if self._nof_processes > 1:
                pool = Pool(self._nof_processes)
                result = sorted(pool.map(p, arguments))
                pool.close()
            else:
                result = [p(arguments[0])]

            # If killed, exit
            if stop_operation:
                exit()

            # Add results to station beam
            try:
                for p in range(len(result)):
                    station_beam.append((result[p][0],
                                         result[p][1],
                                         result[p][2]))
            except:
                break

            # Update plot
            if self._plot:
                plt.clf()

                np.seterr(divide='ignore')
                x = 10 * np.log10(np.array([item[1] for item in station_beam]))
                y = 10 * np.log10(np.array([item[2] for item in station_beam]))
                np.seterr(divide='warn')
                x[np.isneginf(x)] = 0
                y[np.isneginf(y)] = 0

                plt.plot(x)
                if len(coeffs.shape) != 1:
                    plt.plot(y)
                plt.pause(0.001)

            logging.info("Processed {} of {}, in {:.2f}s".format(
                i + 1, len(self._times), time.time() - t0))

        # All done, return station beam
        return station_beam

    def _check_station(self):
        """ Check that we have data files for the correct number of tiles """
        station_info = get_station_information(self._station_id)

        if station_info.nof_antennas != self._nof_tiles * 16:
            logging.error(
                "Mismatch between number of antennas and number of tiles in data. Exiting")
            exit()

    def _list_available_files(self, directory):
        """ Lists the files available for this acquisition """

        tiles, times, dirs = [], [], []

        for f in os.listdir(directory):
            if os.path.isdir(os.path.join(directory, f)):
                x, y, z = self._list_available_files(
                    os.path.join(directory, f))
                tiles.extend(x)
                times.extend(y)
                dirs.extend(z)
                continue

            # Grab timestamp and tile number
            try:
                filename = os.path.basename(os.path.abspath(f))
                if self._use_burst:
                    pattern = r"channel_burst_(?P<tile>\d+)_(?P<timestamp>\d+_\d+)_\d+.hdf5"
                else:
                    pattern = r"channel_cont_(?P<tile>\d+)_(?P<timestamp>\d+_\d+)_\d+.hdf5"
                parts = re.match(pattern, filename).groupdict()
                time_parts = parts['timestamp'].split('_')
                sec = timedelta(seconds=int(time_parts[1]))
                date = datetime.strptime(time_parts[0], '%Y%m%d') + sec
                date = time.mktime(date.timetuple())

                # Add tile and time to appropriate lists if required
                if parts['tile'] not in tiles:
                    tiles.append(parts['tile'])

                if date not in times:
                    times.append(date)
                    dirs.append(directory)
            except:
                continue

        return tiles, times, dirs


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    p = OptionParser()
    p.set_usage('offline_station_beamformer.py [options]')
    p.set_description(__doc__)

    p.add_option('-d', '--directory', dest='directory', action='store', default=".",
                 help="Data directory (default: '.')")
    p.add_option('-S', '--station', dest='station', action='store', default="AAVS1",
                 help="Station identifier (default: AAVS1)")
    p.add_option('-s', '--samples', dest='samples', action='store', default=262144, type=int,
                 help="Number of samples (default: 131072)")
    p.add_option('-c', '--channel', dest='channel', action='store', default=204, type=int,
                 help="Channel to process (default: 204)")
    p.add_option('-p', '--processes', dest='processes', action='store', default=1, type=int,
                 help="Number of parallel processes to use (default: 1)")
    p.add_option('-o', '--output', dest='output', action='store', default="station_beam",
                 help="Output filename (default: station_beam)")
    p.add_option('--skip-amplitude', dest='skip_amplitude', action='store_true',
                 help="Skip application of amplitude from calibration solution (default: False)")
    p.add_option("--use-burst", dest="use_burst", action="store_true", default=False,
                help="Use burst data to generate beam (default: False)")
    p.add_option('--calibrate', dest='calibrate', action='store_true',
                 help="Calibrate data (default: False)")
    p.add_option('--coefficients', dest='coefficients', action='store', default=None,
                 help="File containing calibration coefficients to use (default: None)")
    p.add_option('--tiles', dest='tiles', action='store', default=None,
                 help="Select a subset of the tiles to use (default: all)")
    p.add_option('--live-plot', dest='plot', action='store_true', default=False,
                 help="Show live plot whilst beamforming (default: False)")
    p.add_option('--point-to', dest='point', action='store', default=None,
                 help="Apply pointing coefficients, pointing to specified source (SUN, GALAXY, VIRGO, HYDRA, CENTAURUS) (default: Do not point)")
    p.add_option('--raster-scan', dest='raster_scan', action='store_true', default=False,
                help="Generate a raster scan of the entire sky at each timestamp (default: False)")
    p.add_option('--frequency-scan', dest='frequency_scan', action='store_true', default=False,
                help="Generate a drift scan for all frequency channels (default: False)")
    opts, args = p.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(format)
    log.addHandler(ch)

    # Sanity check on provided coefficient file
    if opts.coefficients:
        if not os.path.exists(opts.coefficients) or not os.path.isfile(opts.coefficients):
            logging.error("Provided coefficients file {} is invalid")
            exit()

    if opts.raster_scan:
        logging.info("Performing raster scan, not showing live plot and enabling calibration")

        station_beams = []
        for altitude in range(0, 91, 1):
            for azimuth in range(0, 361, 1):
                logging.info("Generating beam for ({}, {})".format(altitude, azimuth))

                # Create offline station beamformer instance
                beamformer = OfflineStationBeamformer(opts.directory, opts.station, opts.channel, opts.samples,
                                                      ignore_amplitude=opts.skip_amplitude,
                                                      calibrate=True,
                                                      use_burst=opts.use_burst,
                                                      coefficient_file=opts.coefficients,
                                                      tiles=opts.tiles, nof_processes=opts.processes,
                                                      pointing="C:{}d,{}d".format(azimuth, altitude))
                station_beam = beamformer.process()
                station_beams.append(station_beam)

        # Save station beam and numpy files and exit
        np.save(opts.output, np.array(station_beams, dtype=np.float))
        exit()

    # Pointing options
    source = None
    if opts.point is not None:
        if not opts.calibrate:
            logging.warning(
                "Calibration must be applied for pointing. Not pointing")
            opts.point = None

    # If coefficients are provided then it is assumed that calibration will be performed
    if opts.coefficients:
        opts.calibrate = True

    # If performing frequency scan, disable plot and enable calibration
    if opts.frequency_scan:
        logging.info("Performing frequency scan, not showing live plot, enabling calibration and using burst data")
        opts.plot = False
        opts.calibrate = True
        opts.use_burst = True

    # Create offline station beamformer instance
    beamformer = OfflineStationBeamformer(opts.directory, opts.station, opts.channel, opts.samples,
                                        ignore_amplitude=opts.skip_amplitude, calibrate=opts.calibrate,
                                        coefficient_file=opts.coefficients, tiles=opts.tiles,
                                        use_burst=opts.use_burst,
                                        nof_processes=opts.processes, plot=opts.plot,
                                        all_band=opts.frequency_scan,
                                        pointing=opts.point)
    station_beam = beamformer.process()

    # Save station beam and numpy files and CSV files
    np.save(opts.output, np.array(station_beam, dtype=np.float))

    if opts.plot:
        _ = input("Processing finished. Press Enter to exit")
