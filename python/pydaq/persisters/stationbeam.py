from __future__ import print_function
from builtins import str
from builtins import range
from pydaq.persisters.aavs_file import *
from pydaq.persisters.utils import *
import numpy
import logging
from scapy import packet


class StationBeamFormatFileManager(AAVSFileManager):
    """
    A subclass of AAVSFileManager for StationBeam files. Inherits all behaviour and implements abstract functionality.
    """
    def __init__(self, root_path=None, daq_mode=None, data_type=b'complex16'):
        """
        Constructor for Beamformed file manager.
        :param root_path: Directory where all file operations will take place.
        :param daq_mode: The DAQ type (e.g. normal (none), integrated, etc.
        :param data_type: The data type for all data in this file set/sequence.
        """
        super(StationBeamFormatFileManager, self).__init__(root_path=root_path,
                                                    file_type=FileTypes.StationBeamformed,
                                                    daq_mode=daq_mode,
                                                    data_type=data_type)

        self.metadata_list = ["timestamp","n_pols","n_chans","n_samples","n_blocks","type",
                              "data_type","date_time","data_mode","ts_start","ts_end","station_id"]

        # second set of initialization values
        self.resize_factor = 1024
        self.station_id = 1
        self.n_pols = 2
        self.n_chans = 512
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

        stb_group = file_obj.create_group("stationbeam_")
        stb_group.create_dataset("data", (n_pols, 0, n_chans),
                                 chunks=(n_pols, self.resize_factor, n_chans),
                                 dtype=self.data_type,
                                 maxshape=(n_pols, None, n_chans))

        timestamp_grp = file_obj.create_group("sample_timestamps")
        timestamp_grp.create_dataset("data", (0, 1), chunks=(self.resize_factor, 1),
                                     dtype=numpy.float64, maxshape=(None, 1))

        packet_grp = file_obj.create_group("sample_packets")
        packet_grp.create_dataset("data", (0, 1), chunks=(self.resize_factor, 1),
                                  dtype = numpy.uint32, maxshape = (None, 1))

        file_obj.flush()

    def set_metadata(self, timestamp=0, n_pols=2, n_chans=512, n_samples=0, n_blocks=0, date_time="", data_mode=""):
        """
        A method that has to be called soon after any AAVS File Manager object is created, to let us know what config
        to be used in all subsequent operations.
        :param n_pols: The number of polarizations for this file set.
        :param n_chans: The number of channels for this file set.
        :param n_samples: The number of samples to expect in operations for this file set.
        :param n_blocks: The number of blocks to start this file set.
        :param timestamp: The timestamp for this file set.
        :param date_time: The date time string for this file set.
        :param data_mode: The data mode for this file set (unused).
        :return:
        """
        self.timestamp = timestamp
        self.n_pols = n_pols
        self.n_chans = n_chans
        self.n_samples = n_samples
        self.n_blocks = n_blocks
        self.date_time = date_time
        self.data_mode = data_mode

    def load_metadata(self, file_obj):
        """
        Load metadata for a stationbeam file type.
        :param file_obj: The stationbeam file object.
        :return:
        """
        self.main_dset = file_obj["root"]
        self.n_pols = self.main_dset.attrs['n_pols']
        self.n_chans = self.main_dset.attrs['n_chans']
        self.n_samples = self.main_dset.attrs['n_samples']
        self.n_blocks = self.main_dset.attrs['n_blocks']
        self.date_time = self.main_dset.attrs['date_time']
        self.ts_start = self.main_dset.attrs['ts_start']
        self.ts_end = self.main_dset.attrs['ts_end']
        self.station_id = self.main_dset.attrs['station_id']
        if 'nsamp' in list(self.main_dset.attrs.keys()):
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

        metadata_dict = self.get_metadata(timestamp=timestamp, object_id=station_id)
        if channels is None:
            channels = list(range(0, metadata_dict["n_chans"]))
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
                                                             object_id=station_id,
                                                             query_ts_start=start_ts,
                                                             query_ts_end=end_ts)

        if sample_based_read:
            result = self.get_file_partition_indexes_to_read_given_samples(timestamp=timestamp,
                                                                           object_id=station_id,
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
                  beams = None, sample_offset=0, partition_id=None):
        """
        A helper for the read_data() method. This method performs a read operation based on a sample offset and a
        requested number of samples to be read. If the read_data() method has been called with start and end timestamps
        instead, these would have been converted to the equivalent sample offset and requested number of samples, before
        this method is called.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param station_id: The tile identifier for a file batch.
        :param channels: An array with a list of channels to be read.
        :param polarizations: An array with a list of polarizations to be read.
        :param n_samples: The number of samples to be read.
        :param beams: An array with a list of beams to be read. If None, all beams in the file are read.
        :param sample_offset: An offset, in samples, from which the read operation should start.
        :param partition_id: Indicates which partition for the batch is being read.
        :return:
        """
        metadata_dict = self.get_metadata(timestamp=timestamp, object_id=station_id)
        if channels is None:
            channels = list(range(0, metadata_dict["n_chans"]))
        if polarizations is None:
            polarizations = list(range(0, metadata_dict["n_pols"]))

        try:
            file_obj = self.load_file(timestamp=timestamp, object_id=station_id, partition=partition_id, mode='r')
            if file_obj is not None:
                temp_dset = file_obj["root"]
            else:
                logging.error("Invalid file timestamp, returning empty buffer.")
                # return output_buffer
                return [], []
        except Exception as e:
            logging.error("Can't load file for data reading: ", e.message)
            raise

        output_buffer = numpy.zeros([len(polarizations), n_samples, len(channels)], dtype=self.data_type)
        timestamp_buffer = numpy.zeros([n_samples, 1], dtype=numpy.float)
        packets_buffer = numpy.zeros([n_samples, 1], dtype=numpy.uint32)

        data_flushed = False
        while not data_flushed:
            try:
                stb_group = file_obj["stationbeam_"]
                dset = stb_group["data"]
                nof_items = dset.shape[1]

                timestamp_grp = file_obj["sample_timestamps"]
                ts_dset = timestamp_grp["data"]

                if sample_offset+n_samples>nof_items:
                    output_buffer[:, :, :] = dset[polarizations,:,:][:,0:nof_items,:][:,:,channels]
                    timestamp_buffer[0:nof_items] = ts_dset[0:nof_items]
                else:
                    output_buffer[:, :, :] = dset[polarizations, :, :][:, sample_offset:sample_offset + n_samples, :][:, :, channels]
                    timestamp_buffer[:] = ts_dset[sample_offset:sample_offset + n_samples]

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

    def _write_data(self, append_mode=False, timestamp=None, buffer_timestamp=None, data_ptr=None, sampling_time=None, object_id=0,
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
        file_obj = None
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
            n_samp = self.main_dset.attrs['n_samples']
            n_blocks = self.main_dset.attrs['n_blocks']
            n_chans = self.main_dset.attrs['n_chans']

            self.main_dset.attrs['timestamp'] = timestamp
            stb_group = file_obj["stationbeam_"]
            dset = stb_group["data"]

            # Pre-format data
            pol_data = numpy.reshape(data_ptr, (n_pols, n_samp, n_chans))

            if append_mode:
                ds_last_size = n_blocks * n_samp
                if dset.shape[1] < (n_blocks + 1) * n_samp:
                    dset.resize(dset.shape[1] + self.resize_factor, axis=1)  # resize to fit new data
                dset[:, ds_last_size: ds_last_size + n_samp, :] = pol_data
            else:
                if dset.shape[1] < 1 * n_samp:
                    dset.resize(dset.shape[1] + self.resize_factor, axis=1)  # resize to fit new data
                dset[:, 0: n_samp, :] = pol_data

            self.generate_timestamps(append_mode=append_mode,
                                     file_obj=file_obj,
                                     buffer_timestamp=buffer_timestamp,
                                     timestamp=timestamp,
                                     timestamp_pad=timestamp_pad,
                                     n_samp=n_samp,
                                     sampling_time=sampling_time,
                                     n_blocks=n_blocks)

            # write packets
            sample_packets_list = numpy.zeros((n_samp, 1), dtype=numpy.uint32)
            sample_packets_list[:] = sample_packets
            sample_packets_list = sample_packets_list.flatten()
            packets_grp = file_obj["sample_packets"]
            dset = packets_grp["data"]

            if append_mode:
                ds_last_size = n_blocks * n_samp
                if dset.shape[0] < (n_blocks + 1) * n_samp:
                    dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data
                dset[ds_last_size:ds_last_size + n_samp, 0] = sample_packets_list
            else:
                if dset.shape[0] < 1 * n_samp:
                    dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data
                dset[0: n_samp, 0] = sample_packets_list

            file_obj.flush()
            filename = file_obj.filename
            self.close_file(file_obj)

        return filename


if __name__ == '__main__':
    channels = 8
    pols = 2
    samples = 16
    runs = 2
    times = numpy.zeros(runs)

    print("ingesting...")
    beam_file_mgr = StationBeamFormatFileManager(root_path="/home/andrea", daq_mode=FileDAQModes.Integrated)
    # meta = beam_file_mgr.get_metadata(timestamp=None, object_id=1)
    beam_file_mgr.set_metadata(n_chans=channels,
                               n_pols=pols,
                               n_samples=samples)

    a = numpy.arange(0, channels * samples * pols, dtype=numpy.int8)
    b = numpy.zeros(channels * samples * pols, dtype=numpy.int8)
    data = numpy.array([(a[i], b[i]) for i in range(0, len(a))], dtype=beam_file_mgr.data_type)

    for run in range(0, runs):
        beam_file_mgr.ingest_data(append=False,
                                  data_ptr=data,
                                  timestamp=0,
                                  station_id=1,
                                  sampling_time=0.1,
                                  sample_packets=4)

    data, timestamps, packets = beam_file_mgr.read_data(timestamp=0,
                            station_id=1,
                            channels=list(range(0, channels)),
                            polarizations=list(range(0, pols)),
                            n_samples=2,
                            sample_offset=-2)
    print(timestamps)
    print(data)
    print(packets)


