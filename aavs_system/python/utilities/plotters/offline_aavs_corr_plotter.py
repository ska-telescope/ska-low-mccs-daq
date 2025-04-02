from __future__ import print_function
from __future__ import division
from future import standard_library
standard_library.install_aliases()
from builtins import range
from past.utils import old_div
import os
import urllib.request, urllib.parse, urllib.error
from math import sin, cos, radians

import numpy as np
from matplotlib import pyplot as plt

from pydaq.persisters import CorrelationFormatFileManager, FileDAQModes

# This is used to re-map ADC channels index to the RX
# number going into the TPM
antenna_preadu_mapping = {0: 1, 1: 2, 2: 3, 3: 4,
                          8: 5, 9: 6, 10: 7, 11: 8,
                          15: 9, 14: 10, 13: 11, 12: 12,
                          7: 13, 6: 14, 5: 15, 4: 16}

# AAVS Station center
aavs_station_latitude = -26.70408
aavs_station_longitude = 116.670231

# Some global params
antennas_per_tile = 16
nof_antennas = 256


def antenna_coordinates(save_to_file=False):
    """ Reads antenna base locations from the Google Drive sheet
    :param save_to_file: Save remapped location and baselines to file
    :return: Re-mapped antenna locations
    """

    # Antenna mapping placeholder
    antenna_mapping = []
    for i in range(antennas_per_tile):
        antenna_mapping.append([[]] * antennas_per_tile)

    # Read antenna location spreadsheet
    response = urllib.request.urlopen('https://docs.google.com/spreadsheets/d/e/2PACX-1vRIpaYPims9Qq9JEnZ3AfZtTaYJYWMsq2CWRgB-'
                              'KKFAQOZoEsV0NV2Gmz1fDfOJm7cjDAEBQWM4FgyP/pub?gid=220529610&single=true&output=csv')
    html = response.read().split('\n')

    # Two antennas are not in-place, however we still get an input into the TPM
    missing = 0

    # Read all antenna rows from spreadsheet response
    for i in range(1, nof_antennas + 1):
        items = html[i].split('\t')

        # Parse antenna row
        try:
            tpm, rx = int(items[7]) - 1, int(items[8]) - 1
            east, north, up = float(items[15].replace(',', '.')), float(items[17].replace(',', '.')), 0
        except:
            if missing == 0:
                tpm, rx = 0, 8
                east, north, up = 17.525, -1.123, 0
            else:
                tpm, rx = 10, 8
                east, north, up = 9.701, -14.627, 0
            missing += 1

        # Rotate the antenna and place in placeholder
        antenna_mapping[tpm][rx] = rotate_antenna(east, north, up)

    # Create lookup table (uses preadu mapping)
    antenna_positions = np.zeros((nof_antennas, 3))
    for i in range(nof_antennas):
        tile_number = old_div(i, antennas_per_tile)
        rx_number = antenna_preadu_mapping[i % antennas_per_tile] - 1
        antenna_positions[i] = (antenna_mapping[tile_number][rx_number])

    # Save to file if required
    if save_to_file:
        create_baseline_mapping(antenna_positions)

    return antenna_positions


def create_baseline_mapping(antenna_mapping):
    """ Helper scripts which creates two text files, one containing the baseline to antenna mapping
    and another containing the re-mapped antenna locations """
    with open("baseline_mapping.txt", 'w') as f:
        f.write("# baseline_index, antenna1_index, antenna2_index\r\n")
        index = 0
        for i in range(nof_antennas):
            for j in range(i, nof_antennas):
                f.write("{},{},{}\r\n".format(index, i, j))
                index += 1

    with open("antenna_positions.txt", 'w') as f:
        f.write("# antenna_index, x, y, z\n")
        for i, antenna in enumerate(antenna_mapping):
            f.write("{},{},{},{}\r\n".format(i, antenna[0], antenna[1], antenna[2]))


def rotate_antenna(x, y, z):
    """ Rotate antenna location
    :param x: Antenna location in X-axis
    :param y: Antenna location in Y-axis
    :param z: Antenna location in Z-axis
    :return Tuple containing rotated antenna locations"""

    # NOTE: I've placed this here for readability, if it is should be placed at start of script
    # Form rotation matrix (needs checking), enable to test
    # rot_matrix = np.matrix([[0, -sin(radians(aavs_station_latitude)), cos(radians(aavs_station_latitude))],
    #                        [1, 0, 0],
    #                        [0, cos(radians(aavs_station_latitude)), sin(radians(aavs_station_latitude))]])
    #
    # return np.array((np.matrix([x, y, z]) * rot_matrix))[0]

    return np.array([x, y, z])


def calculate_uvw(dec, ha=0):
    """ Compute the UV plane given a pointing
    :param dec: Required Declination
    :param ha: Required hour angle
    :return: The full U-V plane (entire grid populated) """

    # Form rotation matrix (needs checking)
    dec = radians(dec)
    ha = radians(ha)
    rot_matrix = np.matrix([[sin(ha), cos(ha), 0],
                            [-sin(dec) * cos(ha), sin(dec) * sin(ha), cos(dec)],
                            [cos(dec) * cos(ha), -cos(dec) * sin(ha), sin(dec)]])

    # Get antenna locations
    antenna_mapping = antenna_coordinates()

    # Generate UV plane
    uvw_plane = np.zeros((nof_antennas * nof_antennas, 3))
    for i in range(nof_antennas):
        for j in range(nof_antennas):
            uvw_plane[i * nof_antennas + j, :] = (rot_matrix * np.matrix(antenna_mapping[i] - antenna_mapping[j]).T).T

    return uvw_plane


def calculate_baseline_length(dec, ha=0):
    """ Compute the length of each baseline in UV plance
    :param dec: Required Declination
    :param ha: Required hour angle
    :return: Array containing length of each baseline """

    # Form rotation matrix (needs checking
    dec = radians(dec)
    ha = radians(ha)
    rot_matrix = np.matrix([[sin(ha), cos(ha), 0],
                            [-sin(dec) * cos(ha), sin(dec) * sin(ha), cos(dec)],
                            [cos(dec) * cos(ha), -cos(dec) * sin(ha), sin(dec)]])

    # Get antenna locations
    antenna_mapping = antenna_coordinates()

    # Calculate lenght of each baseline
    counter = 0
    baseline_length = np.zeros(nof_baselines)
    for i in range(nof_antennas):
        for j in range(i, nof_antennas):
            val = (rot_matrix * np.matrix(antenna_mapping[i] - antenna_mapping[j]).T)
            baseline_length[counter] = np.sqrt(val[0] * val[0] + val[1] * val[1])
            counter += 1

    return baseline_length


# Script entry point
if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv

    parser = OptionParser(usage="usage: %process_aavs_correlation.py [options]")
    parser.add_option("-s", "--samples", action="store", dest="nof_samples",
                      default=1, type='int',
                      help="Number of samples to process [default: 1, -1 for all]")
    parser.add_option("-d", "--data_directory", action="store", dest="directory", default=".",
                      help="Data directory [default: .]")
    parser.add_option("-c", "--channel", action="store", dest="channel", default=204, type='int',
                      help="Channel [default: 204]")
    parser.add_option("--stokes", action="store", dest="stokes", default="XX",
                      help="Which stokes to process from XX, XY, YX and YY [default: XX]")

    (conf, args) = parser.parse_args(argv[1:])

    # Check if directory exists
    if not (os.path.exists(conf.directory) and os.path.isdir(conf.directory)):
        print("Specified directory (%s) does not exist or is not a directory" % conf.directory)
        exit(0)

    # Check if Stokes parameter is valid
    if conf.stokes not in ['XX', 'XY', 'YX', 'YY']:
        print("Invalid Stokes define, using XX")
        conf.stokes = 0
    else:
        conf.stokes = ['XX', 'XY', 'YX', 'YY'].index(conf.stokes)

    # Locate file and read metadata
    corr_file_mgr = CorrelationFormatFileManager(root_path=conf.directory, daq_mode=FileDAQModes.Burst)
    print(corr_file_mgr.get_metadata(timestamp=None, tile_id=204))
    corr_file_mgr.read_data(n_samples=1, channel_id=conf.channel)
    nof_samples = conf.nof_samples if conf.nof_samples != -1 else corr_file_mgr.n_blocks
    nof_baselines = corr_file_mgr.n_baselines

    # Read all data
    # Data is in time/baseline/stokes/ order
    data, timestamps = corr_file_mgr.read_data(n_samples=nof_samples, channel_id=conf.channel)

    # Create matrix
    grid = np.zeros((nof_antennas, nof_antennas), dtype=np.complex64)

    # Re-arrange into a grid for easier manipulation
    # This only uses one integration from the file (skips the first one since it might be corrupted)
    counter = 0
    for i in range(nof_antennas):
        for j in range(i, nof_antennas):
            grid[i, j] = data[0, counter, conf.stokes, 0]
            counter += 1

    # --------- Plot correlation matrix
    f = plt.figure(figsize=(14, 10))
#    f.tight_layout()
    plt.imshow(10 * np.log10(np.abs(grid)), aspect='auto')
    plt.xlabel("Antenna")
    plt.ylabel("Antenna")
    plt.colorbar()
    plt.title("Correlation Matrix (XX, log)")
    plt.show()
    exit()

    # --------- Plot UV plane

    # Matrix plotter, calculate antenna positions
    uvw_plane = calculate_uvw(aavs_station_latitude, 0)

    # Plot UV plane
    f = plt.figure(figsize=(14, 10))
    f.tight_layout()
    plt.scatter(uvw_plane[:, 0], uvw_plane[:, 1], s=0.2)
    plt.title("UV plane")
    plt.xlabel("U")
    plt.ylabel("V")

    # --------- Plot amplitude vs UV distance

    # Plot amplitude vs UV distance
    f = plt.figure(figsize=(14, 10))
    f.tight_layout()
    plt.scatter(np.sqrt(uvw_plane[:, 0] ** 2 + uvw_plane[:, 1] ** 2), np.abs(grid.flatten()), s=0.2)
    plt.ylim([0, 12e8])
    plt.title("Ampltiude vs UV distance (no auto)")
    plt.xlabel("U-V distance")
    plt.ylabel("Amplitude")

    # --------- Plot fringes

    # Find 200 longests baseliness
    baseline_length = calculate_baseline_length(aavs_station_latitude, 0)
    longest_baselines = np.argsort(baseline_length)[::200]

    # Plot fringes
    f = plt.figure(figsize=(14, 10))
    for b in longest_baselines:
        plt.plot(data[:, b, 0])
    plt.ylabel("Arbitrary power")
    plt.xlabel("Time")

    # --------- Show plots
    plt.show()
