from __future__ import print_function
from builtins import str
from builtins import range
from pydaq.persisters.aavs_file import *
from pydaq.persisters.utils import *
import numpy


class CorrelationFormatFileManager(AAVSFileManager):
    """
    A subclass of AAVSFileManager for Correlation matrix files. Inherits all behaviour and implements
    abstract functionality.
    """

    def __init__(self, root_path=None, daq_mode=None, data_type=b'complex64'):
        """
        Constructor for Correlation file manager.
        :param root_path: Directory where all file operations will take place.
        :param daq_mode: The DAQ type (e.g. normal (none), integrated, etc.
        :param data_type: The data type for all data in this file set/sequence.
        """
        super(CorrelationFormatFileManager, self).__init__(root_path=root_path,
                                                       file_type=FileTypes.Correlation,
                                                       daq_mode=daq_mode,
                                                       data_type=data_type)

        self.metadata_list = ["timestamp","n_chans","n_samples","n_blocks","type", "data_type","date_time","data_mode",
                              "ts_start","ts_end", "n_baselines", "n_stokes", "channel_id"]


        # second set of initialization values
        self.resize_factor = 1
        self.n_chans = 512
        self.n_samples = 0
        self.n_blocks = 0
        self.timestamp = 0
        self.date_time = ""
        self.data_mode = ""
        self.ts_start = 0
        self.ts_end = 0
        self.n_baselines = 0
        self.n_stokes = 0
        self.channel_id = 0
        self.tsamp = 0

    def configure(self, file_obj):
        """
        Configures a Channel HDF5 file with the appropriate metadata, creates a dataset for channel data and a dataset
        for sample timestamps.
        :param file_obj: The file object to be configured.
        :return:
        """
        n_baselines = self.main_dset.attrs['n_baselines']
        n_stokes = self.main_dset.attrs['n_stokes']
        n_chans = self.main_dset.attrs['n_chans']
        n_samp = self.main_dset.attrs['n_samples']  # should always be 1

        self.resize_factor = n_baselines

        corr_group = file_obj.create_group("correlation_matrix")
        corr_group.create_dataset("data",(0, n_chans, n_baselines, n_stokes),
                                  chunks=(1, n_chans, n_baselines, n_stokes),
                                  dtype=self.data_type,
                                  maxshape=(None, n_chans, n_baselines, n_stokes))

        timestamp_grp = file_obj.create_group("sample_timestamps")
        timestamp_grp.create_dataset("data", (0, 1), chunks=(self.resize_factor, 1),
                                     dtype=numpy.float64, maxshape=(None, 1))

        file_obj.flush()

    def set_metadata(self, timestamp=0, n_chans=512, n_samples=0, n_blocks=0, date_time="", data_mode="", n_baselines=0,
                     n_stokes=0):
        """
        A method that has to be called soon after any AAVS File Manager object is created, to let us know what config
        to be used in all subsequent operations.
        :param timestamp: The timestamp for this file set.
        :param n_chans: The number of channels for this file set.
        :param n_samples: The number of samples to expect in operations for this file set.
        :param n_blocks: The number of blocks to start this file set.
        :param date_time: The date time string for this file set.
        :param data_mode: The data mode for this file set (unused).
        :param n_baselines: The number of baselines for correlation.
        :param n_stokes: The number of stokes for correlation.
        :return:
        """
        self.timestamp = timestamp
        self.n_chans = n_chans
        self.n_samples = n_samples
        self.n_blocks = n_blocks
        self.date_time = date_time
        self.data_mode = data_mode
        self.n_baselines = n_baselines
        self.n_stokes = n_stokes

    def load_metadata(self, file_obj):
        """
        Load metadata for a correlator file type.
        :param file_obj: The correlator file object.
        :return:
        """
        self.main_dset = file_obj["root"]
        self.n_chans = self.main_dset.attrs['n_chans']
        self.n_samples = self.main_dset.attrs['n_samples']
        self.n_blocks = self.main_dset.attrs['n_blocks']
        self.date_time = self.main_dset.attrs['date_time']
        self.ts_start = self.main_dset.attrs['ts_start']
        self.ts_end = self.main_dset.attrs['ts_end']
        self.n_baselines = self.main_dset.attrs['n_baselines']
        self.n_stokes = self.main_dset.attrs['n_stokes']
        self.channel_id = self.main_dset.attrs['channel_id']
        if 'nsamp' in list(self.main_dset.attrs.keys()):
            self.nsamp = self.main_dset.attrs['nsamp']

        self.resize_factor = self.n_baselines

        if sys.version_info.major == 3:
            self.timestamp = self.main_dset.attrs['timestamp']
            self.data_type_name = (self.main_dset.attrs['data_type'])
            self.data_type = DATA_TYPE_MAP[self.data_type_name]
        elif sys.version_info.major == 2:
            self.timestamp = self.main_dset.attrs['timestamp']
            self.data_type_name = self.main_dset.attrs['data_type']
            self.data_type = DATA_TYPE_MAP[self.data_type_name]

    def read_data(self, timestamp=None, channel_id=None, channels=None, antennas=None, polarizations=None,
                  n_samples=None, sample_offset=None, start_ts=None, end_ts=None, **kwargs):
        """
        Method to read data from a correlation matrix data file for a given query.
        Queries can be done based on sample indexes, or timestamps.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param channel_id: The channel identifier for a file batch.
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

        metadata_dict = self.get_metadata(timestamp=timestamp, object_id=channel_id)
        if metadata_dict is not None:
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
                partition_index_list = self.get_file_partition_indexes_to_read_given_ts(timestamp=timestamp,
                                                                          object_id=channel_id,
                                                                          query_ts_start=start_ts,
                                                                          query_ts_end=end_ts)

            if sample_based_read:
                partition_index_list = self.get_file_partition_indexes_to_read_given_samples(timestamp=timestamp,
                                                                               object_id=channel_id,
                                                                               query_samples_read=n_samples,
                                                                               query_sample_offset=sample_offset)

            concat_cnt = 0
            for part in partition_index_list:
                partition = part["partition"]
                indexes = part["indexes"]
                partition_data, partition_timestamps = self._read_data(timestamp=timestamp,
                                                                       channel_id=channel_id,
                                                                       channels=channels,
                                                                       antennas=antennas,
                                                                       polarizations=polarizations,
                                                                       n_samples=indexes[1] - indexes[0],
                                                                       sample_offset=indexes[0],
                                                                       partition_id=partition,
                                                                       **options)

                if concat_cnt < 1:
                    output_buffer = partition_data
                    timestamp_buffer = partition_timestamps
                    concat_cnt += 1
                else:
                    output_buffer = numpy.concatenate((output_buffer, partition_data), 3)
                    timestamp_buffer = numpy.concatenate((timestamp_buffer, partition_timestamps), 0)

            output_buffer = numpy.reshape(output_buffer, (n_samples, self.n_baselines, 4, len(channels)))

        return output_buffer, timestamp_buffer

    def _read_data(self, timestamp=None, channel_id=None, channels=None, antennas=None, polarizations=None, n_samples=0,
                   sample_offset=0, partition_id=None, **kwargs):
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
        metadata_dict = self.get_metadata(timestamp=timestamp, object_id=channel_id)
        baselines = kwargs["baselines"]
        stokes = kwargs["stokes"]
        if channels is None:
            channels = list(range(0, metadata_dict["n_chans"]))

        try:
            file_obj = self.load_file(timestamp=timestamp, object_id=channel_id, partition=partition_id, mode='r')
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

        output_buffer = numpy.zeros([n_samples, len(channels), len(baselines), len(stokes)], dtype=self.data_type)
        timestamp_buffer = numpy.zeros([n_samples, 1], dtype=numpy.float)

        with self.file_exception_handler(file_obj=file_obj):
            data_flushed = False
            while not data_flushed:
                try:
                    correl_group = file_obj["correlation_matrix"]
                    dset = correl_group["data"]
                    nof_items = self.n_samples

                    timestamp_grp = file_obj["sample_timestamps"]
                    ts_dset = timestamp_grp["data"]

                    if sample_offset + n_samples > nof_items:
                        output_buffer = dset[0:nof_items,:,:,:][:,channels,:,:][:,:,baselines,:][:,:,:,stokes]
                        timestamp_buffer[0:nof_items] = ts_dset[0:nof_items]
                    else:
                        output_buffer = dset[sample_offset:n_samples, :, :, :][:, channels, :, :][:, :, baselines, :][:, :, :, stokes]
                        timestamp_buffer[:] = ts_dset[sample_offset:sample_offset + n_samples]

                        data_flushed = True
                except Exception as e:
                    logging.error(str(e))
                    logging.info("Can't read data - are you requesting data at an index that does not exist?")
                    data_flushed = True
                    output_buffer = []
                    timestamp_buffer = []

            self.close_file(file_obj)

        return output_buffer, timestamp_buffer

    def _write_data(self, append_mode=False, data_ptr=None, timestamp=None, buffer_timestamp=None, sampling_time=None,
                    object_id=0, partition_id=0, timestamp_pad=0, **kwargs):
        """
        Method to append data to a correlation matrix file - raises a NotImplementedError since there is no append
        mode for correlation matrix files
        :param data_ptr: A data array.
        :param timestamp:  The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be written to.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param sampling_time: Time per sample.
        :param object_id: The object identifier for a file batch.
        :param partition_id: When creating the file, this will indicate which partition for the batch is being created.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        file_obj = None
        try:
            file_obj = self.load_file(timestamp=timestamp, object_id=object_id, partition=partition_id, mode='r+')
            if file_obj is None:
                file_obj = self.create_file(timestamp=timestamp, object_id=object_id, partition_id=partition_id)
            file_obj.flush()
        except:
            raise

        with self.file_exception_handler(file_obj=file_obj):
            filename = file_obj.filename

            n_chans = self.main_dset.attrs['n_chans']
            n_baselines = self.main_dset.attrs['n_baselines']
            n_stokes = self.main_dset.attrs['n_stokes']
            n_samp = self.main_dset.attrs['n_samples']  # should always be 1
            n_blocks = self.main_dset.attrs['n_blocks']

            self.main_dset.attrs['timestamp'] = timestamp
            self.main_dset.attrs['date_time'] = get_date_time(timestamp=timestamp)
            corr_group = file_obj["correlation_matrix"]
            dset = corr_group["data"]

            # Copy data
            data_ptr = numpy.reshape(data_ptr, (n_chans, n_baselines, n_stokes))

            if append_mode:
                # resize dset and write data
                ds_last_size = n_blocks * n_samp
                if dset.shape[0] < (n_blocks + 1) * n_samp:
                    dset.resize(dset.shape[0] + n_samp, axis=0)  # resize to fit new data
                dset[ds_last_size: ds_last_size + n_samp, :, :, :] = data_ptr
            else:
                if dset.shape[0] < 1 * n_samp:
                    dset.resize(dset.shape[0] + n_samp, axis=0)  # resize to fit new data
                dset[0: n_samp, :, :, :] = data_ptr

            # adding timestamp per sample
            self.generate_timestamps(append_mode=append_mode,
                                     file_obj=file_obj,
                                     buffer_timestamp=buffer_timestamp,
                                     timestamp=timestamp,
                                     timestamp_pad=timestamp_pad,
                                     n_samp=n_samp,
                                     sampling_time=sampling_time,
                                     n_blocks=n_blocks)

            file_obj.flush()
            self.close_file(file_obj)

        return filename


if __name__ == '__main__':
    n_chans = 128
    n_samp = 1
    n_pols = 2
    n_antennas = 256
    n_baselines = int(((n_antennas+1)/2.0)*n_antennas)
    n_stokes = 4
    channel_id = 1

    print("ingesting...")
    data = numpy.zeros((n_chans*n_baselines*n_stokes), dtype=numpy.complex64)

    correl_file = CorrelationFormatFileManager(root_path="/home/andrea/", data_type=b'complex64')
    correl_file.set_metadata(n_chans=n_chans,
                             n_stokes = n_stokes,
                             n_samples=n_samp,
                             n_baselines=n_baselines)
    correl_file.ingest_data(timestamp=0, append=True, data_ptr=data, channel_id=channel_id)
    while True:
        correl_file.ingest_data(timestamp=0, append=True, data_ptr=data, channel_id=channel_id)

    # correl_file.read_data(timestamp=0,channel_id=channel_id,n_samples=1)
