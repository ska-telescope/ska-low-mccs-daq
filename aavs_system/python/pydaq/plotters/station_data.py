from __future__ import division
from pydaq.persisters import StationBeamFormatFileManager, FileDAQModes
from pydaq.plotters.utils import *
from scipy.signal import medfilt
import matplotlib.pyplot as plt
import numpy as np
import logging


def plot_station_beam_data(conf):
    """ Plot beam data """
    logging.info("Plotting station beam data. Ignoring tile ID and antenna selection")

    # Sanity checks
    if conf.plot_type in [PlotTypes.Phase, PlotTypes.ImagPart, PlotTypes.RealPart]:
        logging.error(
            "Selected plot type ({}) not valid for station data, exiting".format(conf.plot_type.name))
        exit()

    if not conf.separate and conf.plot_type == PlotTypes.Waterfall:
        logging.info(
            "Selected plot type {} requires separate plots. Enabling separate plotting".format(conf.plot_type.name))

    # Create station data file manager
    station_plotter = StationBeamFormatFileManager(root_path=conf.directory, daq_mode=FileDAQModes.Integrated)

    # Get plotting parameters
    params = get_plotting_parameters(station_plotter, conf)

    # Further sanity checks
    if len(params['channels']) == 1:
        if conf.plot_type in [PlotTypes.Spectrum, PlotTypes.Waterfall]:
            logging.warning("Data files contains a single channel (or single channel requested), "
                            "cannot generate waterfall or spectrum plot. Switching to magnitude")
            conf.plot_type = PlotTypes.Magnitude
        elif conf.separate:
            logging.warning("Separate plotting not supported for single channel plots. Ignoring")
            conf.separate = False

    # Read data. Data is in pol/samples/channel
    data, timestamps, _ = station_plotter.read_data(timestamp=conf.timestamp,
                                                    channels=params['channels'],
                                                    polarizations=params['pols'],
                                                    n_samples=params['samples'],
                                                    sample_offset=params['offset'])

    # Pre-process data
    data = process_data_for_plot_type(data, conf.plot_type)

    # Get plotting parameters
    frequencies = get_frequencies(params['channels'], conf.frequency)

    # If log is required, process data
    if conf.log:
        np.seterr(divide='ignore')
        data = 10 * np.log10(data)
        np.seterr(divide='warn')
        data[np.isneginf(data)] = 0

    # If plotting a single channel, plot all pols on top of each other
    if len(params["channels"]) == 1:

        plt.figure(figsize=(12, 8))
        for pol in params['pols']:
            ts = set_figure_for_timestamps(timestamps, conf.time, rollover=conf.rollover)
            if conf.median_filter:
                plt.plot(ts, medfilt(data[pol, :, 0], 5), label="Pol {}".format(pol))
            else:
                plt.plot(ts, data[pol, :, 0], label="Pol {}".format(pol))
            plt.xlim((ts[0], ts[-1]))
        plt.title("Plotting Power, Channel {}".format(params['channels'][0]))
        plt.xlabel('Datetime' if conf.time else "Samples")
        plt.ylabel('Power{}'.format(" (db)" if conf.log else ""))
        plt.grid(True)
        plt.legend()

        # Output to file if required
        if conf.output:
            root, ext = os.path.splitext(conf.output)
            if not ext:
                ext = ".png"
            output = "{}{}".format(root, ext)
            plt.savefig(output)
            plt.close()

    # Generate spectrum plots if required
    elif conf.plot_type == PlotTypes.Spectrum:

        # Plot pols separately
        if conf.separate and len(params['pols']) > 1:
            fig, ax = plt.subplots(nrows=1, ncols=2, sharex='all', sharey='all', figsize=(12, 8))
            fig.suptitle("Plotting {} ".format(conf.plot_type.name))
            for pol, col in enumerate(ax):
                col.plot(frequencies, np.sum(data[pol, :, :], axis=0) // params['samples'])
                col.set_xlim((frequencies[0], frequencies[-1]))
                col.set_title("Pol {}".format(pol))
                col.set_xlabel("Frequency (MHz)")
                col.grid(True)
                if pol == 0:
                    col.set_ylabel('Power{}'.format(" (db)" if conf.log else ""))

            if conf.output:
                root, ext = os.path.splitext(conf.output)
                if not ext:
                    ext = ".png"
                output = "{}{}".format(root, ext)
                plt.savefig(output)
                plt.close()

        # Plot pols together
        else:
            plt.figure(figsize=(12, 8))
            for pol in params['pols']:
                plt.plot(frequencies, old_div(np.sum(data[pol, :, :], axis=0), params['samples']), label="Pol {}".format(pol))
            plt.title("Plotting {}".format(conf.plot_type.name))
            plt.xlabel('Frequency (MHz)')
            plt.ylabel("Value")
            plt.xlim((frequencies[0], frequencies[-1]))
            plt.grid(True)
            plt.legend()

            if conf.output:
                root, ext = os.path.splitext(conf.output)
                if not ext:
                    ext = ".png"
                output = "{}{}".format(root, ext)
                plt.savefig(output)
                plt.close()

    # Generate waterfall plots
    else:
        # If a single pol is specified, plot on it ows
        if len(params['pols']) == 1:
            plt.figure(figsize=(12, 8))
            ts = set_figure_for_timestamps(timestamps, conf.time, True)
            plt.imshow(data[params['pols'][0], :, :], aspect='auto',
                       extent=[frequencies[0], frequencies[-1], ts[-1], ts[0]])
            plt.title("Plotting {}".format(conf.plot_type.name))
            plt.ylabel('Datetime' if conf.time else "Samples")
            plt.xlabel('Frequency (MHz)')
            plt.ylabel("Time (samples)")
            plt.colorbar()

            if conf.output:
                root, ext = os.path.splitext(conf.output)
                if not ext:
                    ext = ".png"
                output = "{}{}".format(root, ext)
                plt.savefig(output)
                plt.close()

        # Otherwise plot each pol in a separate subplot
        else:
            fig, ax = plt.subplots(nrows=1, ncols=2, sharex='all', sharey='all', figsize=(12, 8))
            fig.suptitle("Plotting {} ".format(conf.plot_type.name))
            for pol, col in enumerate(ax):
                ts = set_figure_for_timestamps(timestamps, conf.time, True)
                im = col.imshow(data[pol, :, :], aspect='auto',
                                extent=[frequencies[0], frequencies[-1], ts[-1], ts[0]])
                col.set_title("Pol {}".format(pol))
                col.set_xlabel("Frequency (MHz)")
                if pol == 0:
                    col.set_ylabel('Datetime' if conf.time else "Samples")

            # Add colorbar
            fig.subplots_adjust(bottom=0.1, top=0.9, left=0.1, right=0.88,
                                wspace=0.02, hspace=0.02)
            cb_ax = fig.add_axes([0.9, 0.1, 0.02, 0.8])
            fig.colorbar(im, cax=cb_ax)

            if conf.output:
                root, ext = os.path.splitext(conf.output)
                if not ext:
                    ext = ".png"
                output = "{}{}".format(root, ext)
                plt.savefig(output)
                plt.close()

    # All done, show
    if not conf.output:
        plt.show()
