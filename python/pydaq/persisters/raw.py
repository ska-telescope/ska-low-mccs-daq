from pydaq.persisters.aavs_file import *
from pydaq.persisters.utils import *
import logging
import numpy


class RawFormatFileManager(AAVSFileManager):
    """
    A subclass of AAVSFileManager for Raw files. Inherits all behaviour and implements abstract functionality.
    """
    def __init__(self, root_path=None, daq_mode=None, data_type=b"int8"):
        """
        Constructor for Raw file manager.
        :param root_path: Directory where all file operations will take place.
        :param daq_mode: The DAQ type (e.g. normal (none), integrated, etc.
        :param data_type: The data type for all data in this file set/sequence.
        """
        super(RawFormatFileManager, self).__init__(root_path=root_path,
                                                   file_type=FileTypes.Raw,
                                                   daq_mode=daq_mode,
                                                   data_type=data_type)

        self.metadata_list = ["timestamp","n_antennas","n_pols","tile_id","n_samples","n_blocks","type",
                              "data_type","date_time","data_mode","ts_start","ts_end"]

        # second set of initialization values
        self.resize_factor = 1024
        self.tile_id = 0
        self.n_antennas = 16
        self.n_pols = 2
        self.n_samples = 0
        self.n_blocks = 0
        self.timestamp = 0
        self.date_time = ""
        self.data_mode = ""
        self.ts_start = 0
        self.ts_end = 0
        self.tsamp = 0

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
        raw_group.create_dataset("data", (n_antennas, n_pols, 0),
                                 chunks=(n_antennas, n_pols, self.resize_factor),
                                 dtype=self.data_type,
                                 maxshape=(n_antennas, n_pols, None))

        timestamp_grp = file_obj.create_group("sample_timestamps")
        timestamp_grp.create_dataset("data", (0, 1), chunks=(self.resize_factor, 1),
                                     dtype=numpy.float64, maxshape=(None, 1))

        file_obj.flush()

    def set_metadata(self, timestamp=0, n_antennas=16, n_pols=2, n_samples=0, n_blocks=0, date_time="", data_mode=""):
        """
        A method that has to be called soon after any AAVS File Manager object is created, to let us know what config
        to be used in all subsequent operations.
        :param timestamp: The timestamp for this file set.
        :param n_antennas: The number of antennas for this file set.
        :param n_pols: The number of polarizations for this file set.
        :param n_samples: The number of samples to expect in operations for this file set.
        :param n_blocks: The number of blocks to start this file set.
        :param date_time: The date time string for this file set.
        :param data_mode: The data mode for this file set (unused).
        :return:
        """
        self.timestamp = timestamp
        self.n_antennas = n_antennas
        self.n_pols = n_pols
        self.n_samples = n_samples
        self.n_blocks = n_blocks
        self.date_time = date_time
        self.data_mode = data_mode

    def load_metadata(self, file_obj):
        """
        Load metadata for a raw file type.
        :param file_obj: The raw file object.
        :return:
        """
        self.main_dset = file_obj["root"]
        self.n_antennas = self.main_dset.attrs['n_antennas']
        self.n_pols = self.main_dset.attrs['n_pols']
        self.tile_id = self.main_dset.attrs['tile_id']
        self.n_samples = self.main_dset.attrs['n_samples']
        self.n_blocks = self.main_dset.attrs['n_blocks']
        self.date_time = self.main_dset.attrs['date_time']
        self.ts_start = self.main_dset.attrs['ts_start']
        self.ts_end = self.main_dset.attrs['ts_end']
        if 'nsamp' in self.main_dset.attrs.keys():
            self.nsamp = self.main_dset.attrs['nsamp']

        if self.n_samples == 1:
            self.resize_factor = 1024
        else:
            self.resize_factor = self.n_samples

        if sys.version_info.major == 3:
            self.timestamp = self.main_dset.attrs['timestamp']
            self.data_type_name = (self.main_dset.attrs['data_type'])
            self.data_type = DATA_TYPE_MAP[self.data_type_name]
        elif sys.version_info.major == 2:
            self.timestamp = self.main_dset.attrs['timestamp']
            self.data_type_name = self.main_dset.attrs['data_type']
            self.data_type = DATA_TYPE_MAP[self.data_type_name]

    def read_data(self, timestamp=None, tile_id=0, channels=None, antennas=None, polarizations=None, n_samples=None,
                  sample_offset=None, start_ts=0, end_ts=0, **kwargs):
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

        metadata_dict = self.get_metadata(timestamp=timestamp, object_id=tile_id)
        if metadata_dict is not None:
            if antennas is None:
                antennas = range(0, metadata_dict["n_antennas"])
            if polarizations is None:
                polarizations = range(0, metadata_dict["n_pols"])

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
                                                                 object_id=tile_id,
                                                                 query_ts_start=start_ts,
                                                                 query_ts_end=end_ts)

            if sample_based_read:
                partition_index_list = self.get_file_partition_indexes_to_read_given_samples(timestamp=timestamp,
                                                                               object_id=tile_id,
                                                                               query_samples_read=n_samples,
                                                                               query_sample_offset=sample_offset)
            concat_cnt = 0
            for part in partition_index_list:
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

        metadata_dict = self.get_metadata(timestamp=timestamp, object_id=tile_id)
        if antennas is None:
            antennas = range(0, metadata_dict["n_antennas"])
        if polarizations is None:
            polarizations = range(0, metadata_dict["n_pols"])

        output_buffer = []
        timestamp_buffer = []

        try:
            file_obj = self.load_file(timestamp=timestamp, object_id=tile_id, partition=partition_id, mode='r')
            with self.file_exception_handler(file_obj=file_obj):
                if file_obj is not None:
                    temp_dset = file_obj["root"]
                else:
                    logging.error("Invalid file timestamp, returning empty buffer.")
                    return output_buffer, timestamp_buffer
        except Exception as e:
            logging.error("Can't load file for data reading: ", e.message)
            raise

        output_buffer = numpy.zeros([len(antennas), len(polarizations), n_samples], dtype=self.data_type)
        timestamp_buffer = numpy.zeros([n_samples, 1], dtype=numpy.float)

        with self.file_exception_handler(file_obj=file_obj):
            data_flushed = False
            while not data_flushed:
                try:
                    raw_grp = file_obj["raw_"]
                    dset = raw_grp["data"]
                    nof_items = dset[2].size

                    timestamp_grp = file_obj["sample_timestamps"]
                    ts_dset = timestamp_grp["data"]

                    if sample_offset + n_samples > nof_items:
                        output_buffer = dset[antennas,:,:][:,polarizations,:][:,:,0:nof_items]
                        timestamp_buffer[0:nof_items] = ts_dset[0:nof_items]
                    else:
                        output_buffer = dset[antennas, :, :][:, polarizations, :][:, :, sample_offset:sample_offset + n_samples]
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

    def _write_data(self, append_mode=False, data_ptr=None, timestamp=None, sampling_time=None, buffer_timestamp=None,
                    object_id=0, partition_id = 0, timestamp_pad=0, **kwargs):
        """
        Method to append data to a raw file.
        :param data_ptr: A data array.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be appended to.
        :param sampling_time: Time per sample.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param object_id: The tile identifier for a file batch.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :return:
        """
        file_obj = None
        filename = None

        try:
            file_obj = self.load_file(timestamp=timestamp, object_id=object_id, mode='r+', partition=partition_id)
            if file_obj is None:
                file_obj = self.create_file(timestamp=timestamp, object_id=object_id, partition_id=partition_id)
            file_obj.flush()
        except:
            raise

        with self.file_exception_handler(file_obj=file_obj):
            filename = file_obj.filename
            n_pols = self.main_dset.attrs['n_pols']
            n_antennas = self.main_dset.attrs['n_antennas']
            n_samp = self.main_dset.attrs['n_samples']
            n_blocks = self.main_dset.attrs['n_blocks']
            self.main_dset.attrs['timestamp'] = timestamp
            self.main_dset.attrs['date_time'] = get_date_time(timestamp=timestamp)

            raw_grp = file_obj["raw_"]
            dset = raw_grp["data"]

            data_ptr = numpy.reshape(data_ptr, (n_antennas, n_pols, n_samp))

            if append_mode:
                ds_last_size = n_blocks * n_samp
                if dset.shape[2] < (n_blocks + 1) * n_samp:
                    dset.resize(ds_last_size + n_samp, axis=2)  # resize to fit new data
                dset[:, :, ds_last_size:ds_last_size + n_samp] = data_ptr
            else:
                if dset.shape[2] < 1 * n_samp:
                    dset.resize(dset.shape[2] + n_samp, axis=2)  # resize to fit new data
                dset[:, :, 0: n_samp] = data_ptr

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
            filename = file_obj.filename
            self.close_file(file_obj)

        return filename


if __name__ == '__main__':
    antennas = 16
    pols = 2
    samples = 8
    runs = 2

    path="/home/andrea/"
    fm = RawFormatFileManager(root_path=path, daq_mode=FileDAQModes.Burst)
    fm.set_metadata(n_antennas=antennas, n_pols=pols, n_samples=samples)
    # data = fm.read_data(timestamp=None, object_id=1, antennas=range(0, antennas), polarizations=range(0, pols), n_samples=samples)

    raw_file_mgr = RawFormatFileManager(root_path="/home/andrea/", daq_mode=FileDAQModes.Burst)
    raw_file_mgr.set_metadata(n_antennas=antennas, n_pols=pols, n_samples=samples)
    data = numpy.arange(0, antennas * pols * samples, dtype=b'int8')
    for run in range(0, runs):
        raw_file_mgr.ingest_data(append=True, timestamp=0, tile_id=1, data_ptr=data, sampling_time=0)

    # data = fm.read_data(timestamp=None, tile_id=1, antennas=range(0, 1), polarizations=range(0, 1),
    #                     n_samples=samples)
    # print(data)