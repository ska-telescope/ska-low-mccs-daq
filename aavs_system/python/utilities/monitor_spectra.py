#! /usr/bin/python

from __future__ import division
from builtins import range
from past.utils import old_div
import matplotlib
matplotlib.use('Agg')

from matplotlib import pyplot as plt
from pydaq.persisters.channel import ChannelFormatFileManager
from pydaq.persisters import FileDAQModes
from pydaq import daq_receiver as receiver
from pyaavs import station
from time import sleep
from sys import stdout
import numpy as np
import datetime
import logging
import tempfile
import shutil
import errno
import time
import os

# Path to config file
config_file = "/home/aavs/aavs-access-layer/python/pyaavs/conifg/aavs1_full_station.yml"

# Ribbon color mapping
ribbon_color = {1: 'gray', 2: 'g', 3: 'r', 4: 'k',
                5: 'y', 6: 'm', 7: 'deeppink', 8: 'c',
                9: 'gray', 10: 'g', 11: 'r', 12: 'k',
                13: 'y', 14: 'm', 15: 'deeppink', 16: 'c'}

# Preadu mapping
preadu_position = {0: 'bottom', 1: 'top'}
preadu_mapping = {0: [0, 1, 2, 3, 8, 9, 10, 11],
                  1: [15, 14, 13, 12, 7, 6, 5, 4]}

fibre_preadu_mapping = {0: 1, 1: 2, 2: 3, 3: 4,
                        7: 13, 6: 14, 5: 15, 4: 16,
                        8: 5, 9: 6, 10: 7, 11: 8,
                        15: 9, 14: 10, 13: 11, 12: 12}

# Bitfile to use
bitfile = "/home/aavs/aavs-access-layer/bitfiles/itpm_v1_1_tpm_test_wrap_sbf236.bit"

# Plotting directory
plot_directory = "/home/aavs/Dropbox/AAVS_DATA/AAVS_Full_Station_Spectra"

# DAQ configuration
daq_config = {"nof_channel_samples": 4096,
              "receiver_interface": "eth3",
              "receiver_frame_size": 9000}

# Options to program and/or initialise TPM
program_tpm = False
initialise_tpm = False

# LMC IP to send control data to
lmc_ip = "10.0.10.200"

# Global variables for communication between controller and DAQ
data_processed = 0
data_directory = None

# Max power for bandass
max_power = 10 * np.log10(np.sqrt(127**2 + 127**2)**2)


def data_callback(data_type, filename, tile):
    """ Data callback to process data
    :param data_type: Type of data that was generated
    :param filename: Filename of data file where data was saved """

    global data_processed
    data_processed += 1


def generate_spectra(tile_id, tpm, rms):
    """ Generate spectra for current tile
    :param tile_id: Tile ID
    :param rms: Antenna RMS values"""

    # Read data
    channel_file_mgr = ChannelFormatFileManager(root_path=data_directory, daq_mode=FileDAQModes.Burst)
    data, timestamps = channel_file_mgr.read_data(timestamp=None,
                                                  tile_id=tile_id,
                                                  antennas=list(range(16)),
                                                  polarizations=list(range(2)),
                                                  channels=list(range(512)),
                                                  n_samples=daq_config['nof_channel_samples'])

    date_time = datetime.datetime.fromtimestamp(timestamps[0]).strftime("%y-%m-%d %H:%M:%S")

    # Process data
    data = np.abs((data['real'] + 1j * data['imag']).astype(np.complex64))**2
    data[np.where(data < 0.0000001)] = 0.00001
    data = 10 * np.log10(data)

    for pol in range(2):
        for preadu in list(preadu_mapping.keys()):
            plt.figure(figsize=(12, 8))
            plt.subplot(111)
            for ant in preadu_mapping[preadu]:
                pol_to_use = pol
                tpm_input = fibre_preadu_mapping[ant]

                plt.plot(np.arange(1, 512) * (400.0 / 512),
                         (old_div(np.sum(data[1:, ant, pol_to_use, :], axis=1), data.shape[3])) - max_power,
                         label="RX {0} = {1:.2f}".format(tpm_input, rms[ant * 2 + pol_to_use]),
                         color=ribbon_color[tpm_input],
                         linewidth=1)

            plt.xlim((0, 400))
#            plt.ylim((-60, 0))
            plt.title("{} - {} - {}".format(tpm, preadu_position[preadu], 'X' if pol == 0 else 'Y'))
            plt.xlabel("Frequency (MHz)")
            plt.ylabel("Power (dBm)")
            plt.text(315, -58, date_time, weight='bold', size='16')
            plt.legend(loc='lower center', prop={'size': 8})
            plt.minorticks_on()
            plt.grid(b=True, which='major', color='0.3', linestyle='-')
            plt.grid(b=True, which='minor', color='0.8', linestyle='--')
            plt.tight_layout()
            plt.savefig(os.path.join(plot_directory, "{}_{}_{}.png".format(tpm, preadu_position[preadu],
                                                                           'X' if pol == 0 else 'Y')), dpi=400)
            plt.close()


if __name__ == "__main__":

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    format = logging.Formatter("%(asctime)s - %(levelname)s - %(threadName)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(format)
    log.addHandler(ch)

    # Check if directory exists
    if not (os.path.exists(plot_directory) and os.path.isdir(plot_directory)):
        logging.error("Specified directory (%s) does not exist or is not a directory" % plot_directory)
        exit(0)

    # Create temporary directory to store DAQ generated files
    data_directory = tempfile.mkdtemp()
    daq_config['directory'] = data_directory
    logging.info("Using temporary directory {}".format(data_directory))

    try:
        # Create plot directory
        plot_directory = os.path.join(plot_directory, time.strftime("%Y_%m_%d"))
        try:
            os.mkdir(plot_directory)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(plot_directory):
                pass
            else:
                raise

        # Create station
        station_config = station.configuration
        station_config['station']['program'] = program_tpm
        station_config['station']['initialise'] = initialise_tpm

        station.load_configuration_file(station_config)
        aavs_station = station.Station(station.configuration)
        aavs_station.connect()

        # Start DAQ
        daq_config['nof_tiles'] = 16# len(tpms)
        receiver.populate_configuration(daq_config)
        receiver.initialise_daq()
        receiver.start_channel_data_consumer(callback=data_callback)

        sleep(1)

        # Now send channelised data
        station.send_channelised_data(daq_config['nof_channel_samples'])

        # Wait for data to be processed
        while data_processed < len(aavs_station.tiles):
            logging.info("Waiting for data")
            sleep(1)

        # Stop DAQ
        receiver.stop_daq()

        # Generate RMS power and spectra for all tiles in station
        for t in range(len(aavs_station.tiles)):
            logging.info("Processing {}".format(aavs_station.tiles[t]))
            generate_spectra(t, station_config['tiles'][t], station.tiles[t].get_adc_rms())

    # All done, remove temporary directory
    except Exception as e:
        logging.error(e)
    finally:
        shutil.rmtree(data_directory, ignore_errors=True)
