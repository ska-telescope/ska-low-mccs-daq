from __future__ import division

import matplotlib.pyplot as plt

from pydaq.persisters import ChannelFormatFileManager, FileDAQModes
from pydaq.plotters.utils import *


def plot_channel_data(conf, integrated=False, continuous=False):
    """ Plot channelised data """
    logging.info("Plotting channelised antenna data")

    # Sanity check
    if integrated:
        if conf.plot_type in [PlotTypes.Phase, PlotTypes.ImagPart, PlotTypes.RealPart]:
            logging.error(
                "Selected plot type ({}) not valid for integrated channel data, exiting".format(conf.plot_type.name))
            exit()

    else:
        if conf.log and conf.plot_type in [PlotTypes.Phase, PlotTypes.ImagPart, PlotTypes.RealPart]:
            logging.warning("Log not supported for selected plot type ({}). Ignoring".format(conf.plot_type.name))
            conf.log = False

        if not conf.separate and conf.plot_type == PlotTypes.Waterfall:
            logging.info(
                "Selected plot type {} requires separate plots. Enabling separate plotting".format(conf.plot_type.name))

    # Create channel data file manager
    if integrated:
        channel_plotter = ChannelFormatFileManager(root_path=conf.directory, daq_mode=FileDAQModes.Integrated)
    elif continuous:
        channel_plotter = ChannelFormatFileManager(root_path=conf.directory, daq_mode=FileDAQModes.Continuous)
    else:
        channel_plotter = ChannelFormatFileManager(root_path=conf.directory, daq_mode=FileDAQModes.Burst)

    # Get plotting parameters
    params = get_plotting_parameters(channel_plotter, conf)

    # Further sanity checks
    if len(params['channels']) == 1:
        if conf.plot_type in [PlotTypes.Spectrum, PlotTypes.Waterfall]:
            logging.warning("Data files contains a single channel (or single channel requested), "
                            "cannot generate waterfall or spectrum plot. Switching to magnitude")
            conf.plot_type = PlotTypes.Magnitude
        elif conf.separate:
            logging.warning("Separate plotting not supported for single channel plots. Ignoring")
            conf.separate = False

    # Read data. Data is in channel/antenna/pol/sample order
    data, timestamps = channel_plotter.read_data(timestamp=conf.timestamp,
                                                 tile_id=conf.tile_id,
                                                 channels=params['channels'],
                                                 antennas=params['antennas'],
                                                 polarizations=params['pols'],
                                                 n_samples=params['samples'],
                                                 sample_offset=params['offset'])

    # Pre-process data
    if not integrated:
        data = (data['real'] + 1j * data['imag']).astype(np.complex64)
    data = process_data_for_plot_type(data, conf.plot_type)

    # Get plotting parameters
    n_rows, n_cols = get_subplot_configuration(len(params['antennas']))
    frequencies = get_frequencies(params['channels'], conf.frequency)

    # If log is required, process data
    if conf.log:
        np.seterr(divide='ignore')
        if not integrated:
            data = 20 * np.log10(data)
        else:
            data = 10 * np.log10(data)
        np.seterr(divide='warn')
        data[np.isneginf(data)] = 0

    # If plotting a single channel, plot all antennas on top of each other
    if len(params["channels"]) == 1:
        for p, pol in enumerate(params['pols']):
            plt.figure(figsize=(12, 8))
            ts = set_figure_for_timestamps(timestamps, conf.time)
            plt.title("Tile {} - Polarisation {} - Channel {}. Plotting {}".format(conf.tile_id, pol_names[pol],
                                                                                   params['channels'][0],
                                                                                   conf.plot_type.name))
            for a, antenna in enumerate(params['antennas']):
                plt.plot(ts, data[0, a, p, :],
                         label="A: {}, RX: {}".format(antenna, get_rx(antenna)),
                         color=get_color(antenna))
                plt.xlabel('Datetime' if conf.time else "Samples")
                plt.ylabel("Value")
                plt.grid(True)
                plt.legend()

            if conf.output:
                root, ext = os.path.splitext(conf.output)
                if not ext:
                    ext = ".png"
                output = "{}_pol_{}{}".format(root, pol_names[pol], ext)
                plt.savefig(output)
                plt.close()

    # Generate waterfall plots if required
    elif conf.plot_type == PlotTypes.Spectrum:

        # Plot spectra in separate plots
        if conf.separate:
            for p, pol in enumerate(params['pols']):
                fig, ax = plt.subplots(nrows=n_rows, ncols=n_cols, sharex='all', sharey='all', figsize=(12, 8))
                fig.suptitle("Polarisation {}".format(pol_names[pol]))

                for a, antenna in enumerate(params['antennas']):
                    axes, last_row, first_col = get_axes(ax, a)
                    axes.plot(frequencies, old_div(np.sum(data[:, a, p, :], axis=1), params['samples']),
                              color=get_color(antenna))
                    axes.set_xlim((frequencies[0], frequencies[-1]))
                    axes.set_title("Antenna: {}, RX: {}".format(antenna, get_rx(antenna)))

                    if last_row:
                        axes.set_xlabel("Frequency (MHz)")
                    if first_col:
                        axes.set_ylabel('Power{}'.format(" (db)" if conf.log else ""))

                if conf.output:
                    root, ext = os.path.splitext(conf.output)
                    if not ext:
                        ext = ".png"
                    output = "{}_pol_{}{}".format(root, pol_names[pol], ext)
                    plt.savefig(output)
                    plt.close()

        # Show spectra in same figure
        else:
            for p, pol in enumerate(params['pols']):
                plt.figure(figsize=(12, 8))
                for a, antenna in enumerate(params['antennas']):
                    plt.plot(frequencies, old_div(np.sum(data[:, a, p, :], axis=1), params['samples']),
                             label="A: {}, RX: {}".format(antenna, get_rx(antenna)),
                             color=get_color(antenna))
                    plt.title("Tile {} - Polarisation {}".format(conf.tile_id, pol_names[pol]))
                    plt.xlabel('Frequency (MHz)')
                    plt.ylabel('Power{}'.format(" (db)" if conf.log else ""))
                    plt.xlim((frequencies[0], frequencies[-1]))
                    plt.grid(True)
                    plt.legend()

                if conf.output:
                    root, ext = os.path.splitext(conf.output)
                    if not ext:
                        ext = ".png"
                    output = "{}_pol_{}{}".format(root, pol_names[pol], ext)
                    plt.savefig(output)
                    plt.close()

    # Generate waterfall plots
    else:
        for p, pol in enumerate(params['pols']):
            fig, ax = plt.subplots(nrows=n_rows, ncols=n_cols, sharex='all', sharey='all', figsize=(12, 8))
            fig.suptitle("Polarisation {} (Plotting {}) ".format(pol_names[pol], conf.plot_type.name))

            for a, antenna in enumerate(params['antennas']):
                axes, last_row, first_col = get_axes(ax, a)
                to_plot = data[:, a, p, :].T
                im = axes.imshow(to_plot, aspect='auto', extent=[frequencies[0], frequencies[-1], 0, to_plot.shape[0]])
                axes.set_title("Antenna: {}, RX: {}".format(antenna, get_rx(antenna)))

                if last_row:
                    axes.set_xlabel("Frequency (MHz)")
                if first_col:
                    axes.set_ylabel("Time")

            fig.subplots_adjust(bottom=0.1, top=0.9, left=0.1, right=0.88,
                                wspace=0.05, hspace=0.17)
            cb_ax = fig.add_axes([0.9, 0.1, 0.02, 0.8])
            fig.colorbar(im, cax=cb_ax)

            if conf.output:
                root, ext = os.path.splitext(conf.output)
                if not ext:
                    ext = ".png"
                output = "{}_pol_{}{}".format(root, pol_names[pol], ext)
                plt.savefig(output)
                plt.close()

    # All done, show
    if not conf.output:
        plt.show()
