from pydaq.persisters import CorrelationFormatFileManager, FileDAQModes
from pydaq.plotters.utils import *
import logging


def plot_correlated_data(conf):
    """ Plot correlated data """

    # Sanity checks
    if conf.plot_type in [PlotTypes.Spectrum, PlotTypes.Waterfall]:
        logging.error("Plot type {} not supported for correlated data. Exiting".format(conf.plot_type.name))
        exit(-1)

    if conf.nof_samples > 1:
        logging.warning("Only one sample can be plotted for correlated data")
        conf.nof_samples = 1

    # In the case of correlated data we only have one channel,
    # and it's used in place of tile_id in several spots which expect an int.
    conf.channels = int(conf.channels)

    # Create correlation data file manager
    corr_plotter = CorrelationFormatFileManager(root_path=conf.directory, daq_mode=FileDAQModes.Burst)

    # Get plotting parameters
    params = get_plotting_parameters(corr_plotter, conf)

    # Read data
    data, _ = corr_plotter.read_data(timestamp=conf.timestamp,
                                     polarizations=params['pols'],
                                     n_samples=conf.nof_samples,
                                     sample_offset=conf.sample_offset,
                                     channel_id=params['channels'])

    # If log is required, process data
    if conf.log:
        np.seterr(divide='ignore')
        data = 20 * np.log10(data)
        np.seterr(divide='warn')
        data[np.isneginf(data)] = 0

    # Plot polarisations in different plots
    for pol in params['pols']:

        # Create stokes parameters
        stokes = 0 if pol == 0 else 3

        # Create an empty array for generating a plottable matrix
        grid = np.zeros((len(params['antennas']), len(params['antennas'])), dtype=np.complex64)

        # Create correlation matrix
        counter = 0
        for i in range(nof_antennas):
            counter += 1
            for j in range(i+1, nof_antennas):
                grid[i, j] = data[0, counter, stokes, 0]
                counter += 1

        # Process data
        grid = process_data_for_plot_type(grid, conf.plot_type)

        plt.figure(figsize=(14, 10))
        plt.imshow(grid, aspect='auto')
        plt.title("Stokes {}. Plotting {}".format('XX' if pol == 0 else 'YY', conf.plot_type.name))
        plt.xlabel("Antenna")
        plt.ylabel("Antenna")
        plt.colorbar()

    plt.show()
