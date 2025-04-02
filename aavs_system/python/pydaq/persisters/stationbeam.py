from builtins import str
from builtins import range
from pydaq.persisters.aavs_file import *


class StationBeamFormatFileManager(AAVSFileManager):
    """
    A subclass of AAVSFileManager for StationBeam files. Inherits all behaviour and implements abstract functionality.
    """

    def __init__(self, root_path=None, daq_mode=None, data_type='complex16', observation_metadata=None):
        """
        Constructor for Beamformed file manager.
        :param root_path: Directory where all file operations will take place.
        :param daq_mode: The DAQ type (e.g. normal (none), integrated, etc.
        :param data_type: The data type for all data in this file set/sequence.
        :param observation_metadata: A dictionary with observation related metadata which will be stored in the file
        """
        super(StationBeamFormatFileManager, self).__init__(root_path=root_path,
                                                           file_type=FileTypes.StationBeamformed,
                                                           daq_mode=daq_mode,
                                                           data_type=data_type,
                                                           observation_metadata=observation_metadata)

    def configure(self, file_obj):
        """
        Configures a Beamformed HDF5 file with the appropriate metadata, creates a dataset for channel data and a
        dataset for sample timestamps.
        :param file_obj: The file object to be configured.
        :return:
        """
        n_pols = self.main_dset.attrs['n_pols']
        n_samp = self.main_dset.attrs['n_samples']
        n_chans = self.main_dset.attrs['n_chans']

        if n_samp == 1:
            self.resize_factor = 1024
        else:
            self.resize_factor = n_samp

        for polarization in AAVSFileManager.range_array(0, n_pols):
            polarization_grp = file_obj.create_group("polarization_" + str(polarization))
            polarization_grp.create_dataset("data", (0, n_chans), chunks=(self.resize_factor, 1),
                                            dtype=self.data_type, maxshape=(None, n_chans))

        timestamp_grp = file_obj.create_group("sample_timestamps")
        timestamp_grp.create_dataset("data", (0, 1), chunks=(self.resize_factor, 1),
                                     dtype=numpy.float64, maxshape=(None, 1))

        packet_grp = file_obj.create_group("sample_packets")
        packet_grp.create_dataset("data", (0, 1), chunks=(self.resize_factor, 1),
                                  dtype=numpy.uint32, maxshape=(None, 1))

        file_obj.flush()

    def read_data(self, timestamp=None, station_id=0, channels=None, antennas=None, polarizations=None, beams=None,
                  n_samples=None, sample_offset=None, start_ts=None, end_ts=None):
        """
        Method to read data from a station beam data file for a given query. Queries can be done based on sample indexes,
        or timestamps.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param station_id: The station beam identifier.
        :param channels: An array with a list of channels to be read. If None, all channels in the file are read.
        :param antennas: An array with a list of antennas to be read. If None, all antennas in the file are read.
        :param polarizations: An array with a list of polarizations to be read. If None, all polarizations in the file
        are read.
        :param beams: An array with a list of beams to be read. If None, all beams in the file are read.
        :param n_samples: The number of samples to be read.
        :param sample_offset: An offset, in samples, from which the read operation should start.
        :param start_ts: A start timestamp for a read query based on timestamps.
        :param end_ts: An end timestamp for a ready query based on timestamps.
        :return:
        """
        output_buffer = []
        timestamp_buffer = []
        packets_buffer = []

        metadata_dict = self.get_metadata(timestamp=timestamp, tile_id=station_id)
        if channels is None:
            channels = list(range(0, metadata_dict["n_chans"]))
        if polarizations is None:
            polarizations = list(range(0, metadata_dict["n_pols"]))
        if beams is None:
            beams = list(range(0, metadata_dict["n_beams"]))

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
                                                                      tile_id=station_id,
                                                                      query_ts_start=start_ts,
                                                                      query_ts_end=end_ts)

        if sample_based_read:
            result = self.get_file_partition_indexes_to_read_given_samples(timestamp=timestamp,
                                                                           tile_id=station_id,
                                                                           query_samples_read=n_samples,
                                                                           query_sample_offset=sample_offset)

        concat_cnt = 0
        for part in result:
            partition = part["partition"]
            indexes = part["indexes"]
            partition_data, partition_timestamps, partition_packets = self._read_data(timestamp=timestamp,
                                                                                      station_id=station_id,
                                                                                      channels=channels,
                                                                                      polarizations=polarizations,
                                                                                      beams=beams,
                                                                                      n_samples=indexes[1] - indexes[0],
                                                                                      sample_offset=indexes[0],
                                                                                      partition_id=partition)
            if concat_cnt < 1:
                output_buffer = partition_data
                timestamp_buffer = partition_timestamps
                packets_buffer = partition_packets
                concat_cnt += 1
            else:
                output_buffer = numpy.concatenate((output_buffer, partition_data), 2)
                timestamp_buffer = numpy.concatenate((timestamp_buffer, partition_timestamps), 0)
                packets_buffer = numpy.concatenate((packets_buffer, partition_packets), 0)

        return output_buffer, timestamp_buffer, packets_buffer

    def _read_data(self, timestamp=0, station_id=0, channels=None, polarizations=None, n_samples=0,
                   beams=None, sample_offset=0, partition_id=None, **kwargs):
        """
        A helper for the read_data() method. This method performs a read operation based on a sample offset and a
        requested number of samples to be read. If the read_data() method has been called with start and end timestamps
        instead, these would have been converted to the equivalent sample offset and requested number of samples, before
        this method is called.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param tile_id: The tile identifier for a file batch.
        :param beam_id: The beam identifier.
        :param channels: An array with a list of channels to be read.
        :param polarizations: An array with a list of polarizations to be read.
        :param n_samples: The number of samples to be read.
        :param beams: An array with a list of beams to be read. If None, all beams in the file are read.
        :param sample_offset: An offset, in samples, from which the read operation should start.
        :param partition_id: Indicates which partition for the batch is being read.
        :return:
        """
        metadata_dict = self.get_metadata(timestamp=timestamp, tile_id=station_id)
        if channels is None:
            channels = list(range(0, metadata_dict["n_chans"]))
        if polarizations is None:
            polarizations = list(range(0, metadata_dict["n_pols"]))

        try:
            file_obj = self.load_file(timestamp=timestamp, tile_id=station_id, partition=partition_id, mode='r')
            if file_obj is not None:
                temp_dset = file_obj["root"]
            else:
                logging.error("Invalid file timestamp, returning empty buffer.")
                # return output_buffer
                return [], []
        except Exception as e:
            logging.error("Can't load file for data reading: ", e)
            raise

        output_buffer = numpy.zeros([len(polarizations), n_samples, len(channels)], dtype=self.data_type)
        timestamp_buffer = numpy.zeros([n_samples, 1], dtype=float)
        packets_buffer = numpy.zeros([n_samples, 1], dtype=numpy.uint32)

        data_flushed = False
        while not data_flushed:
            try:
                file_groups = list(file_obj.values())
                file_groups_names = [elem.name for elem in file_groups]

                for polarization_idx in range(0, len(polarizations)):
                    current_polarization = polarizations[polarization_idx]
                    polarization_name = "/polarization_" + str(current_polarization)
                    if polarization_name in file_groups_names:
                        polarization_grp = file_obj["polarization_" + str(current_polarization)]
                        if polarization_grp["data"].name == polarization_name + "/data":
                            dset = polarization_grp["data"]
                            dset_rows = dset.shape[0]
                            dset_columns = dset.shape[1]
                            nof_items = dset_rows
                            if (dset_columns == temp_dset.attrs["n_chans"]) and \
                                    (dset_rows >= temp_dset.attrs["n_samples"]):
                                for channel_idx in AAVSFileManager.range_array(0, len(channels)):
                                    current_channel = channels[channel_idx]
                                    if sample_offset + n_samples > nof_items:
                                        output_buffer[polarization_idx, 0:nof_items, channel_idx] = dset[0:nof_items,
                                                                                                    current_channel]
                                    else:
                                        output_buffer[polarization_idx, :, channel_idx] = dset[
                                                                                          sample_offset:sample_offset + n_samples,
                                                                                          current_channel]

                # extracting timestamps
                if sample_offset + n_samples > nof_items:
                    timestamp_grp = file_obj["sample_timestamps"]
                    dset = timestamp_grp["data"]
                    timestamp_buffer[0:nof_items] = dset[0:nof_items]
                else:
                    timestamp_grp = file_obj["sample_timestamps"]
                    dset = timestamp_grp["data"]
                    timestamp_buffer[:] = dset[sample_offset:sample_offset + n_samples]

                # extracting packets
                if sample_offset + n_samples > nof_items:
                    packets_grp = file_obj["sample_packets"]
                    dset = packets_grp["data"]
                    packets_buffer[0:nof_items] = dset[0:nof_items]
                else:
                    packets_grp = file_obj["sample_packets"]
                    dset = packets_grp["data"]
                    packets_buffer[:] = dset[sample_offset:sample_offset + n_samples]

                data_flushed = True
            except Exception as e:
                logging.error(str(e))
                logging.info("Can't read data - are you requesting data at an index that does not exist?")
                data_flushed = True
                output_buffer = []
                timestamp_buffer = []

        self.close_file(file_obj)
        return output_buffer, timestamp_buffer, packets_buffer

    def _write_data(self, timestamp=None, buffer_timestamp=None, data_ptr=None, sampling_time=None, station_id=0,
                    partition_id=0, timestamp_pad=0, sample_packets=0, **kwargs):
        """
        Method to write data to a beamformed file.
        :param data_ptr: A data array.
        :param timestamp:  The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be written to.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param sampling_time: Time per sample.
        :param station_id: The station identifier for a file batch.
        :param partition_id: When creating the file, this will indicate which partition for the batch is being created.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :return:
        """
        file_obj = self.create_file(timestamp=timestamp, tile_id=station_id, partition_id=partition_id)
        file_obj.flush()

        n_pols = self.main_dset.attrs['n_pols']
        n_samp = self.main_dset.attrs['n_samples']
        n_blocks = self.main_dset.attrs['n_blocks']
        n_chans = self.main_dset.attrs['n_chans']

        self.main_dset.attrs['timestamp'] = timestamp
        for polarization in AAVSFileManager.range_array(0, n_pols):
            polarization_grp = file_obj["polarization_" + str(polarization)]
            dset = polarization_grp["data"]

            dset.resize(n_samp, axis=0)  # resize for only one fit

            # Pre-format data
            pol_start_idx = (polarization * n_chans * n_samp)
            pol_end_idx = (polarization + 1) * n_chans * n_samp
            pol_data = data_ptr[pol_start_idx:pol_end_idx]
            pol_data = numpy.reshape(pol_data, (n_samp, n_chans))
            dset[:, :] = pol_data

        # adding timestamp per sample
        if buffer_timestamp is not None:
            padded_timestamp = buffer_timestamp
        else:
            padded_timestamp = timestamp

        padded_timestamp += timestamp_pad  # add timestamp pad from previous partitions

        if timestamp_pad > 0:
            # Since it has already been added for append by the timestap_pad value
            padded_timestamp = padded_timestamp - timestamp

        sample_timestamps = numpy.zeros((n_samp, 1), dtype=float)
        if sampling_time not in [0, None]:
            sample_timestamps = self.time_range(low=0, up=sampling_time * n_samp - sampling_time, leng=n_samp)
            sample_timestamps = sample_timestamps + padded_timestamp
            sample_timestamps = sample_timestamps.tolist()

        # write timestamps
        timestamp_grp = file_obj["sample_timestamps"]
        dset = timestamp_grp["data"]
        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data
        dset[ds_last_size:ds_last_size + n_samp, 0] = sample_timestamps

        # write packets
        sample_packets_list = numpy.zeros((n_samp, 1), dtype=numpy.uint32)
        sample_packets_list[:] = sample_packets
        sample_packets_list = sample_packets_list.flatten()
        packets_grp = file_obj["sample_packets"]
        dset = packets_grp["data"]
        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data
        dset[ds_last_size:ds_last_size + n_samp, 0] = sample_packets_list

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

    def _append_data(self, timestamp=None, data_ptr=None, sampling_time=None, buffer_timestamp=0, station_id=0,
                     timestamp_pad=0, sample_packets=0, **kwargs):
        """
        Method to append data to a beamformed file.
        :param data_ptr: A data array.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be appended to.
        :param sampling_time: Time per sample.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param station_id: The station identifier for a file batch.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :return:
        """
        file_obj = None
        # noinspection PyBroadException
        try:
            file_obj = self.load_file(timestamp=timestamp, tile_id=station_id, mode='r+')
        except:
            logging.error("Error opening file in append mode")

        if file_obj is None:
            file_obj = self.create_file(timestamp=timestamp, tile_id=station_id)

        n_pols = self.main_dset.attrs['n_pols']
        n_samp = self.main_dset.attrs['n_samples']
        n_blocks = self.main_dset.attrs['n_blocks']
        n_chans = self.main_dset.attrs['n_chans']

        self.main_dset.attrs['timestamp'] = timestamp
        for polarization in AAVSFileManager.range_array(0, n_pols):
            polarization_grp = file_obj["polarization_" + str(polarization)]
            dset = polarization_grp["data"]

            ds_last_size = n_blocks * n_samp
            if dset.shape[0] < (n_blocks + 1) * n_samp:
                dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data

            # Pre-format data
            pol_start_idx = (polarization * n_chans * n_samp)
            pol_end_idx = (polarization + 1) * n_chans * n_samp
            pol_data = data_ptr[pol_start_idx:pol_end_idx]
            pol_data = numpy.reshape(pol_data, (n_samp, n_chans))
            dset[ds_last_size: ds_last_size + n_samp, :] = pol_data

        # adding timestamp per sample
        if buffer_timestamp is not None:
            padded_timestamp = buffer_timestamp
        else:
            padded_timestamp = timestamp

        padded_timestamp += timestamp_pad  # add timestamp pad from previous partitions

        if timestamp_pad > 0:
            # Since it has already been added for append by the timestap_pad value
            padded_timestamp = padded_timestamp - timestamp

        sample_timestamps = numpy.zeros((n_samp, 1), dtype=float)
        if sampling_time not in [0, None]:
            sample_timestamps = self.time_range(low=0, up=sampling_time * n_samp - sampling_time, leng=n_samp)
            sample_timestamps = sample_timestamps + padded_timestamp
            sample_timestamps = sample_timestamps.tolist()

        # write timestamps
        timestamp_grp = file_obj["sample_timestamps"]
        dset = timestamp_grp["data"]
        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data
        dset[ds_last_size:ds_last_size + n_samp, 0] = sample_timestamps

        # write packets
        sample_packets_list = numpy.zeros((n_samp, 1), dtype=numpy.uint32)
        sample_packets_list[:] = sample_packets
        sample_packets_list = sample_packets_list.flatten()
        packets_grp = file_obj["sample_packets"]
        dset = packets_grp["data"]
        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data
        dset[ds_last_size:ds_last_size + n_samp, 0] = sample_packets_list

        # set new number of written blocks
        n_blocks += 1
        self.main_dset.attrs['n_blocks'] = n_blocks

        # set new final timestamp in file
        self.main_dset.attrs['ts_end'] = sample_timestamps[-1]

        file_obj.flush()
        filename = file_obj.filename
        self.close_file(file_obj)

        return filename
