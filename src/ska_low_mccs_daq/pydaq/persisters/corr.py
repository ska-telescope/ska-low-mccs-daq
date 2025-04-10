from builtins import range, str

from .aavs_file import *


class CorrelationFormatFileManager(AAVSFileManager):
    """
    A subclass of AAVSFileManager for Correlation matrix files. Inherits all behaviour and implements
    abstract functionality.
    """

    def __init__(
        self,
        root_path=None,
        daq_mode=None,
        data_type="complex64",
        observation_metadata=None,
    ):
        """
        Constructor for Correlation file manager.
        :param root_path: Directory where all file operations will take place.
        :param daq_mode: The DAQ type (e.g. normal (none), integrated, etc.
        :param data_type: The data type for all data in this file set/sequence.
        :param observation_metadata: A dictionary with observation related metadata which will be stored in the file
        """
        super(CorrelationFormatFileManager, self).__init__(
            root_path=root_path,
            file_type=FileTypes.Correlation,
            daq_mode=daq_mode,
            data_type=data_type,
            observation_metadata=observation_metadata,
        )

    def configure(self, file_obj):
        """
        Configures a Channel HDF5 file with the appropriate metadata, creates a dataset for channel data and a dataset
        for sample timestamps.
        :param file_obj: The file object to be configured.
        :return:
        """
        n_baselines = self.main_dset.attrs["n_baselines"]
        n_stokes = self.main_dset.attrs["n_stokes"]
        n_chans = self.main_dset.attrs["n_chans"]
        n_samp = self.main_dset.attrs["n_samples"]  # should always be 1

        if n_samp == 1:
            self.resize_factor = 1
        else:
            self.resize_factor = 128

        corr_group = file_obj.create_group("correlation_matrix")
        corr_group.create_dataset(
            "data",
            (0, n_chans, n_baselines, n_stokes),
            dtype=self.data_type,
            chunks=(1, n_chans, n_baselines, n_stokes),
            maxshape=(None, n_chans, n_baselines, n_stokes),
        )

        timestamp_grp = file_obj.create_group("sample_timestamps")
        timestamp_grp.create_dataset(
            "data",
            (0, 1),
            chunks=(self.n_samples, 1),
            dtype=numpy.float64,
            maxshape=(None, 1),
        )

        file_obj.flush()

    def read_data(
        self,
        timestamp=None,
        channel_id=None,
        channels=None,
        antennas=None,
        polarizations=None,
        n_samples=None,
        sample_offset=None,
        start_ts=None,
        end_ts=None,
        **kwargs
    ):
        """
        Method to read data from a correlation matrix data file for a given query.
        Queries can be done based on sample indexes, or timestamps.
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

        metadata_dict = self.get_metadata(timestamp=timestamp, tile_id=channel_id)
        if metadata_dict is not None:
            if antennas is None:
                antennas = list(range(0, metadata_dict["n_antennas"]))
            if n_samples is None:
                n_samples = 0

            if "n_baselines" not in kwargs:
                baselines = list(range(0, metadata_dict["n_baselines"]))
            else:
                baselines = kwargs["n_baselines"]
            if "n_stokes" not in kwargs:
                stokes = list(range(0, metadata_dict["n_stokes"]))
            else:
                stokes = kwargs["n_stokes"]

            if channels is None:
                channels = list(range(0, metadata_dict["n_chans"]))
            if antennas is None:
                antennas = list(range(0, metadata_dict["n_antennas"]))
            if polarizations is None:
                polarizations = list(range(0, metadata_dict["n_pols"]))

            options = {"baselines": baselines, "stokes": stokes}

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

            partition_index_list = []
            if not sample_based_read:
                partition_index_list = self.get_file_partition_indexes_to_read_given_ts(
                    timestamp=timestamp,
                    tile_id=channel_id,
                    query_ts_start=start_ts,
                    query_ts_end=end_ts,
                )

            if sample_based_read:
                partition_index_list = (
                    self.get_file_partition_indexes_to_read_given_samples(
                        timestamp=timestamp,
                        tile_id=channel_id,
                        query_samples_read=n_samples,
                        query_sample_offset=sample_offset,
                    )
                )

            concat_cnt = 0
            for part in partition_index_list:
                partition = part["partition"]
                indexes = part["indexes"]
                partition_data, partition_timestamps = self._read_data(
                    timestamp=timestamp,
                    channel_id=channel_id,
                    channels=channels,
                    antennas=antennas,
                    polarizations=polarizations,
                    n_samples=indexes[1] - indexes[0],
                    sample_offset=indexes[0],
                    partition_id=partition,
                    **options
                )

                if concat_cnt < 1:
                    output_buffer = partition_data
                    timestamp_buffer = partition_timestamps
                    concat_cnt += 1
                else:
                    output_buffer = numpy.concatenate(
                        (output_buffer, partition_data), 3
                    )
                    timestamp_buffer = numpy.concatenate(
                        (timestamp_buffer, partition_timestamps), 0
                    )

            output_buffer = numpy.reshape(
                output_buffer,
                (n_samples, self.n_baselines, self.n_stokes, len(channels)),
            )

        return output_buffer, timestamp_buffer

    def _read_data(
        self,
        timestamp=None,
        channel_id=None,
        channels=None,
        antennas=None,
        polarizations=None,
        n_samples=0,
        sample_offset=0,
        partition_id=None,
        **kwargs
    ):
        """
        A helper for the read_data() method. This method performs a read operation based on a sample offset and a
        requested number of samples to be read. If the read_data() method has been called with start and end timestamps
        instead, these would have been converted to the equivalent sample offset and requested number of samples, before
        this method is called.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param channel_id: The channel identifier for a file batch.
        :param channels: An array with a list of channels to be read.
        :param antennas: An array with a list of antennas to be read.
        :param polarizations: An array with a list of polarizations to be read.
        :param n_samples: The number of samples to be read.
        :param sample_offset: An offset, in samples, from which the read operation should start.
        :param partition_id: Indicates which partition for the batch is being read.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        metadata_dict = self.get_metadata(timestamp=timestamp, tile_id=channel_id)
        if n_samples is None:
            n_samples = 0

        baselines = kwargs["baselines"]
        stokes = kwargs["stokes"]

        if channels is None:
            channels = list(range(0, metadata_dict["n_chans"]))

        try:
            file_obj = self.load_file(
                timestamp=timestamp,
                tile_id=channel_id,
                partition=partition_id,
                mode="r",
            )
            if file_obj is not None:
                if file_obj["root"]:
                    logging.info("File root intact.")
                else:
                    logging.error("File root compromised.")
            else:
                logging.error("Invalid file timestamp, returning empty buffer.")
                # return output_buffer
                return []
        except Exception as e:
            logging.error("Can't load file for data reading: {}".format(e))
            raise

        output_buffer = numpy.zeros(
            [n_samples, len(channels), len(baselines), len(stokes)],
            dtype=self.data_type,
        )
        timestamp_buffer = numpy.zeros([n_samples, 1], dtype=float)

        data_flushed = False
        while not data_flushed:
            try:
                correl_group = file_obj["correlation_matrix"]
                correl_group_name = "/" + "correlation_matrix"
                if correl_group["data"].name == correl_group_name + "/data":
                    dset = correl_group["data"]
                    nof_items = self.n_samples
                    try:
                        temp_buffer = dset[
                            sample_offset : sample_offset + n_samples, :, :, :
                        ]
                        temp_buffer = temp_buffer[:, channels]
                        temp_buffer = temp_buffer[:, :, baselines]
                        output_buffer = temp_buffer[:, :, :, stokes]
                        del temp_buffer

                        # extracting timestamps
                        if sample_offset + n_samples > nof_items:
                            timestamp_grp = file_obj["sample_timestamps"]
                            dset = timestamp_grp["data"]
                            timestamp_buffer[0:nof_items] = dset[0:nof_items]
                        else:
                            timestamp_grp = file_obj["sample_timestamps"]
                            dset = timestamp_grp["data"]
                            timestamp_buffer[:] = dset[
                                sample_offset : sample_offset + n_samples
                            ]

                        data_flushed = True
                    except Exception as e:
                        logging.error(str(e))
                        logging.info(
                            "Can't read data - are you requesting data at an index that does not exist?"
                        )
                        data_flushed = True
                        output_buffer = []

            except Exception as e:
                logging.error(str(e))
                logging.info(
                    "Can't read data - are you requesting data at an index that does not exist?"
                )
                data_flushed = True
                output_buffer = []
                timestamp_buffer = []

            self.close_file(file_obj)

        return output_buffer, timestamp_buffer

    def _write_data(
        self,
        data_ptr=None,
        timestamp=None,
        buffer_timestamp=None,
        sampling_time=None,
        channel_id=0,
        partition_id=0,
        timestamp_pad=0,
        **kwargs
    ):
        """
        Method to write data to a correlation matrix file.
        :param data_ptr: A data array.
        :param timestamp:  The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be written to.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param sampling_time: Time per sample.
        :param channel_id: The channel identifier for a file batch.
        :param partition_id: When creating the file, this will indicate which partition for the batch is being created.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :param kwargs: dictionary of keyword arguments
        :return: Filename of the file that has been written
        """
        file_obj = self.create_file(
            timestamp=timestamp, tile_id=channel_id, partition_id=partition_id
        )

        file_obj.flush()
        filename = file_obj.filename

        n_chans = self.main_dset.attrs["n_chans"]
        n_baselines = self.main_dset.attrs["n_baselines"]
        n_stokes = self.main_dset.attrs["n_stokes"]
        n_samp = self.main_dset.attrs["n_samples"]  # should always be 1
        n_blocks = self.main_dset.attrs["n_blocks"]

        self.main_dset.attrs["timestamp"] = timestamp
        self.main_dset.attrs["date_time"] = AAVSFileManager._get_date_time(
            timestamp=timestamp
        )
        corr_group = file_obj["correlation_matrix"]
        dset = corr_group["data"]
        dset.resize(n_samp, axis=0)  # resize for only one fit

        # Copy data
        data_ptr = numpy.reshape(data_ptr, (n_chans, n_baselines, n_stokes))
        dset[:, :, :, :] = data_ptr

        # adding timestamp per sample
        if buffer_timestamp is not None:
            padded_timestamp = buffer_timestamp
        else:
            padded_timestamp = timestamp

        padded_timestamp += timestamp_pad  # add timestamp pad from previous partitions

        if timestamp_pad > 0:
            padded_timestamp = (
                padded_timestamp - timestamp
            )  # since it has already been added for append by the timestap_pad value

        sample_timestamps = numpy.zeros((n_samp, 1), dtype=float)
        if sampling_time not in [0, None]:
            sample_timestamps = self.time_range(
                low=0, up=sampling_time * n_samp - sampling_time, leng=n_samp
            )
            sample_timestamps += padded_timestamp
            sample_timestamps = sample_timestamps.tolist()

        timestamp_grp = file_obj["sample_timestamps"]
        dset = timestamp_grp["data"]
        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(
                dset.shape[0] + self.n_samples, axis=0
            )  # resize to fit new data
        dset[ds_last_size : ds_last_size + n_samp, 0] = sample_timestamps

        # set new number of written blocks
        n_blocks += 1
        self.main_dset.attrs["n_blocks"] = n_blocks

        file_obj.flush()
        self.close_file(file_obj)

        return filename

    def _append_data(
        self,
        data_ptr=None,
        timestamp=None,
        buffer_timestamp=None,
        sampling_time=None,
        channel_id=0,
        partition_id=0,
        timestamp_pad=0,
        **kwargs
    ):
        """
        Method to append data to a correlation matrix file - raises a NotImplementedError since there is no append
        mode for correlation matrix files
        :param data_ptr: A data array.
        :param timestamp:  The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be written to.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param sampling_time: Time per sample.
        :param channel_id: The channel identifier for a file batch.
        :param partition_id: When creating the file, this will indicate which partition for the batch is being created.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        file_obj = None
        try:
            file_obj = self.load_file(
                timestamp=timestamp, tile_id=channel_id, mode="r+"
            )
        except:
            logging.error("Error opening file in append mode")

        if file_obj is None:
            file_obj = self.create_file(
                timestamp=timestamp, tile_id=channel_id, partition_id=partition_id
            )

        filename = file_obj.filename

        n_chans = self.main_dset.attrs["n_chans"]
        n_baselines = self.main_dset.attrs["n_baselines"]
        n_stokes = self.main_dset.attrs["n_stokes"]
        n_samp = self.main_dset.attrs["n_samples"]  # should always be 1
        n_blocks = self.main_dset.attrs["n_blocks"]

        self.main_dset.attrs["timestamp"] = timestamp
        self.main_dset.attrs["date_time"] = AAVSFileManager._get_date_time(
            timestamp=timestamp
        )
        corr_group = file_obj["correlation_matrix"]
        dset = corr_group["data"]

        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(dset.shape[0] + n_samp, axis=0)  # resize to fit new data

        # Copy data
        data_ptr = numpy.reshape(data_ptr, (n_chans, n_baselines, n_stokes))
        dset[ds_last_size : ds_last_size + n_samp, :, :, :] = data_ptr

        # adding timestamp per sample
        if buffer_timestamp is not None:
            padded_timestamp = buffer_timestamp
        else:
            padded_timestamp = timestamp

        padded_timestamp += timestamp_pad  # add timestamp pad from previous partitions

        if timestamp_pad > 0:
            padded_timestamp = (
                padded_timestamp - timestamp
            )  # since it has already been added for append by the timestap_pad value

        sample_timestamps = numpy.zeros((n_samp, 1), dtype=float)
        if sampling_time not in [0, None]:
            sample_timestamps = self.time_range(
                low=0, up=sampling_time * n_samp - sampling_time, leng=n_samp
            )
            sample_timestamps += padded_timestamp
            sample_timestamps = sample_timestamps.tolist()

        timestamp_grp = file_obj["sample_timestamps"]
        dset = timestamp_grp["data"]
        ds_last_size = n_blocks * n_samp
        if dset.shape[0] < (n_blocks + 1) * n_samp:
            dset.resize(
                dset.shape[0] + self.n_samples, axis=0
            )  # resize to fit new data

        dset[ds_last_size : ds_last_size + n_samp, 0] = sample_timestamps

        # set new number of written blocks
        n_blocks += 1
        self.main_dset.attrs["n_blocks"] = n_blocks

        file_obj.flush()
        self.close_file(file_obj)

        return filename
