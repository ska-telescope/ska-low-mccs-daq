from builtins import str
from builtins import range
import numpy

from pydaq.persisters.aavs_file import *


class ChannelFormatFileManager(AAVSFileManager):
    """
    A subclass of AAVSFileManager for Channel files. Inherits all behaviour and implements abstract functionality.
    """

    def __init__(self, root_path=None, daq_mode=None, data_type=b'complex'):
        """
        Constructor for Channel file manager.
        :param root_path: Directory where all file operations will take place.
        :param daq_mode: The DAQ type (e.g. normal (none), integrated, etc.
        :param data_type: The data type for all data in this file set/sequence.
        """
        super(ChannelFormatFileManager, self).__init__(root_path=root_path,
                                                       file_type=FileTypes.Channel,
                                                       daq_mode=daq_mode,
                                                       data_type=data_type)

    def configure(self, file_obj):
        """
        Configures a Channel HDF5 file with the appropriate metadata, creates a dataset for channel data and a dataset
        for sample timestamps.
        :param file_obj: The file object to be configured.
        :return:
        """
        n_pols = self.main_dset.attrs['n_pols']
        n_antennas = self.main_dset.attrs['n_antennas']
        n_samp = self.main_dset.attrs['n_samples']
        n_chans = self.main_dset.attrs['n_chans']
        chan_group = file_obj.create_group("chan_")

        if n_samp == 1:
            self.resize_factor = 1024
        else:
            self.resize_factor = n_samp

        chan_group.create_dataset("data", (0, n_chans * n_pols * n_antennas),
                                  chunks=(self.resize_factor, n_chans * n_pols * n_antennas),
                                  dtype=self.data_type, maxshape=(None, n_chans * n_pols * n_antennas))

        timestamp_grp = file_obj.create_group("sample_timestamps")
        timestamp_grp.create_dataset("data", (0, 1), chunks=(self.resize_factor, 1),
                                     dtype=numpy.float64, maxshape=(None, 1))

        file_obj.flush()

    def read_data(self, timestamp=None, tile_id=0, channels=None, antennas=None, polarizations=None, n_samples=None,
                  sample_offset=None, start_ts=None, end_ts=None, **kwargs):
        """
        Method to read data from a channel data file for a given query. Queries can be done based on sample indexes,
        or timestamps.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param tile_id: The tile identifier for a file batch.
        :param channels: An array with a list of channels to be read. If None, all channels in the file are read.
        :param antennas: An array with a list of antennas to be read. If None, all antennas in the file are read.
        :param polarizations: An array with a list of polarizations to be read. If None, all polarizations in the file
        are read.
        :param n_samples: The number of samples to be read.
        :param sample_offset: An offset, in samples, from which the read operation should start.
        :param start_ts: A start timestamp for a read query based on timestamps.
        :param end_ts: An end timestamp for a ready query based on timestamps.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        output_buffer = []
        timestamp_buffer = []

        metadata_dict = self.get_metadata(timestamp=timestamp, tile_id=tile_id)
        if channels is None:
            channels = list(range(0, metadata_dict["n_chans"]))
        if antennas is None:
            antennas = list(range(0, metadata_dict["n_antennas"]))
        if polarizations is None:
            polarizations = list(range(0, metadata_dict["n_pols"]))

        if n_samples is not None:
            sample_based_read = True
            if sample_offset is None:
                sample_offset = 0
        else:
            sample_based_read = False
            if start_ts is None:
                start_ts = 0
            if end_ts is None:
                end_ts = 0

        result = []
        if not sample_based_read:
            result = self.get_file_partition_indexes_to_read_given_ts(timestamp=timestamp,
                                                                      tile_id=tile_id,
                                                                      query_ts_start=start_ts,
                                                                      query_ts_end=end_ts)

        if sample_based_read:
            result = self.get_file_partition_indexes_to_read_given_samples(timestamp=timestamp,
                                                                           tile_id=tile_id,
                                                                           query_samples_read=n_samples,
                                                                           query_sample_offset=sample_offset)

        concat_cnt = 0
        for part in result:
            partition = part["partition"]
            indexes = part["indexes"]
            partition_data, partition_timestamps = self._read_data(timestamp=timestamp,
                                                                   tile_id=tile_id,
                                                                   channels=channels,
                                                                   antennas=antennas,
                                                                   polarizations=polarizations,
                                                                   n_samples=indexes[1] - indexes[0],
                                                                   sample_offset=indexes[0],
                                                                   partition_id=partition)
            if concat_cnt < 1:
                output_buffer = partition_data
                timestamp_buffer = partition_timestamps
                concat_cnt += 1
            else:
                output_buffer = numpy.concatenate((output_buffer, partition_data), 3)
                timestamp_buffer = numpy.concatenate((timestamp_buffer, partition_timestamps), 0)

        return output_buffer, timestamp_buffer

    def _read_data(self, timestamp=None, tile_id=0, channels=None, antennas=None, polarizations=None, n_samples=0,
                   sample_offset=0, partition_id=None, **kwargs):
        """
        A helper for the read_data() method. This method performs a read operation based on a sample offset and a
        requested number of samples to be read. If the read_data() method has been called with start and end timestamps
        instead, these would have been converted to the equivalent sample offset and requested number of samples, before
        this method is called.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param tile_id: The tile identifier for a file batch.
        :param channels: An array with a list of channels to be read.
        :param antennas: An array with a list of antennas to be read.
        :param polarizations: An array with a list of polarizations to be read.
        :param n_samples: The number of samples to be read.
        :param sample_offset: An offset, in samples, from which the read operation should start.
        :param partition_id: Indicates which partition for the batch is being read.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        metadata_dict = self.get_metadata(timestamp=timestamp, tile_id=tile_id)
        if channels is None:
            channels = list(range(0, metadata_dict["n_chans"]))
        if antennas is None:
            antennas = list(range(0, metadata_dict["n_antennas"]))
        if polarizations is None:
            polarizations = list(range(0, metadata_dict["n_pols"]))

        try:
            file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id, partition=partition_id, mode='r')
            if file_obj is not None:
                if not file_obj["root"]:
                    logging.error("File root compromised.")
                    return [], []
            else:
                logging.error("Invalid file timestamp, returning empty buffer.")
                # return output_buffer
                return [], []
        except Exception as e:
            logging.error("Can't load file for data reading: {}".format(e))
            raise

        output_buffer = numpy.zeros([len(channels), len(antennas), len(polarizations), n_samples], dtype=self.data_type)
        timestamp_buffer = numpy.zeros([n_samples, 1], dtype=numpy.float)

        data_flushed = False
        while not data_flushed:
            try:
                channel_grp = file_obj["chan_"]
                channel_name = "/" + "chan_"
                if channel_grp["data"].name == channel_name + "/data":
                    dset = channel_grp["data"]
                    nof_items = dset.shape[0]

                    list_of_indices = []
                    for channel in channels:
                        for antenna in antennas:
                            for pol in polarizations:
                                list_of_indices.append((channel * (self.n_antennas * self.n_pols)) + (
                                    antenna * self.n_pols) + pol)

                    try:
                        temp_buffer = dset[sample_offset:n_samples + sample_offset, list_of_indices]
                        if sample_offset + n_samples > nof_items:
                            temp_buffer = numpy.pad(temp_buffer, ((0, n_samples - nof_items), (0, 0)),
                                                    mode='constant', constant_values=0)

                        output_buffer = temp_buffer.reshape((n_samples, len(channels),
                                                             len(antennas), len(polarizations)))

                        output_buffer = numpy.transpose(output_buffer, (3, 1, 2, 0))
                        output_buffer = numpy.transpose(output_buffer, (1, 0, 2, 3))
                        output_buffer = numpy.transpose(output_buffer, (0, 2, 1, 3))

                        # extracting timestamps
                        if sample_offset + n_samples > nof_items:
                            timestamp_grp = file_obj["sample_timestamps"]
                            dset = timestamp_grp["data"]
                            timestamp_buffer[0:nof_items] = dset[0:nof_items]
                        else:
                            timestamp_grp = file_obj["sample_timestamps"]
                            dset = timestamp_grp["data"]
                            timestamp_buffer[:] = dset[sample_offset:sample_offset + n_samples]
                        data_flushed = True

                    except Exception as e:
                        logging.error(str(e))
                        logging.info("Can't read data - are you requesting data at an index that does not exist?")
                        data_flushed = True
                        output_buffer = []
                        timestamp_buffer = []

            except Exception as e:
                logging.error(str(e))
                logging.info("File appears to be in construction, aborting.")
                self.close_file(file_obj)

        self.close_file(file_obj)
        return output_buffer, timestamp_buffer

    def _write_data(self, data_ptr=None, timestamp=None, buffer_timestamp=None, sampling_time=None, tile_id=0,
                   partition_id=0, timestamp_pad=0, **kwargs):
        """
        Method to write data to a channel file.
        :param data_ptr: A data array.
        :param timestamp:  The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be written to.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param sampling_time: Time per sample.
        :param tile_id: The tile identifier for a file batch.
        :param partition_id: When creating the file, this will indicate which partition for the batch is being created.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        file_obj = self.create_file(timestamp=timestamp, tile_id=tile_id, partition_id=partition_id)
        file_obj.flush()

        n_pols = self.main_dset.attrs['n_pols']
        n_antennas = self.main_dset.attrs['n_antennas']
        n_samp = self.main_dset.attrs['n_samples']
        n_blocks = self.main_dset.attrs['n_blocks']
        n_chans = self.main_dset.attrs['n_chans']
        # collected_data = numpy.empty((n_samp, n_chans * n_pols * n_antennas), dtype=self.data_type)

        self.main_dset.attrs['tsamp'] = sampling_time
        self.main_dset.attrs['timestamp'] = timestamp
        self.main_dset.attrs['date_time'] = AAVSFileManager._get_date_time(timestamp=timestamp)
        channel_grp = file_obj["chan_"]
        dset = channel_grp["data"]

        dset.resize(n_samp, axis=0)  # resize for only one fit

        # Pre-format data
        data_ptr = numpy.reshape(data_ptr, (n_chans, n_samp, n_antennas * n_pols))
        data_ptr = numpy.transpose(data_ptr, (1, 0, 2))
        data_ptr = numpy.reshape(data_ptr, (n_samp, n_chans * n_antennas * n_pols))
        dset[:, :] = data_ptr

        # adding timestamp per sample
        if buffer_timestamp is not None:
            padded_timestamp = buffer_timestamp
        else:
            padded_timestamp = timestamp

        padded_timestamp += timestamp_pad  # add timestamp pad from previous partitions

        if timestamp_pad > 0:
            padded_timestamp = padded_timestamp - timestamp  # since it has already been added for append by the timestap_pad value

        sample_timestamps = numpy.zeros((n_samp, 1), dtype=float)
        if sampling_time not in [0, None]:
            sample_timestamps = self.time_range(low=0, up=sampling_time * n_samp - sampling_time, leng=n_samp)
            sample_timestamps += padded_timestamp
            sample_timestamps = sample_timestamps.tolist()

        timestamp_grp = file_obj["sample_timestamps"]
        dset = timestamp_grp["data"]
        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data
        dset[ds_last_size:ds_last_size + n_samp, 0] = sample_timestamps

        # set new number of written blocks
        n_blocks += 1
        self.main_dset.attrs['n_blocks'] = n_blocks

        # set new final timestamp in file
        self.main_dset.attrs['ts_start'] = sample_timestamps[0]
        self.main_dset.attrs['ts_end'] = sample_timestamps[-1]

        file_obj.flush()
        filename = file_obj.filename
        self.close_file(file_obj)

        return filename

    def _append_data(self, data_ptr=None, timestamp=None, sampling_time=None, buffer_timestamp=None, tile_id=0,
                     timestamp_pad=0, **kwargs):
        """
        Method to append data to a channel file.
        :param data_ptr: A data array.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be appended to.
        :param sampling_time: Time per sample.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param tile_id: The tile identifier for a file batch.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        file_obj = None
        # noinspection PyBroadException
        try:
            file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id, mode='r+')
        except:
            logging.error("Error opening file in append mode")

        if file_obj is None:
            file_obj = self.create_file(timestamp=timestamp, tile_id=tile_id)

        n_pols = self.main_dset.attrs['n_pols']
        n_antennas = self.main_dset.attrs['n_antennas']
        n_samp = self.main_dset.attrs['n_samples']
        n_blocks = self.main_dset.attrs['n_blocks']
        n_chans = self.main_dset.attrs['n_chans']

        # collected_data = numpy.empty((n_samp, n_chans * n_pols * n_antennas), dtype=self.data_type)


        self.main_dset.attrs['timestamp'] = timestamp
        self.main_dset.attrs['date_time'] = AAVSFileManager._get_date_time(timestamp=timestamp)
        channel_grp = file_obj["chan_"]
        dset = channel_grp["data"]

        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data

        # Pre-format data
        data_ptr = numpy.reshape(data_ptr, (n_chans, n_samp, n_antennas * n_pols))
        data_ptr = numpy.transpose(data_ptr, (1, 0, 2))
        data_ptr = numpy.reshape(data_ptr, (n_samp, n_chans * n_antennas * n_pols))

        dset[ds_last_size: ds_last_size + n_samp, :] = data_ptr

        # adding timestamp per sample
        if buffer_timestamp is not None:
            padded_timestamp = buffer_timestamp
        else:
            padded_timestamp = timestamp

        padded_timestamp += timestamp_pad  # add timestamp pad from previous partitions

        if timestamp_pad > 0:
            padded_timestamp = padded_timestamp - timestamp  # since it has already been added for append by the timestap_pad value

        sample_timestamps = numpy.zeros((n_samp, 1), dtype=float)
        if sampling_time not in [0, None]:
            sample_timestamps = self.time_range(low=0, up=sampling_time * n_samp - sampling_time, leng=n_samp)
            sample_timestamps += padded_timestamp
            sample_timestamps = sample_timestamps.tolist()

        timestamp_grp = file_obj["sample_timestamps"]
        dset = timestamp_grp["data"]
        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data

        dset[ds_last_size:ds_last_size + n_samp, 0] = sample_timestamps

        # set new number of written blocks
        n_blocks += 1
        self.main_dset.attrs['n_blocks'] = n_blocks

        # set new final timestamp in file
        self.main_dset.attrs['ts_end'] = sample_timestamps[-1]

        file_obj.flush()
        filename = file_obj.filename
        self.close_file(file_obj)

        return filename
