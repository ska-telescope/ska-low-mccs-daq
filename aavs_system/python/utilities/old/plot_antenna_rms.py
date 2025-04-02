from builtins import range
import matplotlib.pyplot as plt
from datetime import datetime
import matplotlib.dates as md
import datetime as dt
import numpy as np
import logging
import time
import json
import glob
import os


def load_files(directory):
    """ Load json dumps from directory and plot """

    # Get all the JSON dumps
    logging.info("Getting file list")
    files = sorted(glob.glob(os.path.join(directory, '*.json')))

    # If there are not files, return
    if len(files) == 0:
        logging.info("No files found")
        return

    # Tile id are hardcoded for now
    tile_ids = [1, 6, 11, 16]
    nof_tiles = 1

    # If a numpy array exists, load it up
    pre_computed_data = False
    if os.path.exists(os.path.join(directory, 'data.npy')):
        logging.info("Loading pre-computed data")
        data = np.load(os.path.join(directory, 'data.npy'))
        if data.shape[3] == len(files):            
            pre_computed_data = True
        else:
            logging.info("{} != {}. Reloading files".format(data.shape[3], len(files)))

    if not pre_computed_data:
        # Generate empty numpy array
        data = np.zeros((nof_tiles, 16, 2, len(files)))

        # Go through all files
        for i, filepath in enumerate(files):
            with open(filepath, 'r') as f:
                for t, tile_data in enumerate(json.load(f)):
                    for antenna in range(16):
                        data[t, antenna, 0, i] = tile_data['antenna_{}_pol_0'.format(antenna)]['rms']
                        data[t, antenna, 1, i] = tile_data['antenna_{}_pol_1'.format(antenna)]['rms']

            if i % 1000 == 0:
                logging.info("Processed {} of {}".format(i, len(files)))

        # Save processed data to disk
        np.save(os.path.join(directory, 'data.npy'), data)

    # Create data array for x-axis
    dates = []
    for f in files:
        try:
            dates.append(datetime.strptime(os.path.basename(f).replace('.json', ''), '%Y-%m-%d %H:%M:%S.%f'))
        except:
            dates.append(datetime.strptime(os.path.basename(f).replace('.json', ''), '%Y-%m-%d %H_%M_%S.%f'))
    timestamps = [dt.datetime.fromtimestamp(time.mktime(ts.timetuple())) for ts in dates]

    # Plot
    logging.info("Generating plots")

    f = plt.figure()
    plt.subplot(111)
    ax = plt.gca()
 #   ax.xaxis.set_major_formatter(md.DateFormatter('%H:%M:%S.%f'))

    # Plot separately
    tile_ids = [0]
    for t, tile in enumerate(tile_ids):
        for a in range(16):
            plt.plot(data[t, a, 1, :].T, label="{}-{}-{}".format(tile, a, 'X'))
            plt.plot(data[t, a, 0, :].T, label="{}-{}-{}".format(tile, a, 'Y'))

  #  f.autofmt_xdate()
  #  plt.xlim((timestamps[0], timestamps[-1]))
    plt.xlabel("Time")
    plt.ylabel("RMS")
   # plt.legend()
    plt.show()


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
    p.set_usage('plot_antenna_rms.py [options] INPUT_FILE')
    p.set_description(__doc__)

    p.add_option("-d", "--directory", action="store", dest="directory", default='.',
                 help="Directory to store readings [default: '.']")
    opts, args = p.parse_args(argv[1:])

    if not os.path.exists(opts.directory):
        logging.error("Invalid directory")
        exit(-1)

    # Create station
    load_files(opts.directory)

