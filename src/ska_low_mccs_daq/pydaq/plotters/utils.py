import calendar
import datetime
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from builtins import range
from datetime import datetime as dt
from datetime import timedelta
from enum import Enum

import matplotlib.dates as md
import matplotlib.pyplot as plt
import numpy as np

# This is used to re-map ADC channels index to the RX
# number going into the TPM
from ..persisters import CorrelationFormatFileManager, RawFormatFileManager

antenna_rx_mapping = {
    0: 1,
    1: 2,
    2: 3,
    3: 4,
    8: 5,
    9: 6,
    10: 7,
    11: 8,
    15: 9,
    14: 10,
    13: 11,
    12: 12,
    7: 13,
    6: 14,
    5: 15,
    4: 16,
}

# Ribbon color mapping
ribbon_color = {
    1: "gray",
    2: "g",
    3: "r",
    4: "k",
    5: "y",
    6: "m",
    7: "deeppink",
    8: "c",
    9: "gray",
    10: "g",
    11: "r",
    12: "k",
    13: "y",
    14: "m",
    15: "deeppink",
    16: "c",
}

# AAVS Station center
aavs_station_latitude = -26.70408
aavs_station_longitude = 116.670231

# Some global params
antennas_per_tile = 16
nof_antennas = 256


class PlotTypes(Enum):
    """ " An enumerated type for all the supported plot types"""

    RealPart = 1
    ImagPart = 2
    Magnitude = 3
    Phase = 4
    Spectrum = 5
    Waterfall = 6

    @staticmethod
    def convert_plot_type(plot_type):
        """ " Convert plot type to enum"""
        if plot_type == "real":
            return PlotTypes.RealPart
        elif plot_type == "imag":
            return PlotTypes.ImagPart
        elif plot_type == "magnitude":
            return PlotTypes.Magnitude
        elif plot_type == "phase":
            return PlotTypes.Phase
        elif plot_type == "spectrum":
            return PlotTypes.Spectrum
        elif plot_type == "waterfall":
            return PlotTypes.Waterfall
        else:
            logging.info("Plot type '{}' is not supported.".format(plot_type))
            exit(-1)


def get_rx(antenna_id):
    """Get the RX number given an antenna id"""
    return antenna_rx_mapping[antenna_id]


def get_color(antenna_id):
    """Get ribbon colour mapping given an antenna id"""
    return ribbon_color[antenna_rx_mapping[antenna_id]]


def process_data_for_plot_type(data, plot_type):
    """Pre-process data for required plot type"""
    if plot_type == PlotTypes.RealPart:
        return data.real
    elif plot_type == PlotTypes.ImagPart:
        return data.imag
    elif plot_type in [PlotTypes.Magnitude, PlotTypes.Waterfall, PlotTypes.Spectrum]:
        return np.abs(data)
    elif plot_type == PlotTypes.Phase:
        return np.angle(data)
    else:
        return data


def get_plotting_parameters(file_manager, conf):
    """Load and process metadata, returning required information"""

    # Load metadata
    metadata = {}
    try:
        # Hack due to incorrect use of tile_id for correlation files
        if type(file_manager) == CorrelationFormatFileManager:
            metadata = file_manager.get_metadata(
                timestamp=conf.timestamp, tile_id=conf.channels
            )
        else:
            metadata = file_manager.get_metadata(
                timestamp=conf.timestamp, tile_id=conf.tile_id
            )
        if metadata is None:
            raise IOError()
    except IOError:
        logging.error("Could not find data file matching parameters. Exiting")
        exit()

    # Check that plotting parameters are compatible with file metadata
    plotting_parameters = {}

    # Check nof_channels
    if type(file_manager) is not RawFormatFileManager:
        if type(file_manager) == CorrelationFormatFileManager:
            # Correlator special case, ignore channels since it's defined in the filename
            plotting_parameters["channels"] = conf.channels
        elif conf.channels == "all":
            plotting_parameters["channels"] = list(range(metadata["n_chans"]))
        else:
            channels_to_plot = extract_values(conf.channels)
            if (
                max(channels_to_plot) >= metadata["n_chans"]
                or min(channels_to_plot) < 0
            ):
                logging.error(
                    "Cannot plot channels {}, file has {} channels".format(
                        conf.channels, metadata["n_chans"]
                    )
                )
                exit(-1)
            else:
                plotting_parameters["channels"] = channels_to_plot

    # Check nof_antennas
    if type(file_manager) == CorrelationFormatFileManager:
        # Correlator special case, ignore antennas
        pass
    if conf.antennas == "all":
        plotting_parameters["antennas"] = list(range(metadata["n_antennas"]))
    else:
        antennas_to_plot = extract_values(conf.antennas)
        if max(antennas_to_plot) >= metadata["n_antennas"] or min(antennas_to_plot) < 0:
            logging.error(
                "Cannot plot antennas {}, file has {} antennas".format(
                    conf.channels, metadata["n_chans"]
                )
            )
            exit(-1)
        else:
            plotting_parameters["antennas"] = antennas_to_plot

    # Check polarisations
    if conf.polarisations == "all":
        plotting_parameters["pols"] = list(range(metadata["n_pols"]))
    else:
        pols_to_plot = extract_values(conf.polarisations)
        if max(pols_to_plot) >= metadata["n_pols"] or min(pols_to_plot) < 0:
            logging.error(
                "Cannot plot pols {}, file has {} pols".format(
                    conf.channels, metadata["n_pols"]
                )
            )
            exit(-1)
        else:
            plotting_parameters["pols"] = pols_to_plot

    # Check number of samples
    if conf.sample_offset >= metadata["written_samples"]:
        logging.error(
            "Specified sample offset {} is larger than number of samples in file {}. "
            "Exiting".format(conf.sample_offset, metadata["written_samples"])
        )

    elif conf.nof_samples == -1:
        plotting_parameters["offset"] = conf.sample_offset
        plotting_parameters["samples"] = (
            metadata["written_samples"] - conf.sample_offset
        )
        logging.info(
            "Data file contains {} samples".format(plotting_parameters["samples"])
        )

    elif conf.nof_samples + conf.sample_offset > metadata["written_samples"]:
        plotting_parameters["offset"] = conf.sample_offset
        plotting_parameters["samples"] = (
            metadata["written_samples"] - conf.sample_offset
        )
        logging.warning(
            "Cannot plot required sample range ({} samples at offset {}). Setting number of samples to "
            "{}".format(
                conf.nof_samples, conf.sample_offset, plotting_parameters["samples"]
            )
        )

    else:
        plotting_parameters["offset"] = conf.sample_offset
        plotting_parameters["samples"] = conf.nof_samples

    # Done, return plotting parameters
    return plotting_parameters


def get_subplot_configuration(nof_plots):
    """Get subplot configuration based on required number of plots"""
    if nof_plots == 1:
        return 1, 1
    elif nof_plots == 2:
        return 1, 2
    elif nof_plots <= 4:
        return 2, 2
    elif nof_plots <= 6:
        return 2, 3
    elif nof_plots <= 9:
        return 3, 3
    elif nof_plots <= 12:
        return 3, 4
    elif nof_plots <= 16:
        return 4, 4
    else:
        logging.warning("Too many plots to show on a single figure, limiting to 16")
        return 4, 4


def set_figure_for_timestamps(timestamps, enable_time=False, y_axis=False, rollover=0):
    """Get plottable timestamps for plots. Display properties based on
    number of samples and sampling rate"""

    # Just send range if time not required
    if not enable_time:
        return list(range(len(timestamps)))

    timestamps = timestamps[:, 0]

    # Check if there are gaps in timestamps
    if np.any(np.diff(timestamps) < 0):
        logging.warning("Timestamp rollover detected, attempting to fix")
        difference = timestamps[1] - timestamps[0]
        timestamps = np.arange(
            timestamps[0], timestamps[0] + len(timestamps) * difference, difference
        )

    # Apply rollover
    timestamps += rollover * (2**48 * 1e-9)

    # Generate timestamps
    new_timestamps = [
        md.date2num(datetime.datetime.utcfromtimestamp(x)) for x in timestamps
    ]

    ax = plt.gca()
    date_format = md.DateFormatter("%-j - %H:%M:%S")
    if y_axis:
        ax.yaxis.set_major_formatter(date_format)
    else:
        ax.xaxis.set_major_formatter(date_format)

    # Done, return timestamps
    return new_timestamps


def get_axes(ax, antenna):
    """Get axes for provided list and antenna index"""
    if type(ax) == np.ndarray:
        if len(ax.shape) == 1:
            return ax[antenna], True, antenna == 0
        else:
            return (
                ax[antenna // ax.shape[0], antenna % ax.shape[1]],
                (antenna // ax.shape[0]) == ax.shape[0] - 1,
                antenna % ax.shape[1] == 0,
            )
    else:
        return ax, True, True


def get_frequencies(channels, start_frequency):
    """Get frequencies in MHz"""
    df = 400 / 512.0
    return [start_frequency + c * df for c in channels]


def extract_values(values):
    """Extract values from string representation of list
    :param values: String representation of values
    :return: List of values
    """

    # Return list
    converted = []

    try:
        # Loop over all comma separated values
        for item in values.split(","):
            # Check if item contains a semi-colon
            if item.find(":") > 0:
                index = item.find(":")
                lower = item[:index]
                upper = item[index + 1 :]
                converted.extend(list(range(int(lower), int(upper) + 1)))
            else:
                converted.append(int(item))
    except:
        raise Exception("Invalid values parameter: {}".format(values))

    return converted


def camel_case(string):
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", string)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def clear_plotting_modes(conf):
    conf.plot_raw_data = False
    conf.plot_channel_data = False
    conf.plot_cont_channel_data = False
    conf.plot_integrated_channel_data = False
    conf.plot_integrated_beam_data = False
    conf.plot_beam_data = False
    conf.plot_station_beam_data = False
    conf.plot_correlated_data = False


def process_timestamp(timestamp):
    """Convert string representation of timestamp to unix epoch time"""
    try:
        parts = timestamp.split("_")
        sec = timedelta(seconds=int(parts[1]))
        date = dt.strptime(parts[0], "%Y%m%d") + sec
        # return time.mktime(date.timetuple())
        return calendar.timegm(date.timetuple())
    except Exception as e:
        logging.warning(
            "Could not convert date in filename to a timestamp: {}".format(e.message)
        )
        return None


def get_parameters_from_filename(conf):
    """Update plotting parameters for plotting a specified file"""

    # Extract directory from filename
    conf.directory = os.path.dirname(os.path.abspath(conf.file))
    filename = os.path.basename(os.path.abspath(conf.file))

    # Extract file name parts
    try:
        pattern = r"(?P<type>\w+)_(?P<mode>\w+)_(?P<tile>\d+)_(?P<timestamp>\d+_\d+)_(?P<part>\d+).hdf5"
        parts = re.match(pattern, filename).groupdict()
    except:
        return False

    # Clear any existing modes
    logging.info("Filepath specified, clearing all set plotting modes")
    clear_plotting_modes(conf)

    # Process timestamp and tile id
    conf.timestamp = process_timestamp(parts["timestamp"])
    conf.tile_id = int(parts["tile"])

    # Select plotting mode
    if parts["type"] == "beamformed":
        if parts["mode"] == "burst":
            conf.plot_beam_data = True
        elif parts["mode"] == "integ":
            conf.plot_integrated_beam_data = True
        else:
            logging.error("Invalid mode ({}) for beamformed type".format(parts["mode"]))
            return False

    elif parts["type"] == "channel":
        if parts["mode"] == "burst":
            conf.plot_channel_data = True
        elif parts["mode"] == "integ":
            conf.plot_integrated_channel_data = True
        elif parts["mode"] == "cont":
            conf.plot_cont_channel_data = True
        else:
            logging.error("Invalid mode ({}) for channel type".format(parts["mode"]))
            return False

    elif parts["type"] == "stationbeam":
        if parts["mode"] == "integ":
            conf.plot_station_beam_data = True
        else:
            logging.error("Invalid mode ({}) for station type".format(parts["mode"]))

    elif parts["type"] == "raw":
        if parts["mode"] == "burst":
            conf.plot_raw_data = True
        else:
            logging.error("Invalid mode ({}) for raw type".format(parts["mode"]))
    elif parts["type"] == "correlation":
        conf.plot_correlated_data = True
        conf.channels = int(parts["tile"])
        conf.tile_id = 0
    else:
        logging.error("Data type ({}) not supported.".format(parts["type"]))
        return False

    return True


def antenna_coordinates():
    """Reads antenna base locations from the Google Drive sheet
    :return: Re-mapped antenna locations
    """

    # Antenna mapping placeholder
    antenna_mapping = []
    for i in range(antennas_per_tile):
        antenna_mapping.append([[]] * antennas_per_tile)

    # Read antenna location spreadsheet
    response = urllib.request.urlopen(
        "https://docs.google.com/spreadsheets/d/e/2PACX-1vRIpaYPims9Qq9JEnZ3AfZtTaYJYWMsq2CWRgB-"
        "KKFAQOZoEsV0NV2Gmz1fDfOJm7cjDAEBQWM4FgyP/pub?gid=220529610&single=true&output=csv"
    )
    html = response.read().split("\n")

    # Two antennas are not in-place, however we still get an input into the TPM
    missing = 0

    # Read all antenna rows from spreadsheet response
    for i in range(1, nof_antennas + 1):
        items = html[i].split("\t")

        # Parse antenna row
        try:
            tpm, rx = int(items[7]) - 1, int(items[8]) - 1
            east, north, up = (
                float(items[15].replace(",", ".")),
                float(items[17].replace(",", ".")),
                0,
            )
        except:
            if missing == 0:
                tpm, rx = 0, 8
                east, north, up = 17.525, -1.123, 0
            else:
                tpm, rx = 10, 8
                east, north, up = 9.701, -14.627, 0
            missing += 1

        # Rotate the antenna and place in placeholder
        antenna_mapping[tpm][rx] = east, north, up

    # Create lookup table (uses preadu mapping)
    antenna_positions = np.zeros((nof_antennas, 3))
    for i in range(nof_antennas):
        tile_number = i // antennas_per_tile
        rx_number = antenna_rx_mapping[i % antennas_per_tile] - 1
        antenna_positions[i] = antenna_mapping[tile_number][rx_number]

    return antenna_positions


pol_names = ["X", "Y"]
