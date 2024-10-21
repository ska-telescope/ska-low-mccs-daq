#!/usr/bin/env python

from __future__ import absolute_import
from __future__ import division

import time
from builtins import input
import threading
import fcntl
import socket
import struct
import signal
from enum import IntEnum

import yaml

import numpy as np

from pyaavs.slack import get_slack_instance
from pydaq.interface import *
from pydaq.persisters import *
import pyaavs.logger


# Define consumer types enum
class DaqModes(IntEnum):
    """ Board State enumeration """
    RAW_DATA = 0
    CHANNEL_DATA = 1
    BEAM_DATA = 2
    CONTINUOUS_CHANNEL_DATA = 3
    INTEGRATED_BEAM_DATA = 4
    INTEGRATED_CHANNEL_DATA = 5
    STATION_BEAM_DATA = 6
    CORRELATOR_DATA = 7
    ANTENNA_BUFFER = 8
    RAW_STATION_BEAM = 10


# Global configuration dictionary
conf = {"nof_antennas": 16,
        "nof_channels": 512,
        "nof_beams": 1,
        "nof_polarisations": 2,
        "nof_tiles": 1,
        "nof_raw_samples": 32768,
        "raw_rms_threshold": -1,
        "nof_channel_samples": 1024,
        "nof_correlator_samples": 1835008,
        "nof_correlator_channels": 1,
        "continuous_period": 0,
        "nof_beam_samples": 42,
        "nof_beam_channels": 384,
        "nof_station_samples": 262144,
        "integrated_channel_bitwidth": 16,
        "continuous_channel_bitwidth": 16,
        "persist_all_buffers": True,
        "append_integrated": True,
        "tsamp": 1.1325,
        "sampling_rate": (800e6 / 2.0) * (32.0 / 27.0) / 512.0,
        "oversampling_factor": 32.0 / 27.0,
        "receiver_ports": "4660",
        "receiver_interface": "eth0",
        "receiver_ip": "",
        "receiver_frame_size": 8500,
        "receiver_frames_per_block": 32,
        "receiver_nof_blocks": 256,
        "directory": ".",
        "logging": True,
        "write_to_disk": True,
        "station_config": None,
        "max_filesize": None,
        "acquisition_duration": -1,
        "acquisition_start_time": -1,
        "station_beam_source": "",
        "station_beam_start_channel": 0,
        "station_beam_dada": False,
        "station_beam_individual_channels": False,
        "description": "",
        "daq_library": None,
        "observation_metadata": {}  # This is populated automatically
        }

# Global DAQ modes
modes = ["read_raw_data", "read_beam_data", "integrated_beam", "station_beam", "read_channel_data",
         "continuous_channel", "integrated_channel", "correlator", "antenna_buffer", "raw_station_beam"]

# Logging function
logging_function = None

# Global slack reference
slack = get_slack_instance("")


# -------------------------------------------------- HELPERS ---------------------------------------------
def get_ip_address(interface):
    """ Get the IP address of a specified interface """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x8915,  # SIOCGIFADDR
        struct.pack('256s', interface[:15])
    )[20:24]).encode()


def get_conf():
    """ Returns global configuration dictionary defaults """
    return conf


def logging_callback(level, message):
    """ Wrapper to logging function in DAQ """
    if level == LogLevel.Fatal.value:
        logging.fatal(message)
        exit()
    elif level == LogLevel.Error.value:
        logging.error(message)
        exit()
    elif level == LogLevel.Warning.value:
        logging.warning(message)
    elif level == LogLevel.Info.value:
        logging.info(message)
    elif level == LogLevel.Debug.value:
        logging.debug(message)


def get_numpy_from_ctypes(pointer, dtype, nof_values):
    """ Return a numpy object representing content in memory referenced by pointer """
    value_buffer = ctypes.c_char * np.dtype(dtype).itemsize * nof_values
    return np.frombuffer(value_buffer.from_address(ctypes.addressof(pointer.contents)), dtype)


# -------------------------------------------------- RAW DATA ---------------------------------------------


def raw_data_callback(data, timestamp, tile, arg2):
    """ Raw data callback
    :param data: Received data
    :param tile: The tile from which the data was acquired
    :param timestamp: Timestamp of first data point in data
    """

    if not conf['write_to_disk']:
        return

    # Extract data sent by DAQ
    nof_values = conf['nof_antennas'] * conf['nof_polarisations'] * conf['nof_raw_samples']
    values = get_numpy_from_ctypes(data, np.int8, nof_values)

    # If we have threshold enabled, then calculate RMS and only save if the threshold is not exceeded
    if conf['raw_rms_threshold'] > -1:
        # Note data is in antennas/samples/pols
        to_check = np.reshape(values.copy(), (conf['nof_antennas'], conf['nof_raw_samples'], conf['nof_polarisations']))
        to_check = to_check.astype(int)
        rms = np.sqrt(np.mean(to_check ** 2, axis=1)).flatten()
        if not any(rms > conf['raw_rms_threshold']):
            logging.info("RMS checking enabled, threshold not exceeded, not saving")
            return

    # Persist extracted data to file
    filename = persisters[DaqModes.RAW_DATA].ingest_data(data_ptr=values, timestamp=timestamp, tile_id=tile)

    # Call external callback if defined
    if external_callbacks[DaqModes.RAW_DATA] is not None:
        external_callbacks[DaqModes.RAW_DATA]("burst_raw", filename, tile)

    if conf['logging']:
        logging.info("Received raw data for tile {}".format(tile))


# ------------------------------------------------ CHANNEL DATA -------------------------------------------
# Ignore first dump of continuous data
cont_data_dumped = {}


def channel_data_callback(data, timestamp, tile, channel_id, mode='burst'):
    """ Channel data callback
    :param data: Received data
    :param timestamp: Timestamp of first data point in data
    :param mode: Mode in which data was received
    """

    global cont_data_dumped

    if not conf['write_to_disk']:
        return

    # Ignore first two buffers
    if mode == 'continuous' and not conf['persist_all_buffers']:
        if tile not in list(cont_data_dumped.keys()):
            cont_data_dumped[tile] = 1
            if tile == 0:
                logging.info("Ignoring first buffer of continuous channel data")
            return
        elif cont_data_dumped[tile] < 2:
            if tile == 0:
                logging.info("Ignoring additional buffer of continuous channel data")
            cont_data_dumped[tile] += 1
            return

    # Extract data sent by DAQ
    if mode == 'continuous':
        dtype = complex_8t if conf["continuous_channel_bitwidth"] == 16 else complex_16t
        values = get_numpy_from_ctypes(data, dtype,
                                       conf['nof_antennas'] * conf['nof_polarisations'] * conf['nof_channel_samples'])
    elif mode == 'integrated':
        dtype = np.uint16 if conf["integrated_channel_bitwidth"] == 16 else np.uint32
        values = get_numpy_from_ctypes(data, dtype,
                                       conf['nof_antennas'] * conf['nof_polarisations'] * conf['nof_channels'])
    else:
        values = get_numpy_from_ctypes(data, complex_8t,
                                       conf['nof_antennas'] * conf['nof_polarisations'] * \
                                       conf['nof_channel_samples'] * conf['nof_channels'])

    # Persist extracted data to file
    if mode == 'continuous':
        if DaqModes.CONTINUOUS_CHANNEL_DATA not in list(timestamps.keys()):
            timestamps[DaqModes.CONTINUOUS_CHANNEL_DATA] = timestamp

        if conf['continuous_period'] == 0:
            filename = persisters[DaqModes.CONTINUOUS_CHANNEL_DATA].ingest_data(append=True,
                                                                     data_ptr=values,
                                                                     timestamp=timestamps[
                                                                         DaqModes.CONTINUOUS_CHANNEL_DATA],
                                                                     sampling_time=sampling_time[
                                                                         DaqModes.CONTINUOUS_CHANNEL_DATA],
                                                                     buffer_timestamp=timestamp,
                                                                     channel_id=channel_id,
                                                                     tile_id=tile)
        else:
            filename = persisters[DaqModes.CONTINUOUS_CHANNEL_DATA].ingest_data(append=False,
                                                                     data_ptr=values,
                                                                     timestamp=timestamp,
                                                                     sampling_time=sampling_time[
                                                                         DaqModes.CONTINUOUS_CHANNEL_DATA],
                                                                     channel_id=channel_id,
                                                                     buffer_timestamp=timestamp, tile_id=tile)
        if conf['logging']:
            logging.info("Received continuous channel data for tile {} - channel {}".format(tile, channel_id))

        if external_callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA] is not None:
            external_callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA]("cont_channel", filename, tile)

    elif mode == 'integrated':
        if DaqModes.INTEGRATED_CHANNEL_DATA not in list(timestamps.keys()):
            timestamps[DaqModes.INTEGRATED_CHANNEL_DATA] = timestamp

        if conf['append_integrated']:
            filename = persisters[DaqModes.INTEGRATED_CHANNEL_DATA].ingest_data(append=True,
                                                                                data_ptr=values,
                                                                                timestamp=timestamps[
                                                                                    DaqModes.INTEGRATED_CHANNEL_DATA],
                                                                                sampling_time=sampling_time[
                                                                                    DaqModes.INTEGRATED_CHANNEL_DATA],
                                                                                buffer_timestamp=timestamp,
                                                                                tile_id=tile)
        else:
            filename = persisters[DaqModes.INTEGRATED_CHANNEL_DATA].ingest_data(append=False,
                                                                                data_ptr=values,
                                                                                timestamp=timestamp,
                                                                                sampling_time=sampling_time[
                                                                                    DaqModes.INTEGRATED_CHANNEL_DATA],
                                                                                buffer_timestamp=timestamp,
                                                                                tile_id=tile)

        if conf['logging']:
            logging.info("Received integrated channel data for tile {}".format(tile))

        if external_callbacks[DaqModes.INTEGRATED_CHANNEL_DATA] is not None:
            external_callbacks[DaqModes.INTEGRATED_CHANNEL_DATA]("integrated_channel", filename, tile)

    else:
        filename = persisters[DaqModes.CHANNEL_DATA].ingest_data(
            data_ptr=values,
            timestamp=timestamp, sampling_time=sampling_time[DaqModes.CHANNEL_DATA],
            tile_id=tile)
        if conf['logging']:
            logging.info("Received burst channel data for tile {}".format(tile))

        if external_callbacks[DaqModes.CHANNEL_DATA] is not None:
            external_callbacks[DaqModes.CHANNEL_DATA]("burst_channel", filename, tile)


def channel_burst_data_callback(data, timestamp, tile, _):
    """ Channel callback wrapper for burst data mode
    :param data: Received data
    :param tile: The tile from which the data was acquired
    :param timestamp: Timestamp of first data point in data
    """
    channel_data_callback(data, timestamp, tile, _)


def channel_continuous_data_callback(data, timestamp, tile, channel_id):
    """ Channel callback wrapper for continuous data mode
    :param data: Received data
    :param tile: The tile from which the data was acquired
    :param timestamp: Timestamp of first data point in data
    """
    channel_data_callback(data, timestamp, tile, channel_id, "continuous")


def channel_integrated_data_callback(data, timestamp, tile, _):
    """ Channel callback wrapper for integrated data mode
    :param data: Received data
    :param tile: The tile from which the data was acquired
    :param timestamp: Timestamp of first data point in data
    """
    channel_data_callback(data, timestamp, tile, _, "integrated")


# -------------------------------------------------- BEAM DATA --------------------------------------------


def beam_burst_data_callback(data, timestamp, tile, arg2):
    """ Beam callback wrapper for burst data mode
    :param data: Received data
    :param tile: The tile from which the data was acquired
    :param timestamp: Timestamp of first data point in data

    """

    if not conf['write_to_disk']:
        return

    # Extract data sent by DAQ
    values = get_numpy_from_ctypes(data, complex_16t, conf['nof_beams'] * conf['nof_polarisations'] * \
                                   conf['nof_beam_samples'] * conf['nof_beam_channels'])

    filename = persisters[DaqModes.BEAM_DATA].ingest_data(data_ptr=values,
                                                          timestamp=timestamp,
                                                          sampling_time=sampling_time[DaqModes.BEAM_DATA],
                                                          tile_id=tile)

    if conf['logging']:
        logging.info("Received beam data for tile {}".format(tile))

    if external_callbacks[DaqModes.BEAM_DATA] is not None:
        external_callbacks[DaqModes.BEAM_DATA]("burst_beam", filename, tile)


def beam_integrated_data_callback(data, timestamp, tile, arg2):
    """ Beam callback wrapper for integrated data mode
    :param data: Received data
    :param tile: The tile from which the data was acquired
    :param timestamp: Timestamp of first data point in data
    """

    if not conf['write_to_disk']:
        return

    # Extract data sent by DAQ
    values = get_numpy_from_ctypes(data, np.uint32, conf['nof_beams'] * conf['nof_polarisations'] * 384)

    # Re-arrange data
    values = np.reshape(values,
                        (conf['nof_beams'], conf['nof_polarisations'], 384))
    values = values.flatten()

    # Persist extracted data to file
    if DaqModes.INTEGRATED_BEAM_DATA not in list(timestamps.keys()):
        timestamps[DaqModes.INTEGRATED_BEAM_DATA] = timestamp

    filename = persisters[DaqModes.INTEGRATED_BEAM_DATA].ingest_data(append=conf['append_integrated'],
                                                                     data_ptr=values,
                                                                     timestamp=timestamps[
                                                                         DaqModes.INTEGRATED_BEAM_DATA],
                                                                     sampling_time=sampling_time[
                                                                         DaqModes.INTEGRATED_BEAM_DATA],
                                                                     buffer_timestamp=timestamp,
                                                                     tile_id=tile)

    if conf['logging']:
        logging.info("Received integrated beam data for tile {}".format(tile))

    if external_callbacks[DaqModes.INTEGRATED_BEAM_DATA] is not None:
        external_callbacks[DaqModes.INTEGRATED_BEAM_DATA]("integrated_beam", filename, tile)


# ----------------------------------------------- CORRELATOR DATA -----------------------------------------
def correlator_callback(data, timestamp, channel, arg2):
    """ Correlated data callback
    :param data: Received data
    :param timestamp: Timestamp of first sample in data """

    if not conf['write_to_disk']:
        return

    # if conf['nof_correlator_channels'] == 1:
    #     if channel not in list(cont_data_dumped.keys()):
    #         cont_data_dumped[channel] = 1
    #         logging.info("Ignoring first integration for channel {}".format(channel))
    #         return
    #     elif cont_data_dumped[channel] == 1:
    #         logging.info("Ignoring second integration for channel {}".format(channel))
    #         cont_data_dumped[channel] += 1
    #         return

    # Extract data sent by DAQ
    nof_antennas = conf['nof_tiles'] * conf['nof_antennas']
    nof_baselines = int((nof_antennas + 1) * 0.5 * nof_antennas)
    nof_stokes = conf['nof_polarisations'] * conf['nof_polarisations']
    nof_channels = 1

    values = get_numpy_from_ctypes(data, np.complex64, nof_channels * nof_baselines * nof_stokes)

    # The correlator reorders the matrix in lower triangular form, this needs to be converted
    # to upper triangular form to be compatible with the rest of the system
    data = np.reshape(np.conj(values), (nof_baselines, nof_stokes))
    grid = np.zeros((nof_antennas, nof_antennas, nof_stokes), dtype=np.complex64)

    counter = 0
    for i in range(nof_antennas):
        for j in range(i + 1):
            grid[j, i, :] = data[counter, :]
            counter += 1

    values = np.zeros(nof_baselines * nof_stokes, dtype=np.complex64)

    counter = 0
    for i in range(nof_antennas):
        for j in range(i, nof_antennas):
            values[counter * nof_stokes:(counter + 1) * nof_stokes] = grid[i, j, :]
            counter += 1

    # Persist extracted data to file
    if conf['nof_correlator_channels'] == 1:
        # Persist extracted data to file
        if DaqModes.CORRELATOR_DATA not in list(timestamps.keys()):
            timestamps[DaqModes.CORRELATOR_DATA] = timestamp

        filename = persisters[DaqModes.CORRELATOR_DATA].ingest_data(append=True,
                                                                    data_ptr=values,
                                                                    timestamp=timestamps[DaqModes.CORRELATOR_DATA],
                                                                    sampling_time=sampling_time[
                                                                        DaqModes.CORRELATOR_DATA],
                                                                    buffer_timestamp=timestamp,
                                                                    channel_id=channel)
    else:
        filename = persisters[DaqModes.CORRELATOR_DATA].ingest_data(append=False,
                                                                    data_ptr=values, timestamp=timestamp,
                                                                    sampling_time=sampling_time[
                                                                        DaqModes.CORRELATOR_DATA],
                                                                    channel_id=channel)

    if external_callbacks[DaqModes.CORRELATOR_DATA] is not None:
        external_callbacks[DaqModes.CORRELATOR_DATA]("correlator", filename)

    if conf['logging']:
        logging.info("Received correlated data for channel {}".format(channel))


# ----------------------------------------------- STATION DATA -----------------------------------------


def station_callback(data, timestamp, nof_packets, nof_saturations):
    """ Correlated data callback
    :param data: Received data
    :param timestamp: Timestamp of first sample in data """

    if not conf['write_to_disk']:
        return

    if 'station' not in list(cont_data_dumped.keys()):
        cont_data_dumped['station'] = 1
        logging.info("Ignoring first integration for station")
        return
    elif cont_data_dumped['station'] < 2:
        logging.info("Ignoring second integration for station")
        cont_data_dumped['station'] += 1
        return

    # Extract data sent by DAQ
    values = get_numpy_from_ctypes(data, np.double, conf['nof_beam_channels'] * conf['nof_polarisations'])

    # Persist extracted data to file
    if DaqModes.STATION_BEAM_DATA not in list(timestamps.keys()):
        timestamps[DaqModes.STATION_BEAM_DATA] = timestamp

    filename = persisters[DaqModes.STATION_BEAM_DATA].ingest_data(append=True,
                                                                  data_ptr=values,
                                                                  timestamp=timestamps[DaqModes.STATION_BEAM_DATA],
                                                                  sampling_time=sampling_time[
                                                                      DaqModes.STATION_BEAM_DATA],
                                                                  buffer_timestamp=timestamp,
                                                                  station_id=0,
                                                                  sample_packets=nof_packets)

    # Call external callback
    if external_callbacks[DaqModes.STATION_BEAM_DATA] is not None:
        external_callbacks[DaqModes.STATION_BEAM_DATA]("station", filename, nof_packets * 256)

    if conf['logging']:
        logging.info(
            "Received station beam data (nof saturations: {}, nof_packets: {})".format(nof_saturations, nof_packets))


def antenna_buffer_callback(data, timestamp, tile_id, _):
    """ Antenna buffer data callback
    :param data: Received data
    :param tile: The tile from which the data was acquired
    :param timestamp: Timestamp of first data point in data
    """

    # If writing to disk is not enabled, return immediately
    if not conf['write_to_disk']:
        return

    # Extract data sent by DAQ
    nof_values = conf['nof_antennas'] * conf['nof_polarisations'] * \
                 conf['nof_raw_samples']
    values = get_numpy_from_ctypes(data, np.int8, nof_values)

    # Persist extracted data to file
    if DaqModes.ANTENNA_BUFFER not in list(timestamps.keys()):
        timestamps[DaqModes.ANTENNA_BUFFER] = timestamp

    filename = persisters[DaqModes.ANTENNA_BUFFER].ingest_data(append=True,
                                                               data_ptr=values,
                                                               timestamp=timestamps[DaqModes.ANTENNA_BUFFER],
                                                               buffer_timestamp=timestamp,
                                                               tile_id=tile_id,
                                                               disable_per_sample_timestamp=True)

    # Call external callback if defined
    if external_callbacks[DaqModes.ANTENNA_BUFFER] is not None:
        external_callbacks[DaqModes.ANTENNA_BUFFER]("antenna_buffer", filename, tile_id)

    if conf['logging']:
        logging.info("Received antenna data for tile {}".format(tile_id))


# ------------------------------------ Start consumer functions ------------------------------------------

def start_raw_data_consumer(callback=None):
    """ Start raw data consumer
    :param callback: Caller callback
    :param metadata: Any observation metadata to be added to the generated data files
    """

    global callbacks
    global conf

    # Generate configuration for raw consumer
    params = {"nof_antennas": conf['nof_antennas'],
              "samples_per_buffer": conf['nof_raw_samples'],
              "nof_tiles": conf['nof_tiles'],
              "nof_pols": conf['nof_polarisations'],
              "max_packet_size": conf['receiver_frame_size']}

    # Start raw data consumer
    if start_consumer("rawdata", params, callbacks[DaqModes.RAW_DATA]) != Result.Success:
        if conf['logging']:
            logging.info("Failed to start raw data consumer")
        raise Exception("Failed to start raw data consumer")
    running_consumers[DaqModes.RAW_DATA] = True

    # Create data persister
    raw_file = RawFormatFileManager(root_path=conf['directory'],
                                    daq_mode=FileDAQModes.Burst,
                                    observation_metadata=conf['observation_metadata'])

    raw_file.set_metadata(n_antennas=conf['nof_antennas'],
                          n_pols=conf['nof_polarisations'],
                          n_samples=conf['nof_raw_samples'])
    persisters[DaqModes.RAW_DATA] = raw_file

    # Set external callback
    external_callbacks[DaqModes.RAW_DATA] = callback

    if conf['logging']:
        logging.info("Started raw data consumer")


def start_channel_data_consumer(callback=None):
    """ Start channel data consumer
        :param callback: Caller callback
        :param metadata: Any observation metadata to be added to the generated data files
    """

    global callbacks
    global conf

    # Generate configuration for raw consumer
    params = {"nof_channels": conf['nof_channels'],
              "nof_samples": conf['nof_channel_samples'],
              "nof_antennas": conf['nof_antennas'],
              "nof_tiles": conf['nof_tiles'],
              "nof_pols": conf['nof_polarisations'],
              "max_packet_size": conf['receiver_frame_size']}

    # Start channel data consumer
    if start_consumer("burstchannel", params, callbacks[DaqModes.CHANNEL_DATA]) != Result.Success:
        raise Exception("Failed to start channel data consumer")
    running_consumers[DaqModes.CHANNEL_DATA] = True

    # Create data persister
    channel_file = ChannelFormatFileManager(root_path=conf['directory'],
                                            daq_mode=FileDAQModes.Burst,
                                            observation_metadata=conf['observation_metadata'])

    channel_file.set_metadata(n_chans=conf['nof_channels'],
                              n_antennas=conf['nof_antennas'],
                              n_pols=conf['nof_polarisations'],
                              n_samples=conf['nof_channel_samples'])

    persisters[DaqModes.CHANNEL_DATA] = channel_file

    # Set sampling time
    sampling_time[DaqModes.CHANNEL_DATA] = 1.0 / conf['sampling_rate']

    # Set external callback
    external_callbacks[DaqModes.CHANNEL_DATA] = callback

    if conf['logging']:
        logging.info("Started channel data consumer")


def start_continuous_channel_data_consumer(callback=None):
    """ Start continuous channel data consumer
        :param callback: Caller callback
    """

    global callbacks
    global conf

    # Set sampling time
    sampling_time[DaqModes.CONTINUOUS_CHANNEL_DATA] = 1.0 / conf['sampling_rate']

    # Generate configuration for raw consumer
    params = {"nof_channels": 1,
              "nof_samples": conf['nof_channel_samples'],
              "nof_antennas": conf['nof_antennas'],
              "nof_tiles": conf['nof_tiles'],
              "nof_pols": conf['nof_polarisations'],
              "bitwidth": conf['continuous_channel_bitwidth'],
              "sampling_time": 1.0 / conf['sampling_rate'],
              "nof_buffer_skips": conf['continuous_period'] // (
                      sampling_time[DaqModes.CONTINUOUS_CHANNEL_DATA] * conf['nof_channel_samples']),
              "start_time": conf['acquisition_start_time'],
              "max_packet_size": conf['receiver_frame_size']}

    # Start channel data consumer
    if start_consumer("continuouschannel", params, callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA]) != Result.Success:
        raise Exception("Failed to start continuous channel data consumer")
    running_consumers[DaqModes.CONTINUOUS_CHANNEL_DATA] = True

    # Create data persister
    data_type = 'complex' if conf["continuous_channel_bitwidth"] == 16 else 'complex16'
    channel_file = ChannelFormatFileManager(root_path=conf['directory'],
                                            data_type=data_type,
                                            daq_mode=FileDAQModes.Continuous,
                                            observation_metadata=conf['observation_metadata'])
    channel_file.set_metadata(n_chans=1,
                              n_antennas=conf['nof_antennas'],
                              n_pols=conf['nof_polarisations'],
                              n_samples=conf['nof_channel_samples'])
    persisters[DaqModes.CONTINUOUS_CHANNEL_DATA] = channel_file

    # Set external callback
    external_callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA] = callback

    if conf['logging']:
        logging.info("Started continuous channel data consumer")


def start_integrated_channel_data_consumer(callback=None):
    """ Start integrated channel data consumer
        :param callback: Caller callback
        :param metadata: Any observation metadata to be added to the generated data files
    """

    global callbacks
    global conf

    # Generate configuration for raw consumer
    params = {"nof_channels": conf['nof_channels'],
              "nof_antennas": conf['nof_antennas'],
              "nof_tiles": conf['nof_tiles'],
              "nof_pols": conf['nof_polarisations'],
              "bitwidth": conf['integrated_channel_bitwidth'],
              "max_packet_size": conf['receiver_frame_size']}

    # Start channel data consumer
    if start_consumer("integratedchannel", params, callbacks[DaqModes.INTEGRATED_CHANNEL_DATA]) != Result.Success:
        raise Exception("Failed to start continuous channel data consumer")
    running_consumers[DaqModes.INTEGRATED_CHANNEL_DATA] = True

    # Create data persister
    data_type = 'uint16' if conf["integrated_channel_bitwidth"] == 16 else 'uint32'
    channel_file = ChannelFormatFileManager(root_path=conf['directory'],
                                            data_type=data_type,
                                            daq_mode=FileDAQModes.Integrated,
                                            observation_metadata=conf['observation_metadata'])
    channel_file.set_metadata(n_chans=conf['nof_channels'],
                              n_antennas=conf['nof_antennas'],
                              n_pols=conf['nof_polarisations'],
                              n_samples=1)
    persisters[DaqModes.INTEGRATED_CHANNEL_DATA] = channel_file

    # Set sampling time
    sampling_time[DaqModes.INTEGRATED_CHANNEL_DATA] = conf['tsamp']

    # Set external callback
    external_callbacks[DaqModes.INTEGRATED_CHANNEL_DATA] = callback

    if conf['logging']:
        logging.info("Started integrated channel data consumer")


def start_beam_data_consumer(callback=None):
    """ Start beam data consumer
        :param callback: Caller callback
        :param metadata: Any observation metadata to be added to the generated data files
    """

    global callbacks
    global conf

    # Generate configuration for raw consumer
    params = {"nof_channels": conf['nof_beam_channels'],
              "nof_samples": conf['nof_beam_samples'],
              "nof_tiles": conf['nof_tiles'],
              "nof_pols": conf['nof_polarisations'],
              "max_packet_size": conf['receiver_frame_size']}

    if start_consumer("burstbeam", params, callbacks[DaqModes.BEAM_DATA]) != Result.Success:
        raise Exception("Failed to start beam data consumer")

    running_consumers[DaqModes.BEAM_DATA] = True

    # Create data persister
    beam_file = BeamFormatFileManager(root_path=conf['directory'], data_type='complex16',
                                      daq_mode=FileDAQModes.Burst,
                                      observation_metadata=conf['observation_metadata'])

    beam_file.set_metadata(n_chans=conf['nof_beam_channels'],
                           n_pols=conf['nof_polarisations'],
                           n_samples=conf['nof_beam_samples'])
    persisters[DaqModes.BEAM_DATA] = beam_file

    # Set sampling time
    sampling_time[DaqModes.BEAM_DATA] = 1.0 / conf['sampling_rate']
    # Set external callback
    external_callbacks[DaqModes.BEAM_DATA] = callback

    if conf['logging']:
        logging.info("Started beam data consumer")


def start_integrated_beam_data_consumer(callback=None):
    """ Start integrated beam data consumer
        :param callback: Caller callback
        :param metadata: Any observation metadata to be added to the generated data files
    """

    global callbacks
    global conf

    # Generate configuration for raw consumer
    params = {"nof_channels": 384,
              "nof_samples": 1,
              "nof_tiles": conf['nof_tiles'],
              "nof_beams": conf['nof_beams'],
              "nof_pols": conf['nof_polarisations'],
              "max_packet_size": conf['receiver_frame_size']}

    if start_consumer("integratedbeam", params, callbacks[DaqModes.INTEGRATED_BEAM_DATA]) != Result.Success:
        raise Exception("Failed to start beam data consumer")
    running_consumers[DaqModes.INTEGRATED_BEAM_DATA] = True

    # Create data persister
    persisters[DaqModes.INTEGRATED_BEAM_DATA] = []
    beam_file = BeamFormatFileManager(root_path=conf['directory'],
                                      data_type='uint32',
                                      daq_mode=FileDAQModes.Integrated,
                                      observation_metadata=conf['observation_metadata'])

    beam_file.set_metadata(n_chans=384,
                           n_pols=conf['nof_polarisations'],
                           n_samples=1,
                           n_beams=conf['nof_beams'])

    persisters[DaqModes.INTEGRATED_BEAM_DATA] = beam_file

    # Set sampling time
    sampling_time[DaqModes.INTEGRATED_BEAM_DATA] = conf['tsamp']

    # Set external callback
    external_callbacks[DaqModes.INTEGRATED_BEAM_DATA] = callback

    if conf['logging']:
        logging.info("Started integrated beam data consumer")


def start_station_beam_data_consumer(callback=None):
    """ Start station beam data consumer
        :param callback: Caller callback
        :param metadata: Any observation metadata to be added to the generated data files
    """

    global callbacks
    global conf

    # Generate configuration for raw consumer
    params = {"nof_channels": conf['nof_beam_channels'],
              "nof_samples": conf['nof_station_samples'],
              "max_packet_size": conf['receiver_frame_size']}

    if start_consumer("stationdata", params, callbacks[DaqModes.STATION_BEAM_DATA]) != Result.Success:
        raise Exception("Failed to start station beam data consumer")
    running_consumers[DaqModes.STATION_BEAM_DATA] = True

    # Create data persister
    beam_file_mgr = StationBeamFormatFileManager(root_path=conf['directory'], data_type='double',
                                                 daq_mode=FileDAQModes.Integrated,
                                                 observation_metadata=conf['observation_metadata'])

    beam_file_mgr.set_metadata(n_chans=conf['nof_beam_channels'],
                               n_pols=conf['nof_polarisations'],
                               n_samples=1)
    persisters[DaqModes.STATION_BEAM_DATA] = beam_file_mgr

    # Set sampling time
    sampling_time[DaqModes.STATION_BEAM_DATA] = (1.0 / conf['sampling_rate']) * conf["nof_station_samples"]

    # Set external callback
    external_callbacks[DaqModes.STATION_BEAM_DATA] = callback

    if conf['logging']:
        logging.info("Started station beam data consumer")


def start_correlator(callback=None):
    """ Start correlator
        :param callback: Caller callback
        :param metadata: Any observation metadata to be added to the generated data files
    """

    global callbacks
    global conf

    # Generate configuration for raw consumer
    params = {"nof_channels": conf['nof_correlator_channels'],
              "nof_fine_channels": 1,
              "nof_samples": conf['nof_correlator_samples'],
              "nof_antennas": conf['nof_antennas'],
              "nof_tiles": conf['nof_tiles'],
              "nof_pols": conf['nof_polarisations'],
              "max_packet_size": conf['receiver_frame_size']}

    if start_consumer("correlator", params, callbacks[DaqModes.CORRELATOR_DATA]) != Result.Success:
        raise Exception("Failed to start correlator")
    running_consumers[DaqModes.CORRELATOR_DATA] = True

    # Create data persister
    corr_file = CorrelationFormatFileManager(root_path=conf['directory'],
                                             data_type="complex64",
                                             observation_metadata=conf['observation_metadata'])

    nof_baselines = int((conf['nof_tiles'] * conf['nof_antennas'] + 1) * 0.5 * conf['nof_tiles'] * conf['nof_antennas'])
    corr_file.set_metadata(n_chans=1,
                           n_pols=conf['nof_polarisations'],
                           n_samples=1,
                           n_antennas=conf['nof_tiles'] * conf['nof_antennas'],
                           n_stokes=conf['nof_polarisations'] * conf['nof_polarisations'],
                           n_baselines=nof_baselines)
    persisters[DaqModes.CORRELATOR_DATA] = corr_file

    # Set sampling time
    sampling_time[DaqModes.CORRELATOR_DATA] = conf['nof_correlator_samples'] / float(conf['sampling_rate'])

    # Set external callback
    external_callbacks[DaqModes.CORRELATOR_DATA] = callback

    if conf['logging']:
        logging.info("Started correlator")


def start_antenna_buffer_data_consumer(callback=None):
    """ Start antenna buffer data consumer
    :param callback: Caller callback
    :param metadata: Any observation metadata to be added to the generated data files
    """

    global callbacks
    global conf

    # Generate configuration for raw consumer
    params = {"nof_antennas": conf['nof_antennas'],
              "nof_samples": conf['nof_raw_samples'],
              "nof_tiles": conf['nof_tiles'],
              "max_packet_size": conf['receiver_frame_size']}

    # Start raw data consumer
    if start_consumer("antennabuffer", params, callbacks[DaqModes.ANTENNA_BUFFER]) != Result.Success:
        if conf['logging']:
            logging.info("Failed to start antenna buffer data consumer")
        raise Exception("Failed to start antenna buffer data consumer")
    running_consumers[DaqModes.ANTENNA_BUFFER] = True

    # Create data persister
    raw_file = RawFormatFileManager(root_path=conf['directory'],
                                    daq_mode=FileDAQModes.Burst,
                                    observation_metadata=conf['observation_metadata'])

    raw_file.set_metadata(n_antennas=conf['nof_antennas'],
                          n_pols=conf['nof_polarisations'],
                          n_samples=conf['nof_raw_samples'])
    persisters[DaqModes.ANTENNA_BUFFER] = raw_file

    # Set external callback
    external_callbacks[DaqModes.ANTENNA_BUFFER] = callback

    if conf['logging']:
        logging.info("Started antenna buffer consumer")


def start_station_beam_acquisition():
    """ Start station beam acquisition using acquire_station_beam interface """
    global conf

    duration = conf['acquisition_duration'] if conf['acquisition_duration'] > 0 else 60
    max_filesize = conf['max_filesize'] if conf['max_filesize'] is not None else 1

    # Generate configuration for raw consumer
    params = {"base_directory": conf['directory'],
              "max_file_size": max_filesize,
              "duration": duration,
              "nof_samples": conf['nof_station_samples'],
              "start_channel": conf['station_beam_start_channel'],
              "nof_channels": conf['nof_channels'],
              "interface": conf['receiver_interface'],
              "ip": conf['receiver_ip'].decode(),
              "dada": conf['station_beam_dada'],
              "individual": conf['station_beam_individual_channels'],
              "source": conf['station_beam_source'],
              "capture_time": conf['acquisition_start_time']}

    # Start capture
    if call_start_raw_station_acquisition(params) != Result.Success:
        if conf['logging']:
            logging.info("Failed to start raw station beam capture")
        raise Exception("Failed to start raw station beam capture")
    elif conf['logging']:
        logging.info("Started raw station beam capture")

    running_consumers[DaqModes.RAW_STATION_BEAM] = True


# ------------------------------------ Stop consumer functions ------------------------------------------


def stop_raw_data_consumer():
    """ Stop raw data consumer """
    external_callbacks[DaqModes.RAW_DATA] = None
    if stop_consumer("rawdata") != Result.Success:
        raise Exception("Failed to stop raw data consumer")
    running_consumers[DaqModes.RAW_DATA] = False

    if conf['logging']:
        logging.info("Stopped raw data consumer")


def stop_channel_data_consumer():
    """ Stop channel data consumer """
    external_callbacks[DaqModes.CHANNEL_DATA] = None
    if stop_consumer("burstchannel") != Result.Success:
        raise Exception("Failed to stop channel data consumer")
    running_consumers[DaqModes.CHANNEL_DATA] = False

    if conf['logging']:
        logging.info("Stopped channel data consumer")


def stop_continuous_channel_data_consumer():
    """ Stop continuous channel data consumer """
    external_callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA] = None
    if stop_consumer("continuouschannel") != Result.Success:
        raise Exception("Failed to stop continuous channel data consumer")
    running_consumers[DaqModes.CONTINUOUS_CHANNEL_DATA] = False

    if conf['logging']:
        logging.info("Stopped continuous channel data consumer")


def stop_integrated_channel_data_consumer():
    """ Stop integrated channel data consumer """
    external_callbacks[DaqModes.INTEGRATED_CHANNEL_DATA] = None
    if stop_consumer("integratedchannel") != Result.Success:
        raise Exception("Failed to stop integrated channel data consumer")
    running_consumers[DaqModes.INTEGRATED_CHANNEL_DATA] = False

    if conf['logging']:
        logging.info("Stopped integrated channel consumer")


def stop_beam_data_consumer():
    """ Stop beam data consumer """
    external_callbacks[DaqModes.BEAM_DATA] = None
    if stop_consumer("burstbeam") != Result.Success:
        raise Exception("Failed to stop beam data consumer")
    running_consumers[DaqModes.BEAM_DATA] = False

    if conf['logging']:
        logging.info("Stopped beam data consumer")


def stop_integrated_beam_data_consumer():
    """ Stop integrated beam data consumer """
    external_callbacks[DaqModes.INTEGRATED_BEAM_DATA] = None
    if stop_consumer("integratedbeam") != Result.Success:
        raise Exception("Failed to stop integrated beam data consumer")
    running_consumers[DaqModes.INTEGRATED_BEAM_DATA] = False

    if conf['logging']:
        logging.info("Stopped integrated beam data consumer")


def stop_station_beam_data_consumer():
    """ Stop beam data consumer """
    external_callbacks[DaqModes.STATION_BEAM_DATA] = None
    if stop_consumer("stationdata") != Result.Success:
        raise Exception("Failed to stop station beam data consumer")
    running_consumers[DaqModes.STATION_BEAM_DATA] = False

    if conf['logging']:
        logging.info("Stopped station beam data consumer")


def stop_correlator():
    """ Stop correlator consumer """
    external_callbacks[DaqModes.CORRELATOR_DATA] = None
    if stop_consumer("correlator") != Result.Success:
        raise Exception("Failed to stop correlator")
    running_consumers[DaqModes.CORRELATOR_DATA] = False

    if conf['logging']:
        logging.info("Stopped correlator")


def stop_antenna_buffer_data_consumer():
    """ Stop raw data consumer """
    external_callbacks[DaqModes.ANTENNA_BUFFER] = None
    if stop_consumer("antennabuffer") != Result.Success:
        raise Exception("Failed to stop antenna buffer data consumer")
    running_consumers[DaqModes.ANTENNA_BUFFER] = False

    if conf['logging']:
        logging.info("Stopped antenna buffer data consumer")


def stop_station_beam_acquisition():
    """ Stop acquisition of raw station beam"""
    if call_stop_raw_station_acquisition() != Result.Success:
        raise Exception("Failed to stop raw station beam acquisition")
    running_consumers[DaqModes.RAW_STATION_BEAM] = False

    if conf['logging']:
        logging.info("Stopped station beam capture")


# ------------------------------------------ Wrapper Functions Body ---------------------------------------


def populate_configuration(configuration):
    """ Populate configuration object
    :param configuration: Configuration parameters
    """

    global modes
    global conf

    # Check whether configuration object is a dictionary
    import optparse
    if configuration.__class__ == optparse.Values:
        configuration = vars(configuration)
    elif type(configuration) is not dict:
        raise Exception("Configuration parameters must be a dictionary")

    # Check if invalid parameters were passed in
    if len(set(configuration.keys()) - (set(conf.keys()).union(set(modes)))) != 0:
        if conf['logging']:
            logging.warning("Invalid configuration")
        raise Exception("Invalid configuration")

    # Check if data directory exists
    if not os.path.exists(configuration['directory']):
        if conf['logging']:
            logging.info("Specified data directory [%s] does not exist" % configuration['directory'])
        raise Exception("Specified data directory [%s] does not exist" % configuration['directory'])

    # Apply configuration
    for k, v in list(configuration.items()):
        conf[k] = v

    # Extract port string and create list of ports
    if type(conf['receiver_ports']) is not list:
        conf['receiver_ports'] = [int(x) for x in conf['receiver_ports'].split(',')]

    # Check if an IP address was provided, and if not get the assigned address to the interface
    if conf['receiver_ip'] == "":
        try:
            conf['receiver_ip'] = get_ip_address(conf['receiver_interface'].encode())
        except IOError as e:
            logging.error("Interface does not exist or could not get it's IP: {}".format(e))
            exit()

    # Get metadata
    metadata = {'software_version': get_software_version(),
                'description': conf['description']}
    if conf['station_config'] is not None:
        if os.path.exists(conf['station_config']) and os.path.isfile(conf['station_config']):
            metadata.update(get_station_information(conf['station_config']))
        else:
            logging.warning(
                "Provided station config file ({}) in invalid, ignoring.".format(conf['station_config']))

    # Set metadata
    conf['observation_metadata'] = metadata

    # CHeck if filesize restriction is set
    if conf['max_filesize'] is not None:
        AAVSFileManager.FILE_SIZE_GIGABYTES = conf['max_filesize']


def initialise_station_beam():
    """ Initialise the libraries for acquiring the raw station beam """

    # Initialise AAVS DAQ library
    if conf['logging']:
        logging.info("Initialising libraries")

    # Initialise the DAQ library
    initialise_library()

    # Initialise the station beam library
    initialise_station_beam_library()

    # Set logging callback
    call_attach_logger(logging_function)


def initialise_daq(filepath=None):
    """ Initialise DAQ library """

    # Remove any locks
    if conf['logging']:
        logging.info("Removing locks on files in output directory")
    os.system("rm -fr %s/*.lock" % conf['directory'])

    # Initialise AAVS DAQ library
    if conf['logging']:
        logging.info("Initialising library")

    # NOTE: Hardcoded case for 48-element stations in AAVS
    aavs_install_path = os.environ.get("AAVS_INSTALL_PATH", "/opt/aavs")
    if conf['nof_tiles'] == 3:
        initialise_library(f"{aavs_install_path}/lib/libaavsdaq48.so")
    else:
        initialise_library(filepath)

    # Set logging callback
    call_attach_logger(logging_function)

    # Start receiver
    if call_start_receiver(conf['receiver_interface'].encode(),
                           conf['receiver_ip'],
                           conf['receiver_frame_size'],
                           conf['receiver_frames_per_block'],
                           conf['receiver_nof_blocks']) != Result.Success.value:
        if conf['logging']:
            logging.info("Failed to start receiver with conf:")
            logging.info(str(conf))
            logging.info("Failed to start receiver")
        raise Exception("Failed to start receiver")

    # Set receiver ports
    for port in conf['receiver_ports']:
        if call_add_receiver_port(port) != Result.Success.value:
            if conf['logging']:
                logging.info("Failed to set receiver port %d" % port)
            raise Exception("Failed to set receiver port %d" % port)


def stop_daq():
    """ Stop DAQ """

    global cont_data_dumped
    global timestamps

    # If station beam is being acquired, stop it
    if running_consumers[DaqModes.RAW_STATION_BEAM]:
        stop_station_beam_acquisition()
        return

    # Clear timestamps
    timestamps = {}

    # Link stop consumer functions
    stop_functions = {DaqModes.RAW_DATA: stop_raw_data_consumer,
                      DaqModes.CHANNEL_DATA: stop_channel_data_consumer,
                      DaqModes.BEAM_DATA: stop_beam_data_consumer,
                      DaqModes.CONTINUOUS_CHANNEL_DATA: stop_continuous_channel_data_consumer,
                      DaqModes.INTEGRATED_BEAM_DATA: stop_integrated_beam_data_consumer,
                      DaqModes.INTEGRATED_CHANNEL_DATA: stop_integrated_channel_data_consumer,
                      DaqModes.STATION_BEAM_DATA: stop_station_beam_data_consumer,
                      DaqModes.CORRELATOR_DATA: stop_correlator,
                      DaqModes.ANTENNA_BUFFER: stop_antenna_buffer_data_consumer}

    # Stop all running consumers
    for key, running in list(running_consumers.items()):
        if running:
            stop_functions[key]()

    cont_data_dumped = {}

    # Stop DAQ receiver thread
    if call_stop_receiver() != Result.Success.value:
        raise Exception("Failed to stop receiver")
    elif conf['logging']:
        logging.info("Stopped DAQ")


def get_station_information(station_config):
    """ If a station configuration file is provided, connect to
        station and get required information """

    # Dictionary containing required metadata
    metadata = {'firmware_version': 0,
                'station_config': ""
                }

    # Grab file content as string and save it as metadata
    with open(station_config) as f:
        metadata['station_config'] = f.read()

    try:
        from pyaavs import station

        # Load station configuration file
        station.load_configuration_file(station_config)

        # Create station
        aavs_station = station.Station(station.configuration)
        aavs_station.connect()

        # Get firmware version
        metadata['firmware_version'] = aavs_station[0x0][0]
    except Exception as e:
        logging.warning("Could not get station information. Skipping. {}".format(e))

    return metadata


def get_software_version():
    """ Get current software version. This will get the latest git commit hash"""
    try:

        if "AAVS_SOFTWARE_DIRECTORY" not in os.environ:
            logging.error("AAVS_SOFTWARE_DIRECTORY not defined, cannot write software version")
            return 0x0

        path = os.path.expanduser(os.environ['AAVS_SOFTWARE_DIRECTORY'])

        import git
        repo = git.Repo(path)
        return repo.head.object.hexsha
    except Exception as e:
        logging.warning("Could not get software git hash. Skipping")
        return 0


# ----------------------------------------- Script Body ------------------------------------------------

# Signal handler for handling Ctrl-C
def _signal_handler(signum, frame):
    logging.info("Ctrl-C detected. Please press 'q' then Enter to quit")


# Callbacks
callbacks = {DaqModes.RAW_DATA: DATA_CALLBACK(raw_data_callback),
             DaqModes.CHANNEL_DATA: DATA_CALLBACK(channel_burst_data_callback),
             DaqModes.BEAM_DATA: DATA_CALLBACK(beam_burst_data_callback),
             DaqModes.CONTINUOUS_CHANNEL_DATA: DATA_CALLBACK(channel_continuous_data_callback),
             DaqModes.INTEGRATED_BEAM_DATA: DATA_CALLBACK(beam_integrated_data_callback),
             DaqModes.INTEGRATED_CHANNEL_DATA: DATA_CALLBACK(channel_integrated_data_callback),
             DaqModes.STATION_BEAM_DATA: DATA_CALLBACK(station_callback),
             DaqModes.CORRELATOR_DATA: DATA_CALLBACK(correlator_callback),
             DaqModes.ANTENNA_BUFFER: DATA_CALLBACK(antenna_buffer_callback)}

# Logging function
logging_function = LOGGER_CALLBACK(logging_callback)

# External callback
external_callbacks = {key: None for key in DaqModes}

# Running consumers
running_consumers = {key: False for key in DaqModes}

# Global HDF5 persisters handles
persisters = {}

# Global timestamp placeholders for append mode (otherwise we'd end up creating
# a different file per callback
timestamps = {}

# Sampling time for the different modes
sampling_time = {key: 0 for key in DaqModes}

# Script main entry point
if __name__ == "__main__":

    # Use OptionParse to get command-line arguments
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %aavs_daq_receiver [options]")

    parser.add_option("-a", "--nof_antennas", action="store", dest="nof_antennas",
                      type="int", default=16, help="Number of antennas [default: 16]")
    parser.add_option("-c", "--nof_channels", action="store", dest="nof_channels",
                      type="int", default=512, help="Number of channels [default: 512]")
    parser.add_option("-b", "--nof_beams", action="store", dest="nof_beams",
                      type="int", default=1, help="Number of beams [default: 1]")
    parser.add_option("-p", "--nof_pols", action="store", dest="nof_polarisations",
                      type="int", default=2, help="Number of polarisations [default: 2]")
    parser.add_option("-t", "--nof_tiles", action="store", dest="nof_tiles",
                      type="int", default=1, help="Number of tiles in the station [default: 1]")
    parser.add_option("", "--raw_samples", action="store", dest="nof_raw_samples",
                      type="int", default=32768, help="Number of raw antennas samples per buffer (requires "
                                                      "different firmware to change [default: 32768]")
    parser.add_option("", "--raw_rms_threshold", action="store", dest="raw_rms_threshold",
                      type="int", default=-1,
                      help="Only save raw data if RMS exceeds provided threshold [default: -1, do not threshold]")
    parser.add_option("", "--channel_samples", action="store", dest="nof_channel_samples",
                      type="int", default=1024, help="Number of channelised spectra per buffer [default: 1024]")
    parser.add_option("", "--correlator_samples", action="store", dest="nof_correlator_samples",
                      type="int", default=1835008,
                      help="Number of channel samples for correlation per buffer [default: 1835008]")
    parser.add_option("", "--beam_samples", action="store", dest="nof_beam_samples",
                      type="int", default=42, help="Number of beam samples per buffer (requires different firmware to "
                                                   "change [default: 42]")
    parser.add_option("", "--station_samples", action="store", dest="nof_station_samples",
                      type="int", default=262144, help="Number of station beam samples per buffer [default: 262144]")
    parser.add_option("", "--correlator-channels", action="store", dest="nof_correlator_channels",
                      type="int", default=1, help="Number of channels to channelise into before correlation. Only "
                                                  "used in correlator more [default: 1]")
    parser.add_option("", "--tsamp", action="store", dest="tsamp",
                      type="float", default=1.1325,
                      help="Sampling time in s (required for -I and -X) [default: 1.1325s]")
    parser.add_option("", "--sampling_rate", action="store", dest="sampling_rate",
                      type="float", default=(800e6 / 2.0) * (32.0 / 27.0) / 512.0,
                      help="FPGA sampling rate [default: {:,.2e}]".format((800e6 / 2.0) * (32.0 / 27.0) / 512.0))
    parser.add_option("", "--oversampling_factor", action="store", dest="oversampling_factor",
                      type="float", default=32.0 / 27.0,
                      help="Oversampling factor [default: 32/27]")
    parser.add_option("", "--continuous_period", action="store", dest="continuous_period",
                      type="int", default=0, help="Number of elapsed seconds between successive dumps of continuous "
                                                  "channel data [default: 0 (dump everything)")
    parser.add_option("", "--integrated_channel_bitwidth", action="store", dest="integrated_channel_bitwidth",
                      type=int, default=16, help="Bit width of integrated channel data")
    parser.add_option("", "--continuous_channel_bitwidth", action="store", dest="continuous_channel_bitwidth",
                      type=int, default=16, help="Bit width of continuous channel data")
    parser.add_option("", "--append_integrated", action="store_false", dest="append_integrated", default=True,
                      help="Append integrated data in the same file (default: True")
    parser.add_option("", "--persist_all_buffers", action="store_true", dest="persist_all_buffers", default=False,
                      help="Do not ignore the first 3 received buffers for continuous channel data. (default: False")
    parser.add_option("--raw_station_beam_start_channel", action="store", dest="station_beam_start_channel",
                      type=int, default=0, help="Start channel ID for raw station beam [default: 0]")
    parser.add_option("--raw_station_beam_source", dest="station_beam_source", action="store", default="",
                      help="Station beam observed source [default = \"\"]")

    # Receiver options
    parser.add_option("-P", "--receiver_ports", action="store", dest="receiver_ports",
                      default="4660", help="Comma seperated UDP ports to listen on [default: 4660,4661]")
    parser.add_option("-i", "--receiver_interface", action="store", dest="receiver_interface",
                      default="eth0", help="Receiver interface [default: eth0]")
    parser.add_option("", "--receiver-ip", action="store", dest="receiver_ip",
                      default="", help="IP to bind to in case of multiples virtual interfaces [default: automatic]")
    parser.add_option("", "--beam_channels", action="store", dest="nof_beam_channels",
                      type="int", default=384, help="Number of channels in beam data [default: 384]")
    parser.add_option("", "--receiver_frame_size", action="store", dest="receiver_frame_size",
                      type="int", default=9000, help="Receiver frame size [default: 9000]")
    parser.add_option("", "--receiver_frames_per_block", action="store", dest="receiver_frames_per_block",
                      type="int", default=32, help="Receiver frame size [default: 32]")
    parser.add_option("", "--receiver_nof_blocks", action="store", dest="receiver_nof_blocks",
                      type="int", default=256, help="Receiver frame size [default: 256]")

    # Operation modes
    parser.add_option("-R", "--read_raw_data", action="store_true", dest="read_raw_data",
                      default=False, help="Read raw data [default: False]")
    parser.add_option("-B", "--read_beam_data", action="store_true", dest="read_beam_data",
                      default=False, help="Read beam data [default: False]")
    parser.add_option("-I", "--read_integrated_beam_data", action="store_true", dest="integrated_beam",
                      default=False, help="Read integrated beam data [default: False]")
    parser.add_option("-S", "--read_station_beam_data", action="store_true", dest="station_beam",
                      default=False, help="Read station beam data [default: False]")
    parser.add_option("--read_raw_station_beam_data", action="store_true", dest="raw_station_beam",
                      default=False, help="Read raw station beam data, uses acquire_station_beam. This mode cannot"
                                          "be used with any other mode [default: False]")
    parser.add_option("-C", "--read_channel_data", action="store_true", dest="read_channel_data",
                      default=False, help="Read channelised data [default: False]")
    parser.add_option("-X", "--read_continuous_channel_data", action="store_true", dest="continuous_channel",
                      default=False, help="Read continuous channel data [default: False]")
    parser.add_option("-D", "--read_integrated_channel_data", action="store_true", dest="integrated_channel",
                      default=False, help="Read integrated channel data[default: False]")
    parser.add_option("-K", "--correlator", action="store_true", dest="correlator",
                      default=False, help="Perform correlator [default: False]")
    parser.add_option("-A", "--antenna_buffer", action="store_true", dest="antenna_buffer",
                      default=False, help="Read antenna buffer data [default:False")

    # Persister options
    parser.add_option("-d", "--data-directory", action="store", dest="directory",
                      default=".", help="Parent directory where data will be stored [default: current directory]")
    parser.add_option("--disable-writing-to-disk", action="store_false", dest="write_to_disk",
                      default=True, help="Write files to disk [default: Enabled]")
    parser.add_option("-m", "--max-filesize", "--max-filesize_gb", action="store", dest="max_filesize",
                      default=None,
                      help="Maximum file size in GB, set 0 to save each data set to a separate hdf5 file [default: 4 GB]",
                      type="float")
    parser.add_option("--store_as_dada", action="store_true", dest="station_beam_dada", default=False,
                      help="Save raw station beam data as dada files [default: False]")
    parser.add_option("--individual_station_channels", action="store_true",
                      dest="station_beam_individual_channels", default=False,
                      help="Store raw station beam channels individually [default: False]")
    parser.add_option("--disable-logging", action="store_false", dest="logging", default=True,
                      help="Disable logging [default: Enabled]")

    # Observation options
    parser.add_option("--daq_library", action="store", dest="daq_library", default=None,
                      help="Directly specify the AAVS DAQ library to use")
    parser.add_option("--description", action="store", dest="description", default="",
                      help="Observation description, stored in file metadata (default: "")")
    parser.add_option("--station-config", action="store", dest="station_config", default=None,
                      help="Station configuration file, to extract additional metadata (default: None)")
    parser.add_option("--acquisition_duration", "--runtime", "--duration", "--dt", action="store",
                      dest="acquisition_duration", default=-1,
                      help="Duration of data acquisition in seconds [default: %default]", type="int")
    parser.add_option("--acquisition_start_time", "--start_time", "--st", action="store",
                      dest="acquisition_start_time", default=-1,
                      help="Specify acquisition start time, only for continuous channelised data [default: %default]",
                      type="int")

    (config, args) = parser.parse_args(argv[1:])

    # Set current thread name
    threading.current_thread().name = "DAQ"

    if config.max_filesize is not None:
        AAVSFileManager.FILE_SIZE_GIGABYTES = config.max_filesize

    # Populate configuration
    populate_configuration(config)

    # If station configuration is defined, then we can push updates to slack
    station_name = ""
    if 'station_config' in conf['observation_metadata'].keys():
        with open(config.station_config, 'r') as f:
            c = yaml.load(f, Loader=yaml.FullLoader)
            station_name = c['station']['name']
    slack = get_slack_instance(station_name)

    # Check if any mode was chosen
    if not any([config.read_beam_data, config.read_channel_data, config.read_raw_data, config.correlator,
                config.continuous_channel, config.integrated_beam, config.integrated_channel,
                config.station_beam, config.antenna_buffer, config.raw_station_beam]):
        logging.error("No DAQ mode was set. Exiting")
        exit(0)

    # If reading raw station beam, no other modes can be selected
    if config.raw_station_beam and any([config.read_beam_data, config.read_channel_data, config.read_raw_data,
                                        config.correlator, config.continuous_channel, config.integrated_beam,
                                        config.integrated_channel, config.station_beam, config.antenna_buffer]):
        logging.error("Raw station beam mode has to be used in isolation")
        exit(0)

    # Push command to slack
    slack.info("DAQ running with command:\n {}".format(' '.join(argv)))

    # Initialise library
    if config.raw_station_beam:
        initialise_station_beam()
    else:
        initialise_daq(config.daq_library)

    # ------------------------------- Raw data consumer ------------------------------------------
    if config.read_raw_data:
        start_raw_data_consumer()

    if config.antenna_buffer:
        start_antenna_buffer_data_consumer()

    # ----------------------------- Channel data consumers ----------------------------------------
    # Running in integrated data mode
    if config.integrated_channel:
        start_integrated_channel_data_consumer()

    # Running in continuous channel mode
    if config.continuous_channel:
        start_continuous_channel_data_consumer()

    # Running in burst mode
    if config.read_channel_data:
        start_channel_data_consumer()

    # ------------------------------- Beam data consumers -----------------------------------------
    if config.read_beam_data:
        start_beam_data_consumer()

    if config.integrated_beam:
        start_integrated_beam_data_consumer()

    if config.station_beam:
        start_station_beam_data_consumer()

    # --------------------------------------- Correlator ------------------------------------------
    # Correlator mode
    if config.correlator:
        start_correlator()

    # --------------------------------------- Raw Station Beam ------------------------------------------
    if config.raw_station_beam:
        start_station_beam_acquisition()

    logging.info("Ready to receive data. Enter 'q' to quit")

    # Setup signal handler
    signal.signal(signal.SIGINT, _signal_handler)

    if config.acquisition_duration > 0:
        logging.info("Collecting data for {} seconds requested".format(config.acquisition_duration))
        time.sleep(config.acquisition_duration)
    else:
        # If acquisition time interval is not explicitly specified will wait for "quit" command from the command line
        # wait until "q" is input
        while input("").strip().upper() != "Q":
            pass

    # Stop all running consumers and DAQ
    stop_daq()

    slack.info("DAQ acquisition stopped")
