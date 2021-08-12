import numpy as np
import threading
import fcntl
import socket
import struct
import signal
import yaml

from pyaavs.logger import root_logger as daq_logger
from pyaavs.slack import get_slack_instance
from pydaq.persisters import aavs_file
from pydaq.interface import *
from pydaq.persisters import *


# Define consumer type Enums
class DaqModes(Enum):
    """ Board State enumeration """
    RAW_DATA = 0
    CHANNEL_DATA = 1
    BEAM_DATA = 2
    CONTINUOUS_CHANNEL_DATA = 3
    INTEGRATED_BEAM_DATA = 4
    INTEGRATED_CHANNEL_DATA = 5
    STATION_BEAM_DATA = 6
    CORRELATOR_DATA = 7


# Custom numpy type for creating complex signed 8-bit data
complex_8t = np.dtype([('real', np.int8), ('imag', np.int8)])


class DaqReceiver:
    """ Class implementing interface to low-level data acquisition system """

    def __init__(self, use_slack=False):
        """ Class constructor """

        # Configuration directory containing defaults for all possible parameter
        # These parameters can be overridden
        self._config = {"nof_antennas": 16,
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
                        "nof_beam_samples": 32,
                        "nof_beam_channels": 384,
                        "nof_station_samples": 262144,
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
                        "description": "",
                        "observation_metadata": {}  # This is populated automatically
                        }

        # List of data callbacks
        self._callbacks = {DaqModes.RAW_DATA: DATA_CALLBACK(self._raw_data_callback),
                           DaqModes.CHANNEL_DATA: DATA_CALLBACK(self._channel_burst_data_callback),
                           DaqModes.BEAM_DATA: DATA_CALLBACK(self._beam_burst_data_callback),
                           DaqModes.CONTINUOUS_CHANNEL_DATA: DATA_CALLBACK(self._channel_continuous_data_callback),
                           DaqModes.INTEGRATED_BEAM_DATA: DATA_CALLBACK(self._beam_integrated_data_callback),
                           DaqModes.INTEGRATED_CHANNEL_DATA: DATA_CALLBACK(self._channel_integrated_data_callback),
                           DaqModes.STATION_BEAM_DATA: DATA_CALLBACK(self._station_callback),
                           DaqModes.CORRELATOR_DATA: DATA_CALLBACK(self._correlator_callback)}

        # List of external callback
        self._external_callbacks = {key: None for key in DaqModes}

        # List of data persisters
        self._persisters = {}

        # Timestamp placeholders for append mode (otherwise we'd end up creating
        # a different file per callback
        self._timestamps = {}

        # Sampling time for the different modes
        self._sampling_time = {key: 0 for key in DaqModes}

        # Pointer to logging function forwarded by low-level DAQ
        self._daq_logging_function = LOGGER_CALLBACK(self._logging_callback)

        # Keep track of which data consumers are running
        self._running_consumers = {}

        # Slack messenger
        self._slack = get_slack_instance("")

        # Placeholder for continuous and station data to skip first few buffers
        self._buffer_counter = {}

    # --------------------------------------- CONSUMERS --------------------------------------

    def _raw_data_callback(self, data, timestamp, tile, _):
        """ Raw data callback
        :param data: Received data
        :param tile: The tile from which the data was acquired
        :param timestamp: Timestamp of first data point in data
        """

        if not self._config['write_to_disk']:
            return

        # Extract data sent by DAQ
        nof_values = self._config['nof_antennas'] * self._config['nof_polarisations'] * self._config['nof_raw_samples']
        values = self._get_numpy_from_ctypes(data, np.int8, nof_values)

        # If we have threshold enabled, then calculate RMS and only save if the threshold is not exceeded
        if self._config['raw_rms_threshold'] > -1:
            # Note data is in antennas/samples/pols
            to_check = np.reshape(values.copy(),
                                  (self._config['nof_antennas'], self._config['nof_raw_samples'],
                                   self._config['nof_polarisations']))
            to_check = to_check.astype(np.int)
            rms = np.sqrt(np.mean(to_check ** 2, axis=1)).flatten()
            if not any(rms > self._config['raw_rms_threshold']):
                logging.info("RMS checking enabled, threshold not exceeded, not saving")
                return

        # Persist extracted data to file
        filename = self._persisters[DaqModes.RAW_DATA].ingest_data(data_ptr=values, timestamp=timestamp, tile_id=tile)

        # Call external callback if defined
        if self._external_callbacks[DaqModes.RAW_DATA] is not None:
            self._external_callbacks[DaqModes.RAW_DATA]("burst_raw", filename, tile)

        if self._config['logging']:
            logging.info("Received raw data for tile {}".format(tile))

    def _channel_data_callback(self, data, timestamp, tile, channel_id, mode='burst'):
        """ Channel data callback
        :param data: Received data
        :param timestamp: Timestamp of first data point in data
        :param tile: Tile number
        :param channel_id: Channel identifier
        :param mode: Channel transmission mode
        """
        if not self._config['write_to_disk']:
            return

        # Ignore first two buffers for continuous channel mode
        if mode == 'continuous':
            if tile not in list(self._buffer_counter.keys()):
                self._buffer_counter[tile] = 1
                if tile == 0:
                    logging.info("Ignoring first buffer of continuous channel data")
                return
            elif self._buffer_counter[tile] < 2:
                if tile == 0:
                    logging.info("Ignoring additional buffer of continuous channel data")
                self._buffer_counter[tile] += 1
                return

        # Extract data sent by DAQ
        if mode == 'continuous':
            values = self._get_numpy_from_ctypes(data, complex_8t,
                                                 self._config['nof_antennas'] * self._config['nof_polarisations'] *
                                                 self._config['nof_channel_samples'])
        elif mode == 'integrated':
            values = self._get_numpy_from_ctypes(data, np.uint16,
                                                 self._config['nof_antennas'] * self._config['nof_polarisations'] *
                                                 self._config['nof_channels'])
        else:
            values = self._get_numpy_from_ctypes(data, complex_8t,
                                                 self._config['nof_antennas'] * self._config['nof_polarisations'] * \
                                                 self._config['nof_channel_samples'] * self._config['nof_channels'])

        # Persist extracted data to file
        if mode == 'continuous':
            if DaqModes.CONTINUOUS_CHANNEL_DATA not in list(self._timestamps.keys()):
                self._timestamps[DaqModes.CONTINUOUS_CHANNEL_DATA] = timestamp

            persister = self._persisters[DaqModes.CHANNEL_DATA]

            if self._config['continuous_period'] == 0:
                filename = persister.ingest_data(append=True,
                                                 data_ptr=values,
                                                 timestamp=self._timestamps[DaqModes.CONTINUOUS_CHANNEL_DATA],
                                                 sampling_time=self._sampling_time[DaqModes.CONTINUOUS_CHANNEL_DATA],
                                                 buffer_timestamp=timestamp,
                                                 channel_id=channel_id,
                                                 tile_id=tile)
            else:
                filename = persister.ingest_data(append=False,
                                                 data_ptr=values,
                                                 timestamp=timestamp,
                                                 sampling_time=self._sampling_time[DaqModes.CONTINUOUS_CHANNEL_DATA],
                                                 channel_id=channel_id,
                                                 buffer_timestamp=timestamp,
                                                 tile_id=tile)
            if self._config['logging']:
                logging.info("Received continuous channel data for tile {} - channel {}".format(tile, channel_id))

            if self._external_callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA] is not None:
                self._external_callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA]("cont_channel", filename, tile)

        elif mode == 'integrated':
            if DaqModes.INTEGRATED_CHANNEL_DATA not in list(self._timestamps.keys()):
                self._timestamps[DaqModes.INTEGRATED_CHANNEL_DATA] = timestamp

            persister = self._persisters[DaqModes.INTEGRATED_CHANNEL_DATA]

            if self._config['append_integrated']:
                filename = persister.ingest_data(append=True,
                                                 data_ptr=values,
                                                 timestamp=self._timestamps[DaqModes.INTEGRATED_CHANNEL_DATA],
                                                 buffer_timestamp=timestamp,
                                                 tile_id=tile)
            else:
                filename = persister.ingest_data(append=False,
                                                 data_ptr=values,
                                                 timestamp=timestamp,
                                                 sampling_time=self._sampling_time[DaqModes.INTEGRATED_CHANNEL_DATA],
                                                 buffer_timestamp=timestamp,
                                                 tile_id=tile)

            if self._config['logging']:
                logging.info("Received integrated channel data for tile {}".format(tile))

            if self._external_callbacks[DaqModes.INTEGRATED_CHANNEL_DATA] is not None:
                self._external_callbacks[DaqModes.INTEGRATED_CHANNEL_DATA]("integrated_channel", filename, tile)

        else:
            persister = self._persisters[DaqModes.CHANNEL_DATA]
            filename = persister.ingest_data(data_ptr=values,
                                             timestamp=timestamp,
                                             sampling_time=self._sampling_time[DaqModes.CHANNEL_DATA],
                                             tile_id=tile)
            if self._config['logging']:
                logging.info("Received burst channel data for tile {}".format(tile))

            if self._external_callbacks[DaqModes.CHANNEL_DATA] is not None:
                self._external_callbacks[DaqModes.CHANNEL_DATA]("burst_channel", filename, tile)

    def _channel_burst_data_callback(self, data, timestamp, tile, _):
        """ Channel callback wrapper for burst data mode
        :param data: Received data
        :param timestamp: Timestamp of first data point in data
        :param tile: The tile from which the data was acquired
        """
        self._channel_data_callback(data, timestamp, tile, _)

    def _channel_continuous_data_callback(self, data, timestamp, tile, channel_id):
        """ Channel callback wrapper for continuous data mode
        :param data: Received data
        :param timestamp: Timestamp of first data point in data
        :param tile: The tile from which the data was acquired
        :param channel_id: Channel identifier
        """
        self._channel_data_callback(data, timestamp, tile, channel_id, "continuous")

    def _channel_integrated_data_callback(self, data, timestamp, tile, _):
        """ Channel callback wrapper for integrated data mode
        :param data: Received data
        :param timestamp: Timestamp of first data point in data
                :param tile: The tile from which the data was acquired
        """
        self._channel_data_callback(data, timestamp, tile, _, "integrated")

    def _beam_burst_data_callback(self, data, timestamp, tile, _):
        """ Beam callback wrapper for burst data mode
        :param data: Received data
        :param timestamp: Timestamp of first data point in data
        :param tile: The tile from which the data was acquired

        """

        if not self._config['write_to_disk']:
            return

        # Extract data sent by DAQ
        values = self._get_numpy_from_ctypes(data, complex_16t,
                                             self._config['nof_beams'] * self._config['nof_polarisations'] * \
                                             self._config['nof_beam_samples'] * self._config['nof_beam_channels'])

        persister = self._persisters[DaqModes.BEAM_DATA]
        filename = persister.ingest_data(data_ptr=values,
                                         timestamp=timestamp,
                                         sampling_time=self._sampling_time[DaqModes.BEAM_DATA],
                                         tile_id=tile)

        if self._config['logging']:
            logging.info("Received beam data for tile {}".format(tile))

        if self._external_callbacks[DaqModes.BEAM_DATA] is not None:
            self._external_callbacks[DaqModes.BEAM_DATA]("burst_beam", filename, tile)

    def _beam_integrated_data_callback(self, data, timestamp, tile, _):
        """ Beam callback wrapper for integrated data mode
        :param data: Received data
        :param tile: The tile from which the data was acquired
        :param timestamp: Timestamp of first data point in data
        """

        if not self._config['write_to_disk']:
            return

        # Extract data sent by DAQ
        values = self._get_numpy_from_ctypes(data, np.uint32,
                                             self._config['nof_beams'] * self._config['nof_polarisations'] * 384)

        # Re-arrange data
        values = np.reshape(values,
                            (self._config['nof_beams'], self._config['nof_polarisations'], 384))
        values = values.flatten()

        # Persist extracted data to file
        if DaqModes.INTEGRATED_BEAM_DATA not in list(self._timestamps.keys()):
            self._timestamps[DaqModes.INTEGRATED_BEAM_DATA] = timestamp

        persister = self._persisters[DaqModes.INTEGRATED_BEAM_DATA]
        filename = persister.ingest_data(append=self._config['append_integrated'],
                                         data_ptr=values,
                                         timestamp=self._timestamps[DaqModes.INTEGRATED_BEAM_DATA],
                                         sampling_time=self._sampling_time[DaqModes.INTEGRATED_BEAM_DATA],
                                         buffer_timestamp=timestamp,
                                         tile_id=tile)

        if self._config['logging']:
            logging.info("Received integrated beam data for tile {}".format(tile))

        if self._external_callbacks[DaqModes.INTEGRATED_BEAM_DATA] is not None:
            self._external_callbacks[DaqModes.INTEGRATED_BEAM_DATA]("integrated_beam", filename, tile)

    def _correlator_callback(self, data, timestamp, channel_id, _):
        """ Correlated data callback
        :param data: Received data
        :param timestamp: Timestamp of first sample in data
        :param channel_id: Channel identifier"""

        if not self._config['write_to_disk']:
            return

        # Extract data sent by DAQ
        nof_antennas = self._config['nof_tiles'] * self._config['nof_antennas']
        nof_baselines = int((nof_antennas + 1) * 0.5 * nof_antennas)
        nof_stokes = self._config['nof_polarisations'] * self._config['nof_polarisations']
        nof_channels = 1

        values = self._get_numpy_from_ctypes(data, np.complex64, nof_channels * nof_baselines * nof_stokes)

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
        persister = self._persisters[DaqModes.CORRELATOR_DATA]
        if self._config['nof_correlator_channels'] == 1:
            # Persist extracted data to file
            if DaqModes.CORRELATOR_DATA not in list(self._timestamps.keys()):
                self._timestamps[DaqModes.CORRELATOR_DATA] = timestamp

            filename = persister.ingest_data(append=True,
                                             data_ptr=values,
                                             timestamp=self._timestamps[DaqModes.CORRELATOR_DATA],
                                             sampling_time=self._sampling_time[DaqModes.CORRELATOR_DATA],
                                             buffer_timestamp=timestamp,
                                             channel_id=channel_id)
        else:
            filename = persister.ingest_data(append=False,
                                             data_ptr=values,
                                             timestamp=timestamp,
                                             sampling_time=self._sampling_time[DaqModes.CORRELATOR_DATA],
                                             channel_id=channel_id)

        if self._external_callbacks[DaqModes.CORRELATOR_DATA] is not None:
            self._external_callbacks[DaqModes.CORRELATOR_DATA]("correlator", filename)

        if self._config['logging']:
            logging.info("Received correlated data for channel {}".format(channel))

    def _station_callback(self, data, timestamp, nof_packets, nof_saturations):
        """ Correlated data callback
        :param data: Received data
        :param timestamp: Timestamp of first sample in data
        :param nof_packets: Number of packets received for this buffer
        :param nof_saturations: Number of saturated samples whilst acquiring buffer"""

        if not self._config['write_to_disk']:
            return

        if 'station' not in list(self._buffer_counter.keys()):
            self._buffer_counter['station'] = 1
            logging.info("Ignoring first integration for station")
            return
        elif self._buffer_counter['station'] < 2:
            logging.info("Ignoring second integration for station")
            self._buffer_counter['station'] += 1
            return

        # Extract data sent by DAQ
        values = self._get_numpy_from_ctypes(data, np.double,
                                             self._config['nof_beam_channels'] * self._config['nof_polarisations'])

        # Persist extracted data to file
        if DaqModes.STATION_BEAM_DATA not in list(self._timestamps.keys()):
            self._timestamps[DaqModes.STATION_BEAM_DATA] = timestamp

        persister = self._persisters[DaqModes.STATION_BEAM_DATA]
        filename = persister.ingest_data(append=True,
                                         data_ptr=values,
                                         timestamp=self._timestamps[DaqModes.STATION_BEAM_DATA],
                                         sampling_time=self._sampling_time[DaqModes.STATION_BEAM_DATA],
                                         buffer_timestamp=timestamp,
                                         station_id=0,   # TODO: Get station ID from station config, if possible
                                         sample_packets=nof_packets)

        # Call external callback
        if self._external_callbacks[DaqModes.STATION_BEAM_DATA] is not None:
            self._external_callbacks[DaqModes.STATION_BEAM_DATA]("station", filename, nof_packets * 256)

        if self._config['logging']:
            logging.info(
                "Received station beam data (nof saturations: {}, nof_packets: {})".format(nof_saturations,
                                                                                           nof_packets))

    def _start_raw_data_consumer(self, callback=None):
        """ Start raw data consumer
        :param callback: Caller callback """

        # Generate configuration for raw consumer
        params = {"nof_antennas": self._config['nof_antennas'],
                  "samples_per_buffer": self._config['nof_raw_samples'],
                  "nof_tiles": self._config['nof_tiles'],
                  "nof_pols": self._config['nof_polarisations'],
                  "max_packet_size": self._config['receiver_frame_size']}

        # Start raw data consumer
        if start_consumer("rawdata", params, self._callbacks[DaqModes.RAW_DATA]) != Result.Success:
            logging.info("Failed to start raw data consumer")
            raise Exception("Failed to start raw data consumer")
        self._running_consumers[DaqModes.RAW_DATA] = True

        # Create data persister
        raw_file = RawFormatFileManager(root_path=self._config['directory'],
                                        daq_mode=FileDAQModes.Burst,
                                        observation_metadata=self._config['observation_metadata'])

        raw_file.set_metadata(n_antennas=self._config['nof_antennas'],
                              n_pols=self._config['nof_polarisations'],
                              n_samples=self._config['nof_raw_samples'])
        self._persisters[DaqModes.RAW_DATA] = raw_file

        # Set external callback
        self._external_callbacks[DaqModes.RAW_DATA] = callback

        logging.info("Started raw data consumer")

    def _start_channel_data_consumer(self, callback=None):
        """ Start channel data consumer
            :param callback: Caller callback
        """

        # Generate configuration for raw consumer
        params = {"nof_channels": self._config['nof_channels'],
                  "nof_samples": self._config['nof_channel_samples'],
                  "nof_antennas": self._config['nof_antennas'],
                  "nof_tiles": self._config['nof_tiles'],
                  "nof_pols": self._config['nof_polarisations'],
                  "max_packet_size": self._config['receiver_frame_size']}

        # Start channel data consumer
        if start_consumer("burstchannel", params, self._callbacks[DaqModes.CHANNEL_DATA]) != Result.Success:
            raise Exception("Failed to start channel data consumer")
        self._running_consumers[DaqModes.CHANNEL_DATA] = True

        # Create data persister
        channel_file = ChannelFormatFileManager(root_path=self._config['directory'],
                                                daq_mode=FileDAQModes.Burst,
                                                observation_metadata=self._config['observation_metadata'])

        channel_file.set_metadata(n_chans=self._config['nof_channels'],
                                  n_antennas=self._config['nof_antennas'],
                                  n_pols=self._config['nof_polarisations'],
                                  n_samples=self._config['nof_channel_samples'])

        self._persisters[DaqModes.CHANNEL_DATA] = channel_file

        # Set sampling time
        self._sampling_time[DaqModes.CHANNEL_DATA] = 1.0 / self._config['sampling_rate']

        # Set external callback
        self._external_callbacks[DaqModes.CHANNEL_DATA] = callback

        if self._config['logging']:
            logging.info("Started channel data consumer")

    def _start_continuous_channel_data_consumer(self, callback=None):
        """ Start continuous channel data consumer
            :param callback: Caller callback
        """

        # Set sampling time
        self._sampling_time[DaqModes.CONTINUOUS_CHANNEL_DATA] = 1.0 / self._config['sampling_rate']

        # Generate configuration for raw consumer
        params = {"nof_channels": 1,
                  "nof_samples": self._config['nof_channel_samples'],
                  "nof_antennas": self._config['nof_antennas'],
                  "nof_tiles": self._config['nof_tiles'],
                  "nof_pols": self._config['nof_polarisations'],
                  "nof_buffer_skips": int(self._config['continuous_period'] // (
                          self._sampling_time[DaqModes.CONTINUOUS_CHANNEL_DATA] * self._config['nof_channel_samples'])),
                  "max_packet_size": self._config['receiver_frame_size']}

        # Start channel data consumer
        if start_consumer("continuouschannel", params,
                          self._callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA]) != Result.Success:
            raise Exception("Failed to start continuous channel data consumer")
        self._running_consumers[DaqModes.CONTINUOUS_CHANNEL_DATA] = True

        # Create data persister
        channel_file = ChannelFormatFileManager(root_path=self._config['directory'],
                                                daq_mode=FileDAQModes.Continuous,
                                                observation_metadata=self._config['observation_metadata'])
        channel_file.set_metadata(n_chans=1,
                                  n_antennas=self._config['nof_antennas'],
                                  n_pols=self._config['nof_polarisations'],
                                  n_samples=self._config['nof_channel_samples'])
        self._persisters[DaqModes.CHANNEL_DATA] = channel_file

        # Set external callback
        self._external_callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA] = callback

        logging.info("Started continuous channel data consumer")

    def _start_integrated_channel_data_consumer(self, callback=None):
        """ Start integrated channel data consumer
            :param callback: Caller callback
        """

        # Generate configuration for raw consumer
        params = {"nof_channels": self._config['nof_channels'],
                  "nof_antennas": self._config['nof_antennas'],
                  "nof_tiles": self._config['nof_tiles'],
                  "nof_pols": self._config['nof_polarisations'],
                  "max_packet_size": self._config['receiver_frame_size']}

        # Start channel data consumer
        if start_consumer("integratedchannel", params,
                          self._callbacks[DaqModes.INTEGRATED_CHANNEL_DATA]) != Result.Success:
            raise Exception("Failed to start continuous channel data consumer")
        self._running_consumers[DaqModes.INTEGRATED_CHANNEL_DATA] = True

        # Create data persister
        channel_file = ChannelFormatFileManager(root_path=self._config['directory'], data_type='uint16',
                                                daq_mode=FileDAQModes.Integrated,
                                                observation_metadata=self._config['observation_metadata'])
        channel_file.set_metadata(n_chans=self._config['nof_channels'],
                                  n_antennas=self._config['nof_antennas'],
                                  n_pols=self._config['nof_polarisations'],
                                  n_samples=1)
        self._persisters[DaqModes.INTEGRATED_CHANNEL_DATA] = channel_file

        # Set sampling time
        self._sampling_time[DaqModes.INTEGRATED_CHANNEL_DATA] = self._config['tsamp']

        # Set external callback
        self._external_callbacks[DaqModes.INTEGRATED_CHANNEL_DATA] = callback

        logging.info("Started integrated channel data consumer")

    def _start_beam_data_consumer(self, callback=None):
        """ Start beam data consumer
            :param callback: Caller callback
        """

        # Generate configuration for raw consumer
        params = {"nof_channels": self._config['nof_beam_channels'],
                  "nof_samples": self._config['nof_beam_samples'],
                  "nof_tiles": self._config['nof_tiles'],
                  "nof_pols": self._config['nof_polarisations'],
                  "max_packet_size": self._config['receiver_frame_size']}

        if start_consumer("burstbeam", params, self._callbacks[DaqModes.BEAM_DATA]) != Result.Success:
            raise Exception("Failed to start beam data consumer")

        self._running_consumers[DaqModes.BEAM_DATA] = True

        # Create data persister
        beam_file = BeamFormatFileManager(root_path=self._config['directory'], data_type='complex16',
                                          daq_mode=FileDAQModes.Burst,
                                          observation_metadata=self._config['observation_metadata'])

        beam_file.set_metadata(n_chans=self._config['nof_beam_channels'],
                               n_pols=self._config['nof_polarisations'],
                               n_samples=self._config['nof_beam_samples'])
        self._persisters[DaqModes.BEAM_DATA] = beam_file

        # Set sampling time
        self._sampling_time[DaqModes.BEAM_DATA] = 1.0 / self._config['sampling_rate']

        # Set external callback
        self._external_callbacks[DaqModes.BEAM_DATA] = callback

        logging.info("Started beam data consumer")

    def _start_integrated_beam_data_consumer(self, callback=None):
        """ Start integrated beam data consumer
            :param callback: Caller callback
        """

        # Generate configuration for raw consumer
        params = {"nof_channels": 384,
                  "nof_samples": 1,
                  "nof_tiles": self._config['nof_tiles'],
                  "nof_beams": self._config['nof_beams'],
                  "nof_pols": self._config['nof_polarisations'],
                  "max_packet_size": self._config['receiver_frame_size']}

        if start_consumer("integratedbeam", params, self._callbacks[DaqModes.INTEGRATED_BEAM_DATA]) != Result.Success:
            raise Exception("Failed to start beam data consumer")
        self._running_consumers[DaqModes.INTEGRATED_BEAM_DATA] = True

        # Create data persister
        self._persisters[DaqModes.INTEGRATED_BEAM_DATA] = []
        beam_file = BeamFormatFileManager(root_path=self._config['directory'],
                                          data_type='uint32',
                                          daq_mode=FileDAQModes.Integrated,
                                          observation_metadata=self._config['observation_metadata'])

        beam_file.set_metadata(n_chans=384,
                               n_pols=self._config['nof_polarisations'],
                               n_samples=1,
                               n_beams=self._config['nof_beams'])

        self._persisters[DaqModes.INTEGRATED_BEAM_DATA] = beam_file

        # Set sampling time
        self._sampling_time[DaqModes.INTEGRATED_BEAM_DATA] = self._config['tsamp']

        # Set external callback
        self._external_callbacks[DaqModes.INTEGRATED_BEAM_DATA] = callback

        logging.info("Started integrated beam data consumer")

    def _start_station_beam_data_consumer(self, callback=None):
        """ Start station beam data consumer
            :param callback: Caller callback
        """

        # Generate configuration for raw consumer
        params = {"nof_channels": self._config['nof_beam_channels'],
                  "nof_samples": self._config['nof_station_samples'],
                  "max_packet_size": self._config['receiver_frame_size']}

        if start_consumer("stationdata", params, self._callbacks[DaqModes.STATION_BEAM_DATA]) != Result.Success:
            raise Exception("Failed to start station beam data consumer")
        self._running_consumers[DaqModes.STATION_BEAM_DATA] = True

        # Create data persister
        beam_file_mgr = StationBeamFormatFileManager(root_path=self._config['directory'], data_type='double',
                                                     daq_mode=FileDAQModes.Integrated,
                                                     observation_metadata=self._config['observation_metadata'])

        beam_file_mgr.set_metadata(n_chans=self._config['nof_beam_channels'],
                                   n_pols=self._config['nof_polarisations'],
                                   n_samples=1)
        self._persisters[DaqModes.STATION_BEAM_DATA] = beam_file_mgr

        # Set sampling time
        self._sampling_time[DaqModes.STATION_BEAM_DATA] = (1.0 / self._config['sampling_rate']) * self._config[
            "nof_station_samples"]

        # Set external callback
        self._external_callbacks[DaqModes.STATION_BEAM_DATA] = callback

        logging.info("Started station beam data consumer")

    def _start_correlator(self, callback=None):
        """ Start correlator
            :param callback: Caller callback
        """

        # Generate configuration for raw consumer
        params = {"nof_channels": self._config['nof_correlator_channels'],
                  "nof_fine_channels": 1,
                  "nof_samples": self._config['nof_correlator_samples'],
                  "nof_antennas": self._config['nof_antennas'],
                  "nof_tiles": self._config['nof_tiles'],
                  "nof_pols": self._config['nof_polarisations'],
                  "max_packet_size": self._config['receiver_frame_size']}

        if start_consumer("correlator", params, self._callbacks[DaqModes.CORRELATOR_DATA]) != Result.Success:
            raise Exception("Failed to start correlator")
        self._running_consumers[DaqModes.CORRELATOR_DATA] = True

        # Create data persister
        corr_file = CorrelationFormatFileManager(root_path=self._config['directory'],
                                                 data_type="complex64",
                                                 observation_metadata=self._config['observation_metadata'])

        nof_baselines = int((self._config['nof_tiles'] * self._config['nof_antennas'] + 1) *
                            0.5 * self._config['nof_tiles'] * self._config['nof_antennas'])

        corr_file.set_metadata(n_chans=1,
                               n_pols=self._config['nof_polarisations'],
                               n_samples=1,
                               n_antennas=self._config['nof_tiles'] * self._config['nof_antennas'],
                               n_stokes=self._config['nof_polarisations'] * self._config['nof_polarisations'],
                               n_baselines=nof_baselines)
        self._persisters[DaqModes.CORRELATOR_DATA] = corr_file

        # Set sampling time
        self._sampling_time[DaqModes.CORRELATOR_DATA] = self._config['nof_correlator_samples'] / \
                                                        float(self._config['sampling_rate'])

        # Set external callback
        self._external_callbacks[DaqModes.CORRELATOR_DATA] = callback

        logging.info("Started correlator")

    def _stop_raw_data_consumer(self):
        """ Stop raw data consumer """
        self._external_callbacks[DaqModes.RAW_DATA] = None
        if stop_consumer("rawdata") != Result.Success:
            raise Exception("Failed to stop raw data consumer")
        self._running_consumers[DaqModes.RAW_DATA] = False

        logging.info("Stopped raw data consumer")

    def _stop_channel_data_consumer(self):
        """ Stop channel data consumer """
        self._external_callbacks[DaqModes.CHANNEL_DATA] = None
        if stop_consumer("burstchannel") != Result.Success:
            raise Exception("Failed to stop channel data consumer")
        self._running_consumers[DaqModes.CHANNEL_DATA] = False

        logging.info("Stopped channel data consumer")

    def _stop_continuous_channel_data_consumer(self):
        """ Stop continuous channel data consumer """
        self._external_callbacks[DaqModes.CONTINUOUS_CHANNEL_DATA] = None
        if stop_consumer("continuouschannel") != Result.Success:
            raise Exception("Failed to stop continuous channel data consumer")
        self._running_consumers[DaqModes.CONTINUOUS_CHANNEL_DATA] = False

        logging.info("Stopped continuous channel data consumer")

    def _stop_integrated_channel_data_consumer(self):
        """ Stop integrated channel data consumer """
        self._external_callbacks[DaqModes.INTEGRATED_CHANNEL_DATA] = None
        if stop_consumer("integratedchannel") != Result.Success:
            raise Exception("Failed to stop integrated channel data consumer")
        self._running_consumers[DaqModes.INTEGRATED_CHANNEL_DATA] = False

        logging.info("Stopped integrated channel consumer")

    def _stop_beam_data_consumer(self):
        """ Stop beam data consumer """
        self._external_callbacks[DaqModes.BEAM_DATA] = None
        if stop_consumer("burstbeam") != Result.Success:
            raise Exception("Failed to stop beam data consumer")
        self._running_consumers[DaqModes.BEAM_DATA] = False

        logging.info("Stopped beam data consumer")

    def _stop_integrated_beam_data_consumer(self):
        """ Stop integrated beam data consumer """
        self._external_callbacks[DaqModes.INTEGRATED_BEAM_DATA] = None
        if stop_consumer("integratedbeam") != Result.Success:
            raise Exception("Failed to stop integrated beam data consumer")
        self._running_consumers[DaqModes.INTEGRATED_BEAM_DATA] = False

        logging.info("Stopped integrated beam data consumer")

    def _stop_station_beam_data_consumer(self):
        """ Stop beam data consumer """
        self._external_callbacks[DaqModes.STATION_BEAM_DATA] = None
        if stop_consumer("stationdata") != Result.Success:
            raise Exception("Failed to stop station beam data consumer")
        self._running_consumers[DaqModes.STATION_BEAM_DATA] = False

        logging.info("Stopped station beam data consumer")

    def _stop_correlator(self):
        """ Stop correlator consumer """
        self._external_callbacks[DaqModes.CORRELATOR_DATA] = None
        if stop_consumer("correlator") != Result.Success:
            raise Exception("Failed to stop correlator")
        self._running_consumers[DaqModes.CORRELATOR_DATA] = False

        logging.info("Stopped correlator")

    # ------------------------------------- INITIALISATION -----------------------------------

    def initialise_daq(self):
        """ Initialise DAQ library """

        # Remove any locks
        daq_logger.info("Removing locks on files in output directory")
        os.system("rm -fr %s/*.lock" % self._config['directory'])

        # Initialise AAVS DAQ library
        logging.info("Initialising library")

        # NOTE: Hardcoded case for 48-element stations in AAVS
        initialise_library()

        # Set logging callback
        call_attach_logger(self._daq_logging_function)

        # Start receiver
        if call_start_receiver(self._config['receiver_interface'].encode(),
                               self._config['receiver_ip'],
                               self._config['receiver_frame_size'],
                               self._config['receiver_frames_per_block'],
                               self._config['receiver_nof_blocks']) != Result.Success.value:
            logging.info("Failed to start receiver")
            raise Exception("Failed to start receiver")

        # Set receiver ports
        for port in self._config['receiver_ports']:
            if call_add_receiver_port(port) != Result.Success.value:
                logging.info("Failed to set receiver port %d" % port)
                raise Exception("Failed to set receiver port %d" % port)

    def start_daq(self, daq_modes):
        """ Start acquiring data for specified modes
        :param daq_modes: List of modes to start, should be from DaqModes"""

        # Running in raw data mode
        if DaqModes.RAW_DATA in daq_modes:
            self._start_raw_data_consumer()

        # Running in integrated data mode
        if DaqModes.INTEGRATED_CHANNEL_DATA in daq_modes:
            self._start_integrated_channel_data_consumer()

        # Running in continuous channel mode
        if DaqModes.CONTINUOUS_CHANNEL_DATA in daq_modes:
            self._start_continuous_channel_data_consumer()

        # Running in burst mode
        if DaqModes.CHANNEL_DATA in daq_modes:
            self._start_channel_data_consumer()

        # Running in tile beam mode
        if DaqModes.BEAM_DATA in daq_modes:
            self._start_beam_data_consumer()

        # Running in integrated tile beam mode
        if DaqModes.INTEGRATED_BEAM_DATA in daq_modes:
            self._start_integrated_beam_data_consumer()

        # Running in integrated station beam mode
        if DaqModes.STATION_BEAM_DATA in daq_modes:
            self._start_station_beam_data_consumer()

        # Running in correlator mode
        if DaqModes.CORRELATOR_DATA in daq_modes:
            self._start_correlator()

    def stop_daq(self):
        """ Stop DAQ """

        # Clear data
        self._buffer_counter = {}
        self._timestamps = {}

        # Link stop consumer functions
        stop_functions = {DaqModes.RAW_DATA: self._stop_raw_data_consumer,
                          DaqModes.CHANNEL_DATA: self._stop_channel_data_consumer,
                          DaqModes.BEAM_DATA: self._stop_beam_data_consumer,
                          DaqModes.CONTINUOUS_CHANNEL_DATA: self._stop_continuous_channel_data_consumer,
                          DaqModes.INTEGRATED_BEAM_DATA: self._stop_integrated_beam_data_consumer,
                          DaqModes.INTEGRATED_CHANNEL_DATA: self._stop_integrated_channel_data_consumer,
                          DaqModes.STATION_BEAM_DATA: self._stop_station_beam_data_consumer,
                          DaqModes.CORRELATOR_DATA: self._stop_correlator}

        # Stop all running consumers
        for key, running in list(self._running_consumers.items()):
            if running:
                stop_functions[key]()

        # Stop DAQ receiver thread
        if call_stop_receiver() != Result.Success.value:
            raise Exception("Failed to stop receiver")

        logging.info("Stopped DAQ")

    # ------------------------------------- CONFIGURATION ------------------------------------

    def populate_configuration(self, configuration):
        """ Generate instance configuration object
        :param configuration: Configuration parameters  """

        # Check whether configuration object is a dictionary
        import optparse
        if configuration.__class__ == optparse.Values:
            configuration = vars(configuration)
        elif type(configuration) is not dict:
            raise Exception("Configuration parameters must be a dictionary")

        # Check if invalid parameters were passed in
        if len(set(configuration.keys()) - (set(self._config.keys()))) != 0:
            if self._config['logging']:
                logging.warning("Invalid configuration")
            raise Exception("Invalid configuration")

        # Check if data directory exists
        if not os.path.exists(configuration['directory']):
            if self._config['logging']:
                logging.info("Specified data directory [%s] does not exist" % configuration['directory'])
            raise Exception("Specified data directory [%s] does not exist" % configuration['directory'])

        # Apply configuration
        for k, v in list(configuration.items()):
            self._config[k] = v

        # Extract port string and create list of ports
        if type(self._config['receiver_ports']) is not list:
            self._config['receiver_ports'] = [int(x) for x in self._config['receiver_ports'].split(',')]

        # Check if an IP address was provided, and if not get the assigned address to the interface
        if self._config['receiver_ip'] == "":
            try:
                self._config['receiver_ip'] = self._get_ip_address(self._config['receiver_interface'].encode())
            except IOError as e:
                logging.error("Interface does not exist or could not get it's IP: {}".format(e))
                exit()

        # Get metadata
        metadata = {'software_version': self._get_software_version(),
                    'description': self._config['description']}
        if self._config['station_config'] is not None:
            if os.path.exists(self._config['station_config']) and os.path.isfile(self._config['station_config']):
                metadata.update(self._get_station_information(self._config['station_config']))
            else:
                logging.warning(
                    "Provided station config file ({}) in invalid, ignoring.".format(self._config['station_config']))

        # Set metadata
        self._config['observation_metadata'] = metadata

    # ------------------------------------ HELPER FUNCTIONS ----------------------------------

    @staticmethod
    def _get_station_information(station_config):
        """ If a station configuration file is provided, connect to
            station and get required information """

        # Dictionary containing required metadata
        metadata = {'firmware_version': 0,
                    'station_config': ""
                    }

        # Grab file content as string and save it as metadata
        with open(station_config) as station_config_file:
            metadata['station_config'] = station_config_file.read()

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

    @staticmethod
    def _get_software_version():
        """ Get current software version. This will get the latest git commit hash"""
        try:

            if "AAVS_SOFTWARE_DIRECTORY" not in os.environ:
                logging.error("AAVS_SOFTWARE_DIRECTORY not defined, cannot write software version")
                return 0x0

            path = os.path.expanduser(os.environ['AAVS_SOFTWARE_DIRECTORY'])

            import git
            repo = git.Repo(path)
            return repo.head.object.hexsha
        except Exception:
            logging.warning("Could not get software git hash. Skipping")
            return 0

    def get_configuration(self):
        """ Return configuration dictionary """
        return self._config

    @staticmethod
    def _get_numpy_from_ctypes(pointer, dtype, nof_values):
        """ Return a numpy object representing content in memory referenced by pointer
         :param pointer: Pointer to memory
         :param dtype: Data type to case data to
         :param nof_values: Number of value in memory area """
        value_buffer = ctypes.c_char * np.dtype(dtype).itemsize * nof_values
        return np.frombuffer(value_buffer.from_address(ctypes.addressof(pointer.contents)), dtype)

    @staticmethod
    def _logging_callback(level, message):
        """ Wrapper to logging function in low-level DAQ
        :param level: Logging level
        :param message; Message to log """
        message = message.decode()

        if level == LogLevel.Fatal.value:
            daq_logger.fatal(message)
            sys.exit()
        elif level == LogLevel.Error.value:
            daq_logger.error(message)
            sys.exit()
        elif level == LogLevel.Warning.value:
            daq_logger.warning(message)
        elif level == LogLevel.Info.value:
            daq_logger.info(message)
        elif level == LogLevel.Debug.value:
            daq_logger.debug(message)

    def send_slack_message(self, message):
        """ Send a message of slack
        :param message: Message to send"""
        self._slack.info(message)

    @staticmethod
    def _get_ip_address(interface):
        """ Helper methode to get the IP address of a specified interface
        :param interface: Network interface name """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return socket.inet_ntoa(fcntl.ioctl(
            s.fileno(),
            0x8915,  # SIOCGIFADDR
            struct.pack('256s', interface[:15])
        )[20:24]).encode()

    def set_slack(self, name):
        """ Set slack instance
        :param name: Station name"""
        self._slack = get_slack_instance(name)


# Script main entry point
if __name__ == "__main__":

    # Use OptionParse to get command-line arguments
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %daq_receiver [options]")

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
                      type="int", default=32, help="Number of beam samples per buffer (requires different firmware to "
                                                   "change [default: 32]")
    parser.add_option("", "--station_samples", action="store", dest="nof_station_samples",
                      type="int", default=262144, help="Number of station beam samples per buffer [default: 262144]")
    parser.add_option("", "--correlator-channels", action="store", dest="nof_correlator_channels",
                      type="int", default=1, help="Number of channels to channelise into before correlation. Only "
                                                  "used in correlator more [default: 1]")
    parser.add_option("", "--tsamp", action="store", dest="tsamp",
                      type="float", default=1.1325,
                      help="Sampling time in s (required for -I and -X) [default: 1.1325s]")
    parser.add_option("", "--sampling_rate", action="store", dest="sampling_rate",
                      type="int", default=(800e6 / 2.0) * (32.0 / 27.0) / 512.0,
                      help="FPGA sampling rate [default: {:,.2e}]".format((800e6 / 2.0) * (32.0 / 27.0) / 512.0))
    parser.add_option("", "--oversampling_factor", action="store", dest="oversampling_factor",
                      type="float", default=32.0 / 27.0,
                      help="Oversampling factor [default: 32/27]")
    parser.add_option("", "--continuous_period", action="store", dest="continuous_period",
                      type="int", default=0, help="Number of elapsed seconds between successive dumps of continuous "
                                                  "channel data [default: 0 (dump everything)")
    parser.add_option("", "--append_integrated", action="store_false", dest="append_integrated", default=True,
                      help="Append integrated data in the same file (default: True")

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
    parser.add_option("-C", "--read_channel_data", action="store_true", dest="read_channel_data",
                      default=False, help="Read channelised data [default: False]")
    parser.add_option("-X", "--read_continuous_channel_data", action="store_true", dest="continuous_channel",
                      default=False, help="Read continuous channel data [default: False]")
    parser.add_option("-D", "--read_integrated_channel_data", action="store_true", dest="integrated_channel",
                      default=False, help="Read integrated channel data[default: False]")
    parser.add_option("-K", "--correlator", action="store_true", dest="correlator",
                      default=False, help="Perform correlator [default: False]")

    # Persister options
    parser.add_option("-d", "--data-directory", action="store", dest="directory",
                      default=".", help="Parent directory where data will be stored [default: current directory]")
    parser.add_option("--disable-writing-to-disk", action="store_false", dest="write_to_disk",
                      default=True, help="Write files to disk [default: Enabled]")
    parser.add_option("-m", "--max-filesize", "--max-filesize_gb", action="store", dest="max_filesize",
                      default=None, type="float",
                      help="Maximum file size in GB, set 0 to save each data set to a separate "
                           "hdf5 file [default: 4 GB]")
    parser.add_option("--disable-logging", action="store_false", dest="logging", default=True,
                      help="Disable logging [default: Enabled]")

    # Observation options
    parser.add_option("--description", action="store", dest="description", default="",
                      help="Observation description, stored in file metadata (default: "")")
    parser.add_option("--station-config", action="store", dest="station_config", default=None,
                      help="Station configuration file, to extract additional metadata (default: None)")
    parser.add_option("--acquisition_duration", "--runtime", "--duration", "--dt", action="store",
                      dest="acquisition_duration",
                      default=-1, help="Duration of data acquisiton in seconds [default: %default]", type="int")

    (config, args) = parser.parse_args(argv[1:])

    # Set current thread name
    threading.currentThread().name = "DAQ"

    if config.max_filesize is not None:
        aavs_file.AAVSFileManager.FILE_SIZE_GIGABYTES = config.max_filesize

    # Generate DAQ config
    daq_config = {}
    for key in config.__dict__.keys():
        modes = ["read_raw_data", "read_beam_data", "integrated_beam", "station_beam", "read_channel_data",
                 "continuous_channel", "integrated_channel", "correlator"]
        if key not in modes:
            daq_config[key] = getattr(config, key)

    # Create DAQ instance
    daq_instance = DaqReceiver()

    # Populate configuration
    daq_instance.populate_configuration(daq_config)

    # If station configuration is defined, then we can push updates to slack
    station_name = ""
    if 'station_config' in daq_instance.get_configuration()['observation_metadata'].keys():
        with open(config.station_config, 'r') as f:
            c = yaml.load(f, Loader=yaml.FullLoader)
            name = c['station']['name']
            daq_instance.set_slack(name)

    # Check if any mode was chosen
    if not any([config.read_beam_data, config.read_channel_data, config.read_raw_data, config.correlator,
                config.continuous_channel, config.integrated_beam, config.integrated_channel, config.station_beam]):
        logging.error("No DAQ mode was set. Exiting")
        exit(0)

    # Push command to slack
    daq_instance.send_slack_message("DAQ running with command:\n {}".format(' '.join(argv)))

    # Initialise library
    daq_instance.initialise_daq()

    # Generate list of modes to start
    modes_to_start = []
    if config.read_raw_data:
        modes_to_start.append(DaqModes.RAW_DATA)

    if config.integrated_channel:
        modes_to_start.append(DaqModes.INTEGRATED_CHANNEL_DATA)

    if config.continuous_channel:
        modes_to_start.append(DaqModes.CONTINUOUS_CHANNEL_DATA)

    if config.read_channel_data:
        modes_to_start.append(DaqModes.CHANNEL_DATA)

    if config.read_beam_data:
        modes_to_start.append(DaqModes.BEAM_DATA)

    if config.integrated_beam:
        modes_to_start.append(DaqModes.INTEGRATED_BEAM_DATA)

    if config.station_beam:
        modes_to_start.append(DaqModes.STATION_BEAM_DATA)

    if config.correlator:
        modes_to_start.append(DaqModes.CORRELATOR_DATA)

    # Start acquiring
    daq_instance.start_daq(modes_to_start)

    logging.info("Ready to receive data. Enter 'q' to quit")

    # Signal handler for handling Ctrl-C
    def _signal_handler(_, __):
        logging.info("Ctrl-C detected. Please press 'q' then Enter to quit")


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
    daq_instance.stop_daq()

    daq_instance.send_slack_message("DAQ acquisition stopped")
