from builtins import str
from builtins import range
from pydaq.persisters.aavs_file import *


class RawFormatFileManager(AAVSFileManager):
    """
    A subclass of AAVSFileManager for Raw files. Inherits all behaviour and implements abstract functionality.
    """

    def __init__(self, root_path=None, daq_mode=None, data_type="int8", observation_metadata=None):
        """
        Constructor for Raw file manager.
        :param root_path: Directory where all file operations will take place.
        :param daq_mode: The DAQ type (e.g. normal (none), integrated, etc.
        :param data_type: The data type for all data in this file set/sequence.
        :param observation_metadata: A dictionary with observation related metadata which will be stored in the file
        """
        super(RawFormatFileManager, self).__init__(root_path=root_path,
                                                   file_type=FileTypes.Raw,
                                                   daq_mode=daq_mode,
                                                   data_type=data_type,
                                                   observation_metadata=observation_metadata)

    def configure(self, file_obj):
        """
        Configures a Raw HDF5 file with the appropriate metadata, creates a dataset for channel data and a
        dataset for sample timestamps.
        :param file_obj: The file object to be configured.
        :return:
        """
        n_pols = self.main_dset.attrs['n_pols']
        n_antennas = self.main_dset.attrs['n_antennas']
        n_samp = self.main_dset.attrs['n_samples']

        if n_samp == 1:
            self.resize_factor = 1024
        else:
            self.resize_factor = n_samp

        raw_group = file_obj.create_group("raw_")
        raw_group.create_dataset("data", (n_antennas * n_pols, 0),
                                 chunks=(n_antennas * n_pols, self.resize_factor),
                                 dtype=self.data_type,
                                 maxshape=(n_antennas * n_pols, None))

        timestamp_grp = file_obj.create_group("sample_timestamps")
        timestamp_grp.create_dataset("data", (0, 1), chunks=(self.resize_factor, 1),
                                     dtype=numpy.float64, maxshape=(None, 1))

        file_obj.flush()

    def read_data(self, timestamp=None, tile_id=0, channels=None, antennas=None, polarizations=None, n_samples=None,
                  sample_offset=None, start_ts=0, end_ts=0):
        """
        Method to read data from a raw data file for a given query. Queries can be done based on sample indexes,
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
        :return:
        """

        output_buffer = []
        timestamp_buffer = []

        metadata_dict = self.get_metadata(timestamp=timestamp, tile_id=tile_id)
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
                output_buffer = numpy.concatenate((output_buffer, partition_data), 2)
                timestamp_buffer = numpy.concatenate((timestamp_buffer, partition_timestamps), 0)

        return output_buffer, timestamp_buffer

    def _read_data(self, timestamp=None, tile_id=0, antennas=None, polarizations=None, n_samples=0,
                   sample_offset=0, partition_id=None):
        """
        A helper for the read_data() method. This method performs a read operation based on a sample offset and a
        requested number of samples to be read. If the read_data() method has been called with start and end timestamps
        instead, these would have been converted to the equivalent sample offset and requested number of samples, before
        this method is called.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param tile_id: The tile identifier for a file batch.
        :param antennas: An array with a list of antennas to be read.
        :param polarizations: An array with a list of polarizations to be read.
        :param n_samples: The number of samples to be read.
        :param sample_offset: An offset, in samples, from which the read operation should start.
        :param partition_id: Indicates which partition for the batch is being read.
        :return:
        """

        metadata_dict = self.get_metadata(timestamp=timestamp, tile_id=tile_id)
        if antennas is None:
            antennas = list(range(0, metadata_dict["n_antennas"]))
        if polarizations is None:
            polarizations = list(range(0, metadata_dict["n_pols"]))

        try:
            file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id, partition=partition_id, mode='r')
            if file_obj is not None:
                temp_dset = file_obj["root"]
            else:
                logging.error("Invalid file timestamp, returning empty buffer.")
                # return output_buffer
                return [], []
        except Exception as e:
            logging.error("Can't load file for data reading: ", e)
            raise

        output_buffer = numpy.zeros([len(antennas), len(polarizations), n_samples], dtype=self.data_type)
        timestamp_buffer = numpy.zeros([n_samples, 1], dtype=numpy.float)

        data_flushed = False
        while not data_flushed:
            try:
                file_groups = list(file_obj.values())
                file_groups_names = [elem.name for elem in file_groups]

                raw_grp_name = "/raw_"
                if raw_grp_name in file_groups_names:
                    raw_grp = file_obj[raw_grp_name]
                    if raw_grp["data"].name == raw_grp_name + "/data":
                        dset = raw_grp["data"]
                        dset_rows = dset.shape[0]
                        dset_columns = dset.shape[1]
                        nof_items = dset[0].size
                        if (dset_rows == temp_dset.attrs["n_antennas"] * temp_dset.attrs["n_pols"]) and \
                                (dset_columns >= temp_dset.attrs["n_samples"]):
                            for antenna_idx in AAVSFileManager.range_array(0, len(antennas)):
                                current_antenna = antennas[antenna_idx]
                                for polarization_idx in AAVSFileManager.range_array(0, len(polarizations)):
                                    current_polarization = polarizations[polarization_idx]
                                    if sample_offset + n_samples > nof_items:
                                        output_buffer[antenna_idx, polarization_idx, 0:nof_items] = \
                                            dset[(current_antenna * self.n_pols) + current_polarization, 0:nof_items]
                                    else:
                                        output_buffer[antenna_idx, polarization_idx, :] = \
                                            dset[(current_antenna * self.n_pols) + current_polarization,
                                            sample_offset:sample_offset + n_samples]

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

        self.close_file(file_obj)
        return output_buffer, timestamp_buffer

    def _write_data(self, data_ptr=None, timestamp=None, buffer_timestamp=None, sampling_time=None,
                    tile_id=0, partition_id=0, timestamp_pad=0):
        """
        Method to write data to a raw file.
        :param data_ptr: A data array.
        :param timestamp:  The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be written to.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param sampling_time: Time per sample.
        :param tile_id: The tile identifier for a file batch.
        :param partition_id: When creating the file, this will indicate which partition for the batch is being created.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :return:
        """

        file_obj = self.create_file(timestamp=timestamp, tile_id=tile_id, partition_id=partition_id)
        file_obj.flush()

        n_pols = self.main_dset.attrs['n_pols']
        n_antennas = self.main_dset.attrs['n_antennas']
        n_samp = self.main_dset.attrs['n_samples']
        n_blocks = self.main_dset.attrs['n_blocks']
        self.main_dset.attrs['timestamp'] = timestamp
        self.main_dset.attrs['date_time'] = self._get_date_time(timestamp=timestamp)

        raw_grp = file_obj["raw_"]
        dset = raw_grp["data"]
        dset.resize(n_samp, axis=1)  # resize for only one fit

        for antenna in AAVSFileManager.range_array(0, n_antennas):
            for polarization in AAVSFileManager.range_array(0, n_pols):
                start_idx = antenna * n_samp * n_pols + polarization
                end_idx = (antenna + 1) * n_samp * n_pols
                dset[(antenna * n_pols) + polarization, :] = data_ptr[start_idx: end_idx: n_pols]

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
        else:
            sample_timestamps = self.time_range(low=timestamp, up=timestamp, leng=n_samp)
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

    def _append_data(self, data_ptr=None, timestamp=None, sampling_time=None, buffer_timestamp=None,
                     tile_id=0, timestamp_pad=0):
        """
        Method to append data to a raw file.
        :param data_ptr: A data array.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be appended to.
        :param sampling_time: Time per sample.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param tile_id: The tile identifier for a file batch.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
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
        self.main_dset.attrs['timestamp'] = timestamp
        self.main_dset.attrs['date_time'] = self._get_date_time(timestamp=timestamp)

        raw_grp = file_obj["raw_"]
        dset = raw_grp["data"]
        ds_last_size = dset[0].size
        dset.resize(ds_last_size + n_samp, axis=1)  # resize to fit new data

        for antenna in AAVSFileManager.range_array(0, n_antennas):
            for polarization in AAVSFileManager.range_array(0, n_pols):
                start_idx = antenna * n_samp * n_pols + polarization
                end_idx = (antenna + 1) * n_samp * n_pols
                dset[(antenna * n_pols) + polarization, ds_last_size:ds_last_size + n_samp] = \
                    data_ptr[start_idx: end_idx: n_pols]

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
            sample_timestamps = sample_timestamps + padded_timestamp
            sample_timestamps = sample_timestamps.tolist()
        else:
            sample_timestamps = self.time_range(low=timestamp, up=timestamp, leng=n_samp)
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
