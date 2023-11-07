from __future__ import division
from past.utils import old_div
import logging
import os
from sys import stdout

import h5py
import matplotlib.pyplot as plt
import numpy as np


def antenna_rms(filepath):
    """ Check if raw data file exceeds threshold"""

    # Read file
    with h5py.File(filepath, 'r') as f:
        # Get data and calculate RMS. Note that we don't care which ADC
        # signal is causing the trigger, as long as one of the channels has a
        # high RMS then we keep the file
        data = f['raw_']['data'][:].astype(np.int)
        rms = np.sqrt(np.mean(np.power(data, 2), axis=1))

    return rms


def channelise(filepath, adc_channel, nof_channels):
    """ Check if raw data file exceeds threshold"""

    # Read file
    with h5py.File(filepath, 'r') as f:
        data = f['raw_']['data'][:].astype(float)
        data = data[adc_channel, :].reshape((old_div(data.shape[1], nof_channels), nof_channels))
        channelised = np.fft.fftshift(np.fft.fft(data, axis=1))[:, old_div(nof_channels,2):]
        freqs = old_div(np.arange(0, nof_channels) * 800e6, nof_channels) * 1e-6

        plt.figure()
        plt.imshow(10*np.log10(np.abs(channelised)), aspect='auto', extent=[freqs[0], freqs[old_div(nof_channels, 2)], 1, data.shape[0]], origin='lower')
        plt.xlabel("Frequency (MHz)")
        plt.ylabel("Spectrum #")
        clb = plt.colorbar()
        clb.ax.set_title('Power (dB)')
        
        plt.figure()
        plt.plot(10*np.log10(np.sum(np.abs(channelised), axis=0)))
        plt.show()


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv

    parser = OptionParser(usage="usage: %antenna_spectrum_plotter.py [options]")
    parser.add_option("-f", "--file", action="store", dest="file",
                      default="", help="File to process")
    (conf, args) = parser.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(format)
    log.addHandler(ch)

    # Check if directory exists
    if not (os.path.exists(conf.file) and os.path.isfile(conf.file)):
        logging.error("Specified path (%s) does not exist or is not a file" % conf.file)
        exit(0)

    # Find all raw data files
    rms = antenna_rms(conf.file)
    max_rms_index = np.argmax(rms)

    # Channelise
    channelise(conf.file, max_rms_index, 1024)
