from pydaq.persisters import RawFormatFileManager, FileDAQModes
from pydaq.plotters.utils import *
from matplotlib import pyplot as plt
import logging


def plot_raw_data(conf):
    """ Plot raw data """
    logging.info("Plotting raw antenna data")

    # Check data plotting type is supported
    if conf.plot_type != PlotTypes.Magnitude:
        logging.error("Plot type {} not supported for raw data. Exiting".format(conf.plot_type.name))
        exit(-1)

    if conf.log:
        logging.warning("Log not supported for raw data. Ignoring")

    # Create raw data file manager
    raw_plotter = RawFormatFileManager(root_path=conf.directory, daq_mode=FileDAQModes.Burst)

    # Get plotting parameters
    params = get_plotting_parameters(raw_plotter, conf)

    # Data is in antennas/pol/samples order
    data, _ = raw_plotter.read_data(timestamp=conf.timestamp,
                                    tile_id=conf.tile_id,
                                    antennas=params['antennas'],
                                    polarizations=params['pols'],
                                    n_samples=params['samples'],
                                    sample_offset=params['offset'])

    # Plot all antennas separately on a single figure
    if conf.separate:
        for pol in params['pols']:
            # Calculate number of required rows and columns
            n_rows, n_cols = get_subplot_configuration(len(params['antennas']))
            fig, ax = plt.subplots(nrows=n_rows, ncols=n_cols, sharex='all', sharey='all', figsize=(12, 8))
            fig.suptitle("Polarisation {}".format(pol))

            for antenna in range(len(params['antennas'])):
                antenna_number = params['antennas'][antenna]
                axes, last_row, first_col = get_axes(ax, antenna)
                axes.plot(data[antenna, pol, :], color=get_color(antenna_number))
                axes.set_title("Antenna: {}, RX: {}".format(antenna_number, get_rx(antenna_number)))
                axes.grid(True)

                if last_row:
                    axes.set_xlabel("Sample")
                if first_col:
                    axes.set_ylabel('Units')

            # Output to file if required
            if conf.output:
                output = "{}_pol_{}.png".format(conf.output, 'X' if pol == 0 else 'Y')
                plt.savefig(output, figsize=(12, 8))

    else:
        for pol in params['pols']:
            plt.figure(figsize=(12, 8))
            for antenna in range(len(params['antennas'])):
                antenna_number = params['antennas'][antenna]
                plt.plot(data[antenna, pol, :],
                         color=get_color(antenna_number),
                         label="A: {}, RX: {}".format(antenna_number, antenna_number))
                plt.title("Tile {} - Polarisation {}".format(conf.tile_id, pol))
                plt.xlim((0, data.shape[2]))
                plt.xlabel('Sample')
                plt.ylabel('Units')
                plt.grid(True)
                plt.legend()

            # Output to file if required
            if conf.output:
                output = "{}_pol_{}.png".format(conf.output, 'X' if pol == 0 else 'Y')
                plt.savefig(output, figsize=(12, 8))

    # All done, show plots
    if not conf.output:
        plt.show()
