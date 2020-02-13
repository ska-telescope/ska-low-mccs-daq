import os

import matplotlib.pyplot as plt
import matplotlib.dates as md
import numpy as np
import datetime
import logging

if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    p = OptionParser()
    p.set_usage('offline_beamformer.py [options] INPUT_FILE')
    p.set_description(__doc__)

    p.add_option('-f', '--files', dest='files', action='store', default=None,
                 help="Comma separated list of npy files to plot")
    p.add_option('-p', '--pol', dest='pol', action='store', default='all',
                 help="Polarisations to plot [X, Y or ALL]. Default: ALL")
    p.add_option('-l', '--power', dest='power', action='store_true',
                 help="Plot power (default: False)")

    opts, args = p.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(format)
    log.addHandler(ch)

    # Sanity checks
    if opts.files is None:
        logging.error("At least on file required to plot")
        exit()

    # Generate figure
    f = plt.figure(figsize=(12, 8))

    # Line styles and colors
    styles = ['-', '--', ':', '-', '-.']
    color_x = 'k'
    color_y = 'b'

    # Process each file separately
    for i, beam_file in enumerate(opts.files.split(',')):

        # Load file
        loaded_data = np.load(beam_file)

        # Get filename for legend
        filename = os.path.basename(os.path.abspath(beam_file)).replace('.npy', '')

        # Process timestamps
        new_timestamps = [md.date2num(datetime.datetime.utcfromtimestamp(x)) for x in loaded_data[:, 0]]

        # Remove timestamps from data
        data = loaded_data[:, 1:3]

        # Convert to power if required
        if opts.power:
            np.seterr(divide='ignore')
            data = 10 * np.log10(data)
            np.seterr(divide='warn')
            data[np.isneginf(data)] = 0

        # Make the first file more opaque than the rest
        alpha = 1
        if i != 0:
            alpha = 0.5

        # Find the peak of the plot for the first file
        # if i == 0:
        #     maximum = np.where(data[:, 0] == np.max(data))
        #     power = data[:, 0][maximum[0]][0]
        #     timestamp = new_timestamps[maximum[0][0]]
        #     human_timestamp = datetime.datetime.utcfromtimestamp(loaded_data[maximum[0][0], 0])
        #     plt.text(timestamp, power + 0.2, 
        #              "(Power: {:.2f}, Time: {})".format(power, human_timestamp))

        # Plot
        if opts.pol.lower() in ['x', 'all']:
            plt.plot(new_timestamps, data[:, 0], linestyle=styles[i], color=color_x, 
                     label="{} - X".format(filename), alpha=alpha)

        if opts.pol.lower() in ['y', 'all']:
            plt.plot(new_timestamps, data[:, 1], linestyle=styles[i], color=color_y,
                     label="{} - Y".format(filename), alpha=alpha)

    # Done, pretty up plot
    ax = plt.gca()
    date_format = md.DateFormatter('%H:%M:%S')
    ax.xaxis.set_major_formatter(date_format)

    plt.xlabel("Time")
    if opts.power:
        plt.ylabel("Power (dB)")
    else:
        plt.ylabel("Power (linear)")
    plt.legend()
    plt.grid()

    plt.show()


