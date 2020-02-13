#! /usr/bin/env python

from __future__ import division
from future import standard_library
standard_library.install_aliases()

import urllib.request, urllib.parse, urllib.error
from datetime import datetime
from glob import glob
import numpy as np
import logging
import time
import os

from pyaavs import station

antenna_preadu_mapping = {0: 1, 1: 2, 2: 3, 3: 4,
                          8: 5, 9: 6, 10: 7, 11: 8,
                          15: 9, 14: 10, 13: 11, 12: 12,
                          7: 13, 6: 14, 5: 15, 4: 16}

nof_antennas_per_tile = 16
nof_antennas = 256
nof_stokes = 4


def antenna_coordinates():
    """ Reads antenna base locations from the Google Drive sheet
    :param save_to_file: Save remapped location and baselines to file
    :return: Re-mapped antenna locations
    """

    # Antenna mapping placeholder
    antenna_mapping = []
    for i in range(nof_antennas_per_tile):
        antenna_mapping.append([[]] * nof_antennas_per_tile)

    # Read antenna location spreadsheet
    response = urllib.request.urlopen('https://docs.google.com/spreadsheets/d/e/2PACX-1vQTo60lZmrvBfT0gpa4BwyaB_QkPplqfHga'
                              '7RCsLDR9J_lv15BQTqb3loBHFhMp6U0X_FIwyByfFCwG/pub?gid=220529610&single=true&output=tsv')
    html = response.read().split('\n')

    # Two antennas are not in-place, however we still get an input into the TPM
    missing = 0

    # Read all antenna rows from spreadsheet response
    for i in range(1, nof_antennas + 1):
        items = html[i].split('\t')

        # Parse antenna row
        try:
            base, tpm, rx = int(items[1]), int(items[7]) - 1, int(items[8]) - 1
            east, north, up = float(items[15].replace(',', '.')), float(items[17].replace(',', '.')), 0
        except:
            if missing == 0:
                base, tpm, rx = 3, 0, 8
                east, north, up = 17.525, -1.123, 0
            else:
                base, tpm, rx = 41, 10, 8
                east, north, up = 9.701, -14.627, 0
            missing += 1

        # Rotate the antenna and place in placeholder
        antenna_mapping[tpm][rx] = (base, east, north)

    # Create lookup table (uses preadu mapping)
    antenna_positions = np.zeros((nof_antennas, 3))
    for i in range(nof_antennas):
        tile_number = i // nof_antennas_per_tile
        rx_number = antenna_preadu_mapping[i % nof_antennas_per_tile] - 1
        antenna_positions[i] = (antenna_mapping[tile_number][rx_number])

    return antenna_positions


def read_coefficients(filepath):
    """ Read coefficients from filepath """

    # Read file content. First lines contains header, so can be ignored
    with open(filepath, 'r') as f:
        content = f.readlines()[1:]

    # Find the entry which is closest in time to the current UCT time
    # We are only interested in hour, minute and second
    utc_time = datetime.utcnow()
    current_time = datetime(1900, 1, 1, utc_time.hour, utc_time.minute, utc_time.second)

    # Get all times from file
    delta_times = []
    for i, line in enumerate(content):
        entries = [value for value in line.split(' ') if value.strip() != '']
        delta_times.append(abs(datetime.strptime(entries[1], '%H:%M:%S') - current_time).total_seconds())

    # Get index of calibration coefficient closes to current time
    index = delta_times.index(min(delta_times))

    # Each line contains an index, the time and the coefficient for each antenna
    entries = [value for value in content[index].split(' ') if value.strip() != '']

    # Rearrange indices
    coords = antenna_coordinates()
    entries = [float(x) for x in entries[2:]]
    coeffs = []
    for antenna in range(256):
        coeffs.append(entries[int(coords[antenna][0]) - 1])

    # Return values
    return coeffs


def load_coefficients(directory, file_prefix, nof_channels, channel, skip_amplitude=False):
    # Load coefficient files for given file prefix
    xx_amp, xx_phase, yy_amp, yy_phase = None, None, None, None
    for f in glob("{}*.txt".format(os.path.join(directory, file_prefix))):

        # If skipping amplitudes, ignore amplitude coefficient file
        if skip_amplitude and "_amp" in f:
            continue

        if 'XX' in f and 'amp' in f:
            xx_amp = read_coefficients(f)
        elif 'XX' in f and 'pha' in f:
            xx_phase = read_coefficients(f)
        elif 'YY' in f and 'amp' in f:
            yy_amp = read_coefficients(f)
        elif 'YY' in f and 'pha' in f:
            yy_phase = read_coefficients(f)
        else:
            logging.warning("{} has an invalid filename format".format(f))

    # All files loaded, check that we have all required coefficients
    if skip_amplitude:
        if not all([xx_phase, yy_phase]):
            logging.critical("Missing files in specified directory ({})".format(directory))
            exit()
    else:
        if not all([xx_amp, xx_phase, yy_amp, yy_phase]):
            logging.critical("Missing files in specified directory ({})".format(directory))
            exit()

    # Create default calibration coefficient array
    # Index 0 is XX, 3 is YY. Indices 2 and 3 are the cross-pols, which should be initialised to 0
    coefficients = np.ones((nof_antennas, nof_channels, nof_stokes), dtype=np.complex64)
    coefficients[:, :, 1:3] = 0 + 0j

    # Apply XX coefficients
    xx_amp, xx_phase = np.array(xx_amp) if not skip_amplitude else np.ones(nof_antennas), np.deg2rad(np.array(xx_phase))
    coefficients[:, channel, 0] = (xx_amp * np.cos(xx_phase) + xx_amp * np.sin(xx_phase) * 1j)
    coefficients[:, channel + 1, 0] = (xx_amp * np.cos(xx_phase) - xx_amp * np.sin(xx_phase) * 1j)

    # Apply YY coefficients
    yy_amp, yy_phase = np.array(yy_amp) if not skip_amplitude else np.ones(nof_antennas), np.deg2rad(np.array(yy_phase))
    coefficients[:, channel, 3] = (yy_amp * np.cos(yy_phase) + yy_amp * np.sin(yy_phase) * 1j)[:nof_antennas]
    coefficients[:, channel + 1, 3] = (yy_amp * np.cos(yy_phase) - yy_amp * np.sin(yy_phase) * 1j)[:nof_antennas]

    logging.info("Loaded calibration coefficients from file")

    return coefficients


def download_coefficients(config, coefficients):
    """ Download coefficients to station """

    # Connect to tiles in station
    station.load_configuration_file(config)
    aavs_station = station.Station(station.configuration)
    aavs_station.connect()

    # Download coefficients
    t0 = time.time()
    for i, tile in enumerate(aavs_station.tiles):
        # Get coefficients range for current tile
        for antenna in range(nof_antennas_per_tile):
            tile.load_calibration_coefficients(antenna,
                                               coefficients[i * nof_antennas_per_tile + antenna, :, :].tolist())
    t1 = time.time()

    logging.info("Downloaded coefficients to tiles in {0:.2}s".format(t1 - t0))

    # Done downloading coefficient, switch calibration bank
    aavs_station.switch_calibration_banks(2048)  # About 0.5 seconds
    logging.info("Switched calibration banks")


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %calibrate_station [options]")
    parser.add_option("--config", action="store", dest="config",
                      default=None, help="Station configuration file to use")
    parser.add_option("-d", "--directory", action="store", dest="directory",
                      default=".", help="Directory where calibration coefficients are stored [default: .]")
    parser.add_option("-c", action="store", dest="nof_channels", type='int',
                      default=8, help="Number of beamformed channels [default: 8]")
    parser.add_option("--prefix", action="store", dest="prefix",
                      default="gainsextract", help="File prefix [default: gainsextract]")
    parser.add_option("--channel", action="store", dest="channel",
                      type="int", default="4", help="Beamformed channel to calibrate [default: 4]")
    parser.add_option("--period", action="store", dest="period",
                      type="int", default="0", help="Duty cycle in s for updating coefficients [default: 0 (once)]")
    parser.add_option("--skip-amp", action="store_true", dest="skip_amp", default=False,
                      help="Ignore amplitude coefficient (set to 1) [default: False]")
    (opts, args) = parser.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    line_format = logging.Formatter("%(asctime)s - %(levelname)s - %(threadName)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(line_format)
    log.addHandler(ch)

    # Check if a configuration file was defined
    if opts.config is None:
        log.error("A station configuration file is required, exiting")
        exit()

    # Load and download coefficients
    nof_channels = opts.nof_channels
    download_coefficients(opts.config, load_coefficients(opts.directory, opts.prefix,
                                                         opts.nof_channels, opts.channel, opts.skip_amp))

    # If period is defined, loop forever with given period
    if opts.period != 0:
        while True:
            logging.info("Waiting for {} seconds".format(opts.period))
            time.sleep(opts.period)
            download_coefficients(opts.config, load_coefficients(opts.directory, opts.prefix,
                                                                 opts.nof_channels, opts.channel, opts.skip_amp))
