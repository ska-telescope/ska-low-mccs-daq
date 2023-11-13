#!/usr/bin/env python2
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt

from pydaq import daq_receiver as receiver
from datetime import datetime, timedelta
from pydaq.persisters import *
from pyaavs import station
from numpy import random
import numpy as np
import tempfile
import logging
import shutil
import time

# Script parameters
station_config_file = None
receiver_interface = None
initialise_tile = None
program_tile = None

# Test generator and beam parameters  
test_signal = 78.125e6  # Frequency channel 100
beam_start_frequency = 75e6
beam_bandwidth = 6.25e6
nof_samples = 524288

# Antenna delay parameters
antennas_per_tile = 16
masked_antennas = []

# Global variables populated by main
channelised_channel = None
beamformed_channel = None
nof_antennas = None
nof_channels = None

# Global variables to track callback
tiles_processed = None
buffers_processed = 0
data_ready = False
nof_buffers = 2


def channel_callback(data_type, filename, tile):
    """ Data callback to process data
    :param data_type: Type of data that was generated
    :param filename: Filename of data file where data was saved """

    global tiles_processed
    global data_ready
    
    if data_ready:
        return

    tiles_processed[tile] += 1
    if np.all(tiles_processed >= nof_buffers):
        data_ready = True
        
        
def station_callback(data_type, filename, samples):
    """ Data callback to process data
    :param data_type: Type of data that was generated
    :param filename: Filename of data file where data was saved """

    global buffers_processed
    global data_ready
    
    if data_ready:
        return

    buffers_processed += 1
    if nof_samples == samples:
        data_ready = True
       
       
def accurate_sleep(seconds):
    now = datetime.datetime.now()
    end = now + timedelta(seconds=seconds)
    while now < end:
        now = datetime.datetime.now()
        time.sleep(0.1)


def delete_files(directory):
    """ Delete all files in directory """
    for f in os.listdir(directory):
        os.remove(os.path.join(directory, f))


def normalize_complex_vector(vector):
    """ Normalise the complex coefficients to between 1 and -1 for both real and imaginary """
    
    normalised = np.zeros(vector.shape, dtype=np.complex64)
    
    max_val = 0.0   
    for p in range(vector.shape[0]):
        for a in range(nof_antennas):
            if abs(vector[p][a].real) > max_val:
                max_val = abs(vector[p][a].real)
            if abs(vector[p][a].imag) > max_val:
                max_val = abs(vector[p][a].imag)
                
    for p in range(vector.shape[0]):
        for a in range(nof_antennas):
            normalised[p, a] = vector[p][a] / max_val
     
    return normalised
    
    
def check_calibration(daq_config, coeffs):
    """ Plot effect of calibration coefficients on channelised data """
    # Read in generate data file
    channel_file_mgr = ChannelFormatFileManager(root_path=daq_config['directory'], 
                                                daq_mode=FileDAQModes.Continuous)                 
                                                
    data, _ = channel_file_mgr.read_data(timestamp=None, n_samples=daq_config['nof_channel_samples'])
    data = (data['real'] + 1j * data['imag']).astype(np.complex64)
   
    # Plot pre-calibration
    pre_cal = data.copy()
    pre_cal = pre_cal[0, :, 0, :64].T

    plt.plot(pre_cal.imag)
    plt.savefig("pre_calibration_imag.png", dpi=300)

    plt.plot(pre_cal.real)
    plt.savefig("pre_calibration_real.png", dpi=300)

    for i in range(nof_antennas):
        plt.plot((pre_cal[:, i].real**2 + pre_cal[:, i].imag**2) ** 0.5)
    plt.savefig("pre_calibration_power.png", dpi=300)
    
    # Plot post-calibration
    post_cal = data.copy()
    post_cal = post_cal[0, :, 0, :64].T * coeffs[0, :]

    plt.plot(post_cal.imag)
    plt.savefig("post_calibration_imag.png", dpi=300)

    plt.plot(post_cal.real)
    plt.savefig("post_calibration_real.png", dpi=300)

    for i in range(nof_antennas):
        plt.plot((post_cal[:, 1].real**2 + post_cal[:, 1].imag**2) ** 0.5)
    plt.savefig("post_calibration_power.png", dpi=300)
   

def calibrate(vis, nof_antennas):
    """ Calibrate visibilities. Vis should be [visibilities/pol], with visibilities being in 
        upper triangular form """

    # Initialise coefficients
    coefficients = np.ones((2, nof_antennas), dtype=np.complex64)

    # Determine antenna numbers pertaining to baselines
    baseline_mapping = np.zeros((vis.shape[0], 2))
    counter = 0
    for i in range(nof_antennas):
        for j in range(i, nof_antennas):
            baseline_mapping[counter, 0] = i
            baseline_mapping[counter, 1] = j
            counter += 1

    # Define reference antenna
    ref_antenna = 0

    for pol in range(vis.shape[1]):
        # Determine per baseline complex coefficient, assuming all baselines should have equal response
        with np.errstate(divide='ignore', invalid='ignore'):
            bas_coeffs = vis[ref_antenna, pol] / vis[:, pol]
 
        # Compute per antenna coefficients, with respect to reference antenna. Default is antenna 0
        selection = np.unique(np.where(baseline_mapping[:, :] == ref_antenna)[0])
        
        for i in range(nof_antennas):
            if i <= ref_antenna:
                coefficients[pol, i] = bas_coeffs[selection[i]]
            else:
                coefficients[pol, i] = np.conj(bas_coeffs[selection[i]])
        
        coefficients[pol, :] /= coefficients[pol, 0]
        
    # If any nans are present, leave signal as is
    coefficients[np.where(np.isnan(coefficients))] = 1+0j
    return coefficients
    
         
def correlate_data(daq_config, test_station):
    """ Grab channel data """
    global buffers_processed
    global data_ready
    global tiles_processed

    # Reset number of processed tiles
    tiles_processed = np.zeros(daq_config['nof_tiles'], dtype=int)
    
    # Stop any data transmission
    test_station.stop_data_transmission()
    accurate_sleep(1)
    
    # Start DAQ
    logging.info("Starting DAQ")
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_continuous_channel_data_consumer(channel_callback)
    
    # Wait for DAQ to initialise
    accurate_sleep(2)
    
    # Start sending data
    test_station.send_channelised_data_continuous(channelised_channel, daq_config['nof_channel_samples'])
    logging.info("Acquisition started")
        
    # Wait for observation to finish
    while not data_ready:
        accurate_sleep(0.1)
        
    # All done, instruct receiver to stop writing to disk
    receiver.WRITE_TO_DISK = False
    logging.info("Data acquired")
        
    # Stop DAQ
    try:
        receiver.stop_daq()
    except Exception as e:
        logging.error("Failed to stop DAQ cleanly: {}".format(e))
    
    # Stop data transmission and reset
    test_station.stop_data_transmission()
    tiles_processed = np.zeros(daq_config['nof_tiles'], dtype=int)
    buffers_processed = 0
    receiver.WRITE_TO_DISK = True
    data_ready = False

    # Create channel manager
    channel_file_mgr = ChannelFormatFileManager(root_path=daq_config['directory'], 
                                                daq_mode=FileDAQModes.Continuous)   

    # Read in generate data file, combinig data from multiple tiles
    data = np.zeros((1, daq_config['nof_tiles'] * antennas_per_tile, 2, daq_config['nof_channel_samples']), 
                     dtype=np.complex64)
                     
    for tile in range(daq_config['nof_tiles']):            
        read_data, _ = channel_file_mgr.read_data(timestamp=None, 
                                                  tile_id=tile,
                                                  n_samples=daq_config['nof_channel_samples'])
        
        read_data = (read_data['real'] + 1j * read_data['imag']).astype(np.complex64)
        data[:, tile * antennas_per_tile: (tile + 1) * antennas_per_tile, :, :] = read_data
    
    # Data is in chan/ants/pol/samples order. Correlate XX and XY (upper triangle)
    logging.info("Correlating data")
    nof_antennas = daq_config['nof_tiles'] * channel_file_mgr.n_antennas
    nof_baselines = int((nof_antennas + 1) * 0.5 * nof_antennas)
    output = np.zeros((nof_baselines, 2), dtype=np.complex64)
    
    baseline = 0
    for antenna1 in xrange(nof_antennas):
        for antenna2 in xrange(antenna1, nof_antennas):
            output[baseline, 0] = np.correlate(data[0, antenna1, 0, :], data[0, antenna2, 0, :])[0]
            output[baseline, 1] = np.correlate(data[0, antenna1, 1, :], data[0, antenna2, 1, :])[0]
            baseline += 1

    return output

        
def grab_data(daq_config):
    """ Grab channel data """
    global buffers_processed
    global data_ready
    
    # Start DAQ
    logging.info("Starting DAQ")
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_station_beam_data_consumer(station_callback)
        
    # Wait for observation to finish
    while not data_ready:
        accurate_sleep(0.1)
        
    # All done, instruct receiver to stop writing to disk
    logging.info("Station beam acquired")
        
    # Stop DAQ
    try:
        receiver.stop_daq()
    except Exception as e:
        logging.error("Failed to stop DAQ cleanly: {}".format(e))
    
    # Stop data transmission and reset
    data_ready = False
    
    # Read integrated station beam and return computed power
    station_file_mgr = StationBeamFormatFileManager(root_path=daq_config['directory'], daq_mode=FileDAQModes.Integrated)
    
    # Data is in pol/sample/channel order.
    data, _, _ = station_file_mgr.read_data(timestamp=None, n_samples=buffers_processed)
    beam_power = 20 * np.log10(data[:, -1, beamformed_channel])
    
    # Reset number of buffers processed
    buffers_processed = 0
    
    return beam_power
    

if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout
    
    parser = OptionParser(usage="usage: %test_antenna_delays [options]")
    parser.add_option("--config", action="store", dest="config",
                      type="str", default=None, help="Configuration file [default: None]")
    parser.add_option("-P", "--program", action="store_true", dest="program",
                      default=False, help="Program FPGAs [default: False]")
    parser.add_option("-I", "--initialise", action="store_true", dest="initialise",
                      default=False, help="Initialise TPM [default: False]")
    parser.add_option("-i", "--receiver_interface", action="store", dest="receiver_interface",
                      default="eth0", help="Receiver interface [default: eth0]")
    parser.add_option("-D", "--generate-plots", action="store_true", dest="generate_plots",
                      default=False, help="Generate diagnostic plots [default: False]")
    (opts, args) = parser.parse_args(argv[1:])
    
    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    line_format = logging.Formatter("%(asctime)s - %(levelname)s - %(threadName)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(line_format)
    log.addHandler(ch)
    
    # Check if a config file is specified
    if opts.config is None:
        logging.error("No station configuration file was defined. Exiting")
        exit()
    elif not os.path.exists(opts.config) or not os.path.isfile(opts.config):
        logging.error("Specified config file does not exist or is not a file. Exiting")
        exit()
        
    # Update global config
    station_config_file = opts.config
    receiver_interface = opts.receiver_interface
    initialise_tile = opts.initialise
    program_tile = opts.program
    
    # Load station configuration file
    station.load_configuration_file(station_config_file)
    
    # Override parameters
    station_config = station.configuration
    station_config['station']['program'] = program_tile
    station_config['station']['initialise'] = initialise_tile
    station_config['station']['channel_truncation'] = 5  # Increase channel truncation factor
    station_config['station']['start_beamformer'] = True
    
    # Define station beam parameters (using configuration for test pattern generator)
    station_config['observation']['start_frequency_channel'] = beam_start_frequency
    station_config['observation']['bandwidth'] = beam_bandwidth
    
    # Check number of antennas to delay
    nof_antennas = len(station_config['tiles']) * antennas_per_tile
    
    # Create station
    test_station = station.Station(station_config)
    
    # Initialise station
    test_station.connect()
    
    if not test_station.properly_formed_station:
        logging.error("Station not properly formed, exiting")
        exit()    
        
    # Configure and start test pattern generator
    test_station.test_generator_input_select(0xFFFFFFFF)
    test_station.test_generator_set_tone(0, frequency=test_signal, ampl=1.0)
    # test_station.test_generator_set_noise(ampl=0.5)

    # Update channel numbers for script
    channel_bandwidth = 400e6 / 512.0
    channelised_channel = int(test_signal / channel_bandwidth)
    beamformed_channel = int((test_signal - station_config['observation']['start_frequency_channel']) / channel_bandwidth)
    nof_channels = int(station_config['observation']['bandwidth'] / channel_bandwidth)
    
    # Generate DAQ configuration
    daq_config = {"nof_channels": 1,
                  "nof_tiles": len(test_station.tiles),
                  "nof_channel_samples": nof_samples,
                  "nof_beam_channels": nof_channels,
                  "nof_station_samples": nof_samples,
                  "receiver_interface": receiver_interface,
                  "receiver_frame_size": 9000}
     
    # Create temporary directory to store DAQ generated files
    data_directory = tempfile.mkdtemp()
    daq_config['directory'] = data_directory
    logging.info("Using temporary directory {}".format(data_directory))
    
    try:
        # Reset delays
        for tile in test_station.tiles:
            tile.test_generator[0].set_delay([0] * antennas_per_tile)
            tile.test_generator[1].set_delay([0] * antennas_per_tile)
        
        # Mask antennas if required
        zero_matrix = np.zeros((nof_channels, 4), dtype=np.complex64)
        one_matrix = np.ones((nof_channels, 4), dtype=np.complex64)
        one_matrix[:, 1] = one_matrix[:, 2] = 0

        for i, tile in enumerate(test_station.tiles):
            for antenna in range(antennas_per_tile):
                #if i * 16 + antenna in masked_antennas:
                #    tile.load_calibration_coefficients(antenna, zero_matrix.tolist())
                #else:
                tile.load_calibration_coefficients(antenna, one_matrix.tolist())
         
        # Done downloading coefficient, switch calibration bank 
        test_station.switch_calibration_banks(64)
        logging.info("Masked antennas")
        
        # Wait for a bit due to beamformer delay
        logging.info("Waiting for beamformer delay application due to beamformer latency")
        accurate_sleep(len(test_station.tiles))

        # Grab some data before applying delays
        logging.info("Checking beam power before delay application")
        power = grab_data(daq_config)
        logging.info("Beamformed channel power before delays: {}".format(str(power))) 
        delete_files(data_directory) 
        
        logging.info("Applying random antenna delays")
        
        # Generate random delays
        random.seed(0)  # Static seed so that each run generates the same random numbers
        random_delays = np.array(random.random(nof_antennas * 2) * (100 + 100) - 100, dtype=int)
        
        counter = 0
        for tile in test_station.tiles:
            delays = np.zeros(antennas_per_tile * 2, dtype=int)
            for i in range(antennas_per_tile):
                delays[i * 2] = random_delays[counter]
                delays[i * 2 + 1] = random_delays[counter + 1]
                counter += 2

            # Set delays
            tile.test_generator[0].set_delay(delays[:antennas_per_tile].tolist())
            tile.test_generator[1].set_delay(delays[antennas_per_tile:].tolist())
        
        # Delays applied, grab data      
        logging.info("Checking beam power after delay application")
        power = grab_data(daq_config)
        logging.info("Beamformed channel power after delays: {}".format(str(power)))
        delete_files(data_directory) 
        
        # Grab channelised data and calibrate
        logging.info("Grabbing data for correlation and correlating")
        visibilities = correlate_data(daq_config, test_station)
        
        # Calibrate
        logging.info("Calibrating tile")
        coeffs = calibrate(visibilities, nof_antennas)
        coeffs = normalize_complex_vector(coeffs)
        
        if opts.generate_plots:
            check_calibration(daq_config, coeffs)
        
        # Load calibration coefficients
        logging.info("Downloading calibration coefficients")
        for i, tile in enumerate(test_station.tiles):
            for antenna in range(antennas_per_tile):
                coeff_matrix = np.zeros((nof_channels, 4), dtype=np.complex64)
                # If an antenna is masked, leave 0s
                # if i * antennas_per_tile + antenna not in masked_antennas:
                coeff_matrix[beamformed_channel, 0] = coeffs[0, i * antennas_per_tile + antenna]
                coeff_matrix[beamformed_channel, 3] = coeffs[1, i * antennas_per_tile + antenna]
                tile.load_calibration_coefficients(antenna, coeff_matrix.tolist())
        
        # Done downloading coefficient, switch calibration bank
        test_station.switch_calibration_banks(64)
        logging.info("Switched calibration banks")
        accurate_sleep(1)
        
        logging.info("Checking beam power after calibration")
        power = grab_data(daq_config)
        logging.info("Beamformed channel power after calibration: {}".format(str(power)))
        delete_files(data_directory) 
        
        # All done, remove temporary directory
    except Exception as e:
        import traceback
        logging.error(traceback.format_exc())

    finally:
        shutil.rmtree(data_directory, ignore_errors=True)       
