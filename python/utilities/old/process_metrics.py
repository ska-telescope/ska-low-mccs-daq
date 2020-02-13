from matplotlib import pyplot as plt
import matplotlib.dates as md
import numpy as np
import logging
import os

try:
    import pymongo
except ImportError:
    pass

# Mongo db parameters
mongodb_database_name = "aavs_metrics"
mongodb_collection_name = "metrics"
mongodb_host = 'localhost'
mongodb_port = 27017

output_directory = "/home/aavs/Dropbox/AAVS_DATA/output"


def process_metrics():
    """ Plot metrics from database """

    # Create output directory
    if not os.path.exists(output_directory):
        os.mkdir(output_directory)

    # Connect to Mongo database
    client = pymongo.MongoClient(mongodb_host,
                                 mongodb_port,
                                 username='aavs',
                                 password='aavsaavs')

    db = client[mongodb_database_name]
    metrics = db[mongodb_collection_name]

    # Get tile IDs and sort them
    tiles = [0]  # sorted(metrics.find().distinct("tile_id"))

    # We only need to process timestamps once
    entries = metrics.find({"tile_id": 0})
    timestamps = [md.date2num(value['datetime']) for value in entries]

    # We'll save temperature and voltage across tiles
    fpga0_temp = np.zeros((len(tiles), entries.count()))
    fpga1_temp = np.zeros((len(tiles), entries.count()))
    current = np.zeros((len(tiles), entries.count()))

    # Loop over tiles
    for tile in tiles:

        # Get entries for current tile
        entries = metrics.find({"tile_id": tile})

        # Create empty arrays
        antenna_rms = np.zeros((entries.count(), 16, 2), dtype=float)
        antenna_bandpass = np.zeros((entries.count(), 16, 2, 512), dtype=float)
        antenna_rfi = np.zeros((entries.count(), 16, 2), dtype=float)

        # Process all entries
        for i, entry in enumerate(entries):
            fpga0_temp[tile, i] = entry['fpga0_temp']
            fpga1_temp[tile, i] = entry['fpga1_temp']
            current[tile, i] = entry['current']

            # Get RMS and bandpasses for all antennas
            for antenna in range(16):
                for pol in range(2):
                    key = "antenna_{}_pol_{}".format(antenna, pol)
                    antenna_rms[i, antenna, pol] = entry[key]['rms']
                    antenna_bandpass[i, antenna, pol, :] = entry[key]['bandpass']

        # All entries for tile processed, generate plots
        for pol in range(2):

            # ================================== PLOT RMS ======================================
            f = plt.figure(figsize=(16, 12))
            plt.subplot(111)
            ax = plt.gca()
            xfmt = md.DateFormatter('%-j - %H:%M:%S')
            ax.xaxis.set_major_formatter(xfmt)

            for antenna in range(16):
                plt.plot(timestamps, antenna_rms[:, antenna, pol], label='Antenna {}'.format(antenna))

            # Finalise plot and save
            f.autofmt_xdate()
            f.tight_layout(rect=[0, 0.03, 1, 0.95])
            plt.ylim((10, 35))
            plt.title('Tile {} Pol {} - RMS'.format(tile, pol))
            plt.xlabel('Time')
            plt.ylabel('RMS')
            plt.legend()
            plt.savefig(os.path.join(output_directory, "rms_tile_{}_pol_{}".format(tile, pol)), dpi=300)
            plt.close(f)

            # ================================== PLOT RFI ======================================
            f = plt.figure(figsize=(16, 12))
            plt.subplot(111)
            ax = plt.gca()
            xfmt = md.DateFormatter('%-j - %H:%M:%S')
            ax.xaxis.set_major_formatter(xfmt)

            for antenna in range(16):
                plt.plot(timestamps, antenna_rfi[:, antenna, pol], label='Antenna {}'.format(antenna))

            # Finalise plot and save
            f.autofmt_xdate()
            f.tight_layout(rect=[0, 0.03, 1, 0.95])
            plt.title('Tile {} Pol {} - RFI'.format(tile, pol))
            plt.xlabel('Time')
            plt.ylabel('RFI')
            plt.legend()
            plt.savefig(os.path.join(output_directory, "rfi_tile_{}_pol_{}".format(tile, pol)), dpi=300)
            plt.close(f)

            # ================================== PLOT Spectra ======================================
            f = plt.figure(figsize=(16, 12))
            plt.subplot(111)
            ax = plt.gca()
            xfmt = md.DateFormatter('%-j - %H:%M:%S')
            ax.xaxis.set_major_formatter(xfmt)

            for antenna in range(16):
                plt.plot(timestamps, np.sum(antenna_bandpass[:, antenna, pol, :], axis=1), label='Antenna {}'.format(antenna))

            # Finalise plot and save
            f.autofmt_xdate()
            f.tight_layout(rect=[0, 0.03, 1, 0.95])
            plt.title('Tile {} Pol {} - Spectra'.format(tile, pol))
            plt.xlabel('Time')
            plt.ylabel('Power')
            plt.legend()
            plt.savefig(os.path.join(output_directory, "spectra_tile_{}_pol_{}".format(tile, pol)), dpi=300)
            plt.close(f)

            # ================================== PLOT Waterfall ======================================
            for antenna in range(16):
                f = plt.figure(figsize=(16, 12))
                plt.subplot(111)
                ax = plt.gca()
                xfmt = md.DateFormatter('%-j - %H:%M:%S')
                ax.xaxis.set_major_formatter(xfmt)

                plt.imshow(antenna_bandpass[:, antenna, pol, :].T,
                           extent=[timestamps[0], timestamps[-1], 0, 511],
                           aspect='auto')

                # Finalise plot and save
                f.autofmt_xdate()
                f.tight_layout(rect=[0, 0.03, 1, 0.95])
                plt.title('Tile {} Antenna {} Pol {} - Waterfall'.format(tile, antenna, pol))
                plt.xlabel('Time')
                plt.ylabel('Channel')
                plt.colorbar()
                plt.savefig(os.path.join(output_directory, "waterfall_tile_{}_antenna_{}_pol_{}".format(tile, antenna, pol)), dpi=300)
                plt.close(f)

    # ================================== PLOT Temperatures ======================================
    f = plt.figure(figsize=(16, 12))
    plt.subplot(111)
    ax = plt.gca()
    xfmt = md.DateFormatter('%-j - %H:%M:%S')
    ax.xaxis.set_major_formatter(xfmt)

    for tile in tiles:
        plt.plot(timestamps, fpga0_temp[tile, :], label='Tile {} - FPGA 0'.format(tile))
        plt.plot(timestamps, fpga1_temp[tile, :], label='Tile {} - FPGA 1'.format(tile))

    # Finalise plot and save
    f.autofmt_xdate()
    f.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.title('Temperature')
    plt.xlabel('Time')
    plt.ylabel('Temperature')
    plt.legend()
    plt.savefig(os.path.join(output_directory, "temperatures"), dpi=300)
    plt.close(f)

    # ================================== PLOT Current ======================================
    f = plt.figure(figsize=(16, 12))
    plt.subplot(111)
    ax = plt.gca()
    xfmt = md.DateFormatter('%-j - %H:%M:%S')
    ax.xaxis.set_major_formatter(xfmt)

    for tile in tiles:
        plt.plot(timestamps, current[tile, :], label='Tile {}'.format(tile))

    # Finalise plot and save
    f.autofmt_xdate()
    f.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.title('Voltage')
    plt.xlabel('Time')
    plt.ylabel('Voltage')
    plt.legend()
    plt.savefig(os.path.join(output_directory, "voltage"), dpi=300)
    plt.close(f)


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
    p.set_usage('process_metrics.py [options] INPUT_FILE')
    p.set_description(__doc__)

    opts, args = p.parse_args(argv[1:])

    # Generate plots
    process_metrics()
