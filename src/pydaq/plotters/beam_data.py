from __future__ import division
from pydaq.persisters import BeamFormatFileManager, FileDAQModes
import matplotlib.pyplot as plt
from pydaq.plotters.utils import *
import logging


# TODO: Support multiple beams
def plot_beam_data(conf, integrated=False):
    """ Plot beam data """
    logging.info("Plotting beam data. Ignoring antenna selection")

    # Sanity check
    if integrated:
        if conf.plot_type in [PlotTypes.Phase, PlotTypes.ImagPart, PlotTypes.RealPart]:
            logging.error(
                "Selected plot type ({}) not valid for integrated beam data, exiting".format(conf.plot_type.name))
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
        beam_plotter = BeamFormatFileManager(root_path=conf.directory, daq_mode=FileDAQModes.Integrated)
    else:
        beam_plotter = BeamFormatFileManager(root_path=conf.directory, daq_mode=FileDAQModes.Burst)

    # Get plotting parameters
    params = get_plotting_parameters(beam_plotter, conf)

    # Further sanity checks
    if len(params['channels']) == 1:
        if conf.plot_type in [PlotTypes.Spectrum, PlotTypes.Waterfall]:
            logging.warning("Data files contains a single channel (or single channel requested), "
                            "cannot generate waterfall or spectrum plot. Switching to magnitude")
            conf.plot_type = PlotTypes.Magnitude
        elif conf.separate:
            logging.warning("Separate plotting not supported for single channel plots. Ignoring")
            conf.separate = False

    # Read data. Data is in pol/channel/sample/beam order
    data, timestamps = beam_plotter.read_data(timestamp=conf.timestamp,
                                     tile_id=conf.tile_id,
                                     channels=params['channels'],
                                     polarizations=params['pols'],
                                     n_samples=params['samples'],
                                     sample_offset=params['offset'],
                                     beams=[0])

    # Pre-process data
    if not integrated:
        data = (data['real'] + 1j * data['imag']).astype(np.complex64)
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
        ts = set_figure_for_timestamps(timestamps, conf.time)
        for pol in params['pols']:
            plt.plot(ts, data[pol, 0, :, 0], label="Pol {}".format(pol))
        plt.title("Plotting Power, Channel {}".format(params['channels'][0]))
        plt.xlabel('Datetime' if conf.time else "Samples")
        plt.ylabel('Power{}'.format(" (db)" if conf.log else ""))
        plt.grid(True)
        plt.legend()

        # Output to file if required
        if conf.output:
            output = "{}.png".format(conf.output)
            plt.savefig(output, figsize=(12, 8))

    # Generate spectrum plots if required
    elif conf.plot_type == PlotTypes.Spectrum:

        # Plot pols separately
        if conf.separate and len(params['pols']) > 1:
            fig, ax = plt.subplots(nrows=1, ncols=2, sharex='all', sharey='all', figsize=(12, 8))
            fig.suptitle("Plotting {} ".format(conf.plot_type.name))
            for pol, col in enumerate(ax):
                col.plot(frequencies, old_div(np.sum(data[pol, :, :, 0], axis=0), params['samples']))
                col.set_xlim((frequencies[0], frequencies[-1]))
                col.set_title("Pol {}".format(pol))
                col.grid(True)
                col.set_xlabel("Frequency (MHz)")
                if pol == 0:
                    col.set_ylabel('Power{}'.format(" (db)" if conf.log else ""))

            # Output to file if required
            if conf.output:
                output = "{}.png".format(conf.output)
                plt.savefig(output, figsize=(12, 8))

        # Plot pols together
        else:
            plt.figure(figsize=(12, 8))
            for pol in params['pols']:
                plt.plot(frequencies, old_div(np.sum(data[pol, :, :, 0], axis=1), params['samples']), label="Pol {}".format(pol))
            plt.title("Plotting {}".format(conf.plot_type.name))
            plt.xlim((frequencies[0], frequencies[-1]))
            plt.xlabel('Channel number')
            plt.ylabel("Value")
            plt.grid(True)
            plt.legend()

            # Output to file if required
            if conf.output:
                output = "{}.png".format(conf.output)
                plt.savefig(output, figsize=(12, 8))

    # Generate waterfall plots
    else:
        # If a single pol is specified, plot on it ows
        if len(params['pols']) == 1:
            plt.figure(figsize=(12, 8))
            to_plot = data[params['pols'][0], :, :, 0].T
            plt.imshow(to_plot, aspect='auto', extent=[frequencies[0], frequencies[-1], 0, to_plot.shape[0]])
            plt.title("Plotting {}".format(conf.plot_type.name))
            plt.xlabel('Frequency (MHz)')
            plt.ylabel("Time (samples)")
            plt.colorbar()

            # Output to file if required
            if conf.output:
                output = os.path.join(conf.output, ".png")
                plt.savefig(output, figsize=(12, 8))

        # Otherwise plot each pol in a separate subplot
        else:
            fig, ax = plt.subplots(nrows=1, ncols=2, sharex='all', sharey='all', figsize=(12, 8))
            fig.suptitle("Plotting {} ".format(conf.plot_type.name))
            for pol, col in enumerate(ax):
                to_plot = data[pol, :, :, 0].T
                im = col.imshow(to_plot, aspect='auto', extent=[frequencies[0], frequencies[-1], 0, to_plot.shape[0]])
                col.set_xlabel("Frequency (MHz)")
                if pol == 0:
                    col.set_ylabel('Time (samples)')

            fig.subplots_adjust(bottom=0.1, top=0.9, left=0.1, right=0.88,
                                wspace=0.05, hspace=0.17)
            cb_ax = fig.add_axes([0.9, 0.1, 0.02, 0.8])
            fig.colorbar(im, cax=cb_ax)

            # Output to file if required
            if conf.output:
                output = "{}.png".format(conf.output)
                plt.savefig(output, figsize=(12, 8))

    # All done, show
    if not conf.output:
        plt.show()
