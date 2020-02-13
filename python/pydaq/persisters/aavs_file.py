import h5py
import fnmatch
import os
import sys
import logging
from abc import abstractmethod
import ntpath
from contextlib import contextmanager

from lockfile import FileLock
from pydaq.persisters.definitions import *
from pydaq.persisters.utils import *


class AAVSFileManager(object):
    """ A superclass for all DAQ persister operations. This class acts primarily as a file manager for AAVS data
    files. For instance, creation, closing, opening of files (HDF5), management of partitions of the same file,
    integrity checks on files, creation and updating of metadata. This class also contains method signatures for
    read/write operations which are then implemented in subclasses."""

    # A constant value for the approximate size limit to file partitions. If a file partition gets bigger than this size
    # following an append operation, the next append operation will be placed in a new partition.
    FILE_SIZE_GIGABYTES = 2.0  # 2.0GB

    def __init__(self, root_path=None, file_type=None, daq_mode=None, data_type=None, use_locks=False):
        """
        Constructor for the AAVSFileManager
        :param root_path: Directory where all file operations will take place.
        :param file_type: The file type for this manager (RAW, CHANNEL or BEAM)
        :param daq_mode: The DAQ type (e.g. normal (none), integrated, etc.
        :param data_type: The data type for all data in this file set/sequence.
        :param use_locks: Flag to indicate whether file locks should be used (for safe operations), set to False by
        default. In the default case, clients must make sure no parallel accesses are made.
        """

        self.metadata_list = []

        # check root path and set default if no path is provided
        if root_path is None:
            self.root_path = '.'
        else:
            self.root_path = root_path

        # set locks setting
        self.use_locks = use_locks

        if daq_mode is None:
            self.daqmode = FileDAQModes.Burst
        else:
            self.daqmode = daq_mode

        # check data type and set default if no type is provided
        if data_type is None:
            self.data_type = complex_8t
            self.data_type_name = b'complex'
        elif data_type in DATA_TYPE_MAP.keys():
            self.data_type = DATA_TYPE_MAP[data_type]
            self.data_type_name = data_type
        else:
            logging.error("Invalid data type specified")
            return

        self.main_dset = None
        self.type = file_type

    @abstractmethod
    def configure(self, file_obj):
        """
        Abstract method for file configuration. To be implemented by all subclasses.
        :param file_obj: The file object to be configured.
        :return:
        """
        pass

    @abstractmethod
    def read_data(self, timestamp=0, object_id=0, channels=None, antennas=None, polarizations=None, n_samples=0,
                  sample_offset=0, start_ts=None, end_ts=None, **kwargs):
        """
        Abstract method to read data from a file for a given query. To be implemented by all subclasses. Queries can be
        done based on sample indexes, or timestamps.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param object_id: The tile identifier for a file batch.
        :param channels: An array with a list of channels to be read.
        :param antennas: An array with a list of antennas to be read.
        :param polarizations: An array with a list of polarizations to be read.
        :param n_samples: The number of samples to be read.
        :param sample_offset: An offset, in samples, from which the read operation should start.
        :param start_ts: A start timestamp for a read query based on timestamps.
        :param end_ts: An end timestamp for a ready query based on timestamps.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        pass

    @abstractmethod
    def _write_data(self, append_mode=False, data_ptr=None, timestamp=None, buffer_timestamp=None, sampling_time=None,
                    object_id=0, partition_id=0, timestamp_pad=0, **kwargs):
        """
        Abstract method to write data to a file. To be implemented by all subclasses.
        :param append_mode: True if appending to an existing file, False for new files (or overwritten)
        :param data_ptr: A data array.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be written to.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param sampling_time: Time per sample.
        :param object_id: The tile identifier for a file batch.
        :param partition_id: When creating the file, this will indicate which partition for the batch is being created.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        pass

    def ingest_data(self, data_ptr=None, timestamp=None, append=False, sampling_time=0, buffer_timestamp=None,
                    **kwargs):
        """
        Data ingestion operation for writing/appending.
        :param data_ptr: A data array.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be ingested to.
        :param append: If true, operation is to append, not to create a new file/overwrite.
        :param sampling_time: Time per sample.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param kwargs: dictionary of keyword arguments e.g. tile_id, channel_id etc.
        :return:
        """

        # for correlator files
        if 'channel_id' in kwargs.keys():
            if kwargs["channel_id"] is not None:
                object_id = kwargs["channel_id"]
                self.channel_id = kwargs["channel_id"]

        if 'tile_id' in kwargs.keys():
            if kwargs["tile_id"] is not None:
                object_id = kwargs["tile_id"]
                self.tile_id = kwargs["tile_id"]

        # for stationbeam files
        if 'station_id' in kwargs.keys():
            if kwargs["station_id"] is not None:
                object_id = kwargs["station_id"]
                self.station_id = kwargs["station_id"]

        self.tsamp = sampling_time

        if append:
            n_parts = self.file_partitions(timestamp=timestamp, object_id=object_id)
            if n_parts > 0:
                final_timestamp = self.file_final_timestamp(timestamp=timestamp, object_id=object_id, partition=n_parts - 1)
            else:
                final_timestamp = 0.0
        else:
            final_timestamp = 0.0

        if final_timestamp > 0.0:
            timestamp_pad = final_timestamp + sampling_time
        else:
            timestamp_pad = final_timestamp

        # check file size
        current_size = self.file_size(timestamp=timestamp, object_id=object_id)
        if current_size < self.FILE_SIZE_GIGABYTES:
            if append and (n_parts>=0):
                return self._write_data(append_mode=True,
                                        data_ptr=data_ptr,
                                         timestamp=timestamp,
                                         sampling_time=sampling_time,
                                         buffer_timestamp=buffer_timestamp,
                                         object_id=object_id,
                                         partition_id=n_parts,
                                         timestamp_pad=timestamp_pad)
            else:
                return self._write_data(append_mode=False,
                                        data_ptr=data_ptr,
                                        timestamp=timestamp,
                                        buffer_timestamp=buffer_timestamp,
                                        sampling_time=sampling_time,
                                        object_id=object_id,
                                        partition_id=0,
                                        timestamp_pad=timestamp_pad)
        else:
            last_partition = self.file_partitions(timestamp=timestamp, object_id=object_id)
            final_timestamp = self.file_final_timestamp(timestamp=timestamp, object_id=object_id)
            new_partition = last_partition + 1
            return self._write_data(append_mode=False,
                                    data_ptr=data_ptr,
                                    timestamp=timestamp,
                                    buffer_timestamp=buffer_timestamp,
                                    sampling_time=sampling_time,
                                    object_id=object_id,
                                    partition_id=new_partition,
                                    timestamp_pad=final_timestamp + sampling_time)

    def check_root_integrity(self,file_obj):
        """
        Method to check if all metadata of a file is well structured.
        :param file_obj: An HDF5 file object.
        :return: True, if integrity is OK.
        """
        integrity = True
        try:
            file_obj.require_dataset("root", shape=(1,), dtype='float16', exact=True)
            file_dset = file_obj.get("root", default=None)
            if file_dset is not None:
                attrs_found = file_dset.attrs.items()
                dict_attrs_found = dict(attrs_found)

                if len(dict_attrs_found) >= len(self.metadata_list):
                    for metadata_attr in self.metadata_list:
                        if metadata_attr not in dict_attrs_found:
                            if metadata_attr is not "tsamp": # this check is only for backward compatibility
                                integrity = False
                else:
                    integrity = False
            else:
                integrity = False
        except Exception as ex:
            integrity = False
        finally:
            return integrity

    @abstractmethod
    def load_metadata(self, file_obj):
        """
        An abstract method, where metadata for a particular file is loaded in the file manager.
        :param file_obj: The file to be accessed for loading metadata.
        :return:
        """
        pass

    def get_metadata(self, timestamp=None, object_id=None):
        """
        Returns the metadata for a file batch, given by file timestamp and tile id.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be retrieved).
        :param object_id: The tile identifier for a file batch.
        :return: A metadata dictionary.
        """

        file_obj = self.load_file(timestamp=timestamp, object_id=object_id, mode='r')
        metadata_dict = None

        if file_obj is not None:
            metadata_dict = {}

            if file_obj:
                with self.file_exception_handler(file_obj=file_obj):
                    file_dset = file_obj.get("root", default=None)
                    if file_dset is not None:
                        attrs_found = file_dset.attrs.items()
                        dict_attrs_found = dict(attrs_found)

                        for metadata_attr in self.metadata_list:
                            metadata_dict[metadata_attr] = dict_attrs_found[metadata_attr]

                        #only for backward compatibility
                        if self.tsamp is not None:
                            metadata_dict['tsamp'] = self.tsamp

                    self.close_file(file_obj=file_obj)

        return metadata_dict

    def file_final_timestamp(self, timestamp=None, object_id=None, partition=None):
        """
        For a particular timestamp and tile id combination, this method returns the timestamp of the last stored sample
        of the last file partition.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be retrieved).
        :param object_id: The tile identifier for a file batch.
        :param partition: The particular partition to open, if None, the max partition returned by file_partitions is
        used.
        :return:
        """
        file_obj = self.load_file(timestamp=timestamp, object_id=object_id, mode='r', partition=partition)
        ts_end = 0

        if file_obj is not None:
            with self.file_exception_handler(file_obj=file_obj):
                ts_end = self.ts_end
                self.close_file(file_obj=file_obj)

        return ts_end

    def file_partitions(self, timestamp=None, object_id=None):
        """
        Returns the largest partition ID (number of existing partitions) for a file set (based on timestamp and tile ID)
        :param timestamp: file timestamp, if None, latest timestamp in directory is fetched
        :param object_id: object_id for files to fetch, default of 0
        :return: Largest partition ID, or -1 if file set does not exist
        """

        filename_prefix, filename_mode_prefix = self.get_prefixes()
        largest_partition_id = -1
        latest_file_time = -1
        full_filename = None

        date_time = None if timestamp is None else get_date_time(timestamp=timestamp)
        object_id_str = '' if object_id is None else str(object_id)

        for file in os.listdir(self.root_path):
            if date_time is not None:
                srch_string = filename_prefix + filename_mode_prefix + object_id_str + "_" + str(date_time) + "_" + "*" + ".hdf5"
            else:
                srch_string = filename_prefix + filename_mode_prefix + object_id_str + "_" + "*" + ".hdf5"

            if fnmatch.fnmatch(file, srch_string):
                file_obj_filename = ntpath.basename(file)
                file_object_id = file_obj_filename.split('_')[2]

                # first get file batch with latest timestamp
                if int(file_object_id) == object_id:
                    file_time = int(file.split('_')[FILE_NAME_MAP[b'time1']] + file.split('_')[FILE_NAME_MAP[b'time2']])
                    if file_time >= latest_file_time:
                        latest_file_time = file_time

                        # then get file with largest partition
                        file_partition = file_obj_filename.split('_')[FILE_NAME_MAP[b'partition']]
                        file_partition = int(file_partition.replace('.hdf5', ''))
                        if file_partition >= largest_partition_id:
                            largest_partition_id = file_partition
                            full_filename = os.path.join(self.root_path, file)

        return largest_partition_id

    def file_size(self, timestamp=None, object_id=0):
        """
        Returns the size of the HDF5 file in gigabytes.
        :param timestamp: file timestamp, if None, latest timestamp in directory is fetched
        :param object_id: object_id for files to fetch, default of 0
        :return: Size in gigabytes, 0.0 if file does not exist.
        """
        gigabytes_in_file = 0.0
        file_obj = self.load_file(timestamp=timestamp, object_id=object_id)

        if file_obj is not None:
            with self.file_exception_handler(file_obj=file_obj):
                file_bytes = os.path.getsize(file_obj.filename)
                gigabytes_in_file = file_bytes * 1e-9
            self.close_file(file_obj=file_obj)

        return gigabytes_in_file

    def get_total_samples_in_all_partitions(self, timestamp=None, tile_id=0):
        # Get number of partitions
        nof_partitions = self.file_partitions(timestamp=timestamp, object_id=tile_id) + 1

        # Sum number of samples in each partition
        total_samples = 0
        for partition_id in range(0,nof_partitions):
            file_obj = self.load_file(timestamp=timestamp, object_id=tile_id, partition=0)
            total_samples += self.n_samples * self.n_blocks
            self.close_file(file_obj=file_obj)

        return total_samples

    def get_file_partition_indexes_to_read_given_samples(self, timestamp=None, object_id=0, query_samples_read=0,
                                                         query_sample_offset=0):
        """
        Returns an array of the form: [{"partition":partition,"indexes":[partition_start_idx,partition_end_idx]}]
        which contains the indexes range of which partitions need to be included when reading from a set of files
        (split into partitions) for a particular start and end sample index
        :param timestamp: Mother timestamp of the file series
        :param object_id: The object_id e.g. tile ID to pick files for
        :param query_samples_read: The number of samples to read
        :param query_sample_offset: The start sample index of interest
        :return:
        """

        # get total samples
        total_samples_in_all_files = self.get_total_samples_in_all_partitions(timestamp=timestamp, tile_id=object_id)

        if query_sample_offset < 0:  # if reading from the back
            query_sample_offset = total_samples_in_all_files + query_sample_offset

        if query_sample_offset + query_samples_read > total_samples_in_all_files:
            query_samples_read = query_samples_read - (
                        (query_sample_offset + query_samples_read) - total_samples_in_all_files)

        # Get number of partitions
        nof_partitions = self.file_partitions(timestamp=timestamp, object_id=object_id) + 1

        # Get number of samples in each partition
        file_obj = self.load_file(timestamp=timestamp, object_id=object_id, partition=0)
        samples_per_partition = self.n_samples * self.n_blocks

        # Get partition number given file offset
        start_partition = int(query_sample_offset / samples_per_partition)
        end_partition = int((query_sample_offset + query_samples_read) / (samples_per_partition + 1))

        # Check whether partitions exist
        if end_partition >= nof_partitions or start_partition >= nof_partitions:
            return []

        # Get number of samples in last partition
        if end_partition == start_partition:
            samples_in_last_partition = self.n_samples * self.n_blocks
            self.close_file(file_obj=file_obj)
        else:
            self.close_file(file_obj=file_obj)
            file_obj = self.load_file(timestamp=timestamp, object_id=object_id, partition=end_partition)
            samples_in_last_partition = self.n_samples * self.n_blocks
            self.close_file(file_obj=file_obj)

        # find starting offset of start partition
        if start_partition > 0:
            samples_passed = samples_per_partition * start_partition
        else:
            samples_passed = 0
        start_idx_in_start_partition = query_sample_offset - samples_passed

        # find ending offset of end partition
        if end_partition > 0:
            samples_passed = samples_per_partition * end_partition
        else:
            samples_passed = 0
        end_idx_in_end_partition = query_sample_offset + query_samples_read - samples_passed

        # if we ask for too many samples from last partition, truncate end index
        if end_idx_in_end_partition > samples_in_last_partition:
            end_idx_in_end_partition = samples_in_last_partition

        # set up partition list
        if start_partition == end_partition:
            return [{"partition": start_partition, "indexes": [start_idx_in_start_partition, end_idx_in_end_partition]}]

        partition_list = [
            {"partition": start_partition, "indexes": [start_idx_in_start_partition, samples_per_partition]}]

        for mid_partition in range(start_partition + 1, end_partition):
            partition_list.append(
                {"partition": start_partition, "indexes": [0, samples_per_partition]})

        if end_partition != start_partition and end_idx_in_end_partition != 0:
            partition_list.append({"partition": end_partition, "indexes": [0, end_idx_in_end_partition]})

        return partition_list

    def get_file_partition_indexes_to_read_given_ts(self, timestamp=None, object_id=0, query_ts_start=0, query_ts_end=0):
        """
        Returns an array of the form: [{"partition":partition,"indexes":[partition_start_idx,partition_end_idx]}]
        which contains the indexes range of which partitions need to be included when reading from a set of files
        (split into partitions) for a particular start and end timestamp
        :param timestamp: Mother timestamp of the file series
        :param object_id: The tile ID to pick files for
        :param query_ts_start: The start timestamp of interest
        :param query_ts_end: The end timestamp of interest
        :return:
        """
        max_partition = self.file_partitions(timestamp=timestamp, object_id=object_id)

        partition_list = []

        for partition in range(0, max_partition + 1):
            file_obj = self.load_file(timestamp=timestamp, object_id=object_id, partition=partition)
            with self.file_exception_handler(file_obj=file_obj):
                if self.ts_start <= query_ts_end:  # we need it, so find indexes where timestamp window matches
                    nof_items = self.n_samples * self.n_blocks
                    timestamp_buffer = numpy.empty((nof_items, 1))
                    timestamp_grp = file_obj["sample_timestamps"]
                    dset = timestamp_grp["data"]
                    timestamp_buffer[0:nof_items] = dset[0:nof_items]

                    try:
                        partition_start_idx = numpy.where(timestamp_buffer >= query_ts_start)[0][0]
                        try:
                            partition_end_idx = (numpy.where(timestamp_buffer > query_ts_end)[0][0]) - 1
                        except:
                            # no index, so we take all of the rest of this partition
                            partition_end_idx = timestamp_buffer.size - 1

                        partition_list.append(
                            {"partition": partition, "indexes": [partition_start_idx, partition_end_idx]})
                    except:
                        pass
                self.close_file(file_obj=file_obj)
        return partition_list

    def load_file(self, timestamp=None, object_id=0, mode='r', partition=None):
        """
        Loads a file for a particular timestamp, object id, load mode, and particular partition.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be retrieved).
        :param object_id: The tile identifier for a file batch.
        :param mode: The HDF5 mode string for loading 'r', 'r+', 'w'
        :param partition: The particular partition to open, if None, the max partition returned by file_partitions is
        used.
        :return: An HDF5 file object if no errors and file exists, None otherwise.
        """
        filename_prefix, filename_mode_prefix = self.get_prefixes()
        full_filename = None
        file_obj = None

        load_partition = self.file_partitions(timestamp=timestamp, object_id=object_id) if partition is None else partition
        date_time = None if timestamp is None else get_date_time(timestamp=timestamp)
        object_id_str = '' if object_id is None else str(object_id)

        if date_time is not None:
            full_filename = os.path.join(self.root_path, filename_prefix + filename_mode_prefix + object_id_str + "_" +
                                         str(date_time) + "_" + str(load_partition) + ".hdf5")
        else:
            latest_file_time = -1
            for file in os.listdir(self.root_path):
                if fnmatch.fnmatch(file, filename_prefix + filename_mode_prefix + object_id_str + "_" + "*" + str(load_partition) + ".hdf5"):
                    file_obj_filename = ntpath.basename(file)
                    file_object_id = file_obj_filename.split('_')[FILE_NAME_MAP[b'objectid']]
                    if int(file_object_id) == object_id:
                        file_time = int(file.split('_')[FILE_NAME_MAP[b'time1']] + file.split('_')[FILE_NAME_MAP[b'time2']])
                        if file_time > latest_file_time:
                            latest_file_time = file_time
                            full_filename = os.path.join(self.root_path, file)

        if full_filename is not None:
            if os.path.isfile(full_filename):
                file_obj = self.open_file(full_filename, mode=mode)
                with self.file_exception_handler(file_obj=file_obj):
                    if self.check_root_integrity(file_obj=file_obj):
                        self.load_metadata(file_obj=file_obj)
                    else:
                        logging.error("File root integrity check failed, can't load file.")
        else:
            logging.error("Attempted to load a file which does not exist. No file object returned.")

        return file_obj

    def create_file(self, timestamp=None, object_id=0, partition_id=0):
        """
        Creates a file for a particular timestamp, tile id, and particular partition.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be retrieved).
        :param object_id: The tile identifier for a file batch.
        :param partition_id: The particular partition to open, if None, the max partition returned by file_partitions is
        used.
        :return: An HDF5 file object if no errors occurred.
        """
        filename_prefix, filename_mode_prefix = self.get_prefixes()

        if timestamp is None:
            date_time = None
        else:
            date_time = get_date_time(timestamp=timestamp)

        if object_id is None:
            object_id_str = ''
        else:
            object_id_str = str(object_id)

        full_filename = os.path.join(self.root_path, filename_prefix + filename_mode_prefix + object_id_str + "_" +
                                     date_time + "_" + str(partition_id) + ".hdf5")

        # Check if file exists, delete if it does (we want to create here!)
        for file_obj in os.listdir(os.path.join(self.root_path)):
            if fnmatch.fnmatch(file_obj, os.path.join(self.root_path, filename_prefix + filename_mode_prefix +
                                                                      object_id_str + "_" + date_time + "_" +
                                                                      str(partition_id) + ".hdf5")): os.remove(file_obj)

        first_full_filename = os.path.join(self.root_path, filename_prefix + filename_mode_prefix + object_id_str +
                                           "_" + date_time + "_" + str(partition_id) + ".hdf5")

        file_obj = self.open_file(full_filename, 'w')
        os.chmod(first_full_filename, 0o776)

        with self.file_exception_handler(file_obj=file_obj):
            self.main_dset = file_obj.create_dataset("root", (1,), chunks=True, dtype='float16')
            self.n_blocks = 0
            self.main_dset.attrs['timestamp'] = timestamp
            self.main_dset.attrs['date_time'] = date_time

            if hasattr(self,"n_antennas"):
                self.main_dset.attrs['n_antennas'] = self.n_antennas
            if hasattr(self, "n_pols"):
                self.main_dset.attrs['n_pols'] = self.n_pols
            if hasattr(self, "n_beams"):
                self.main_dset.attrs['n_beams'] = self.n_beams
            if object_id is not None:
                if self.type == FileTypes.Raw:
                    self.main_dset.attrs['tile_id'] = object_id
                elif self.type == FileTypes.Channel:
                    self.main_dset.attrs['tile_id'] = object_id
                elif self.type == FileTypes.Beamformed:
                    self.main_dset.attrs['tile_id'] = object_id
                elif self.type == FileTypes.Correlation:
                    self.main_dset.attrs['tile_id'] = object_id
                elif self.type == FileTypes.StationBeamformed:
                    self.main_dset.attrs['station_id'] = object_id
            if hasattr(self, "n_chans"):
                self.main_dset.attrs['n_chans'] = self.n_chans
            if hasattr(self, "n_samples"):
                self.main_dset.attrs['n_samples'] = self.n_samples
            if hasattr(self, "n_blocks"):
                self.main_dset.attrs['n_blocks'] = 0
            if hasattr(self, "type"):
                self.main_dset.attrs['type'] = self.type.value
            if hasattr(self, "data_type_name"):
                self.main_dset.attrs['data_type'] = self.data_type_name
            if hasattr(self, "data_mode"):
                self.main_dset.attrs['data_mode'] = self.data_mode
            if timestamp is not None:
                self.main_dset.attrs['ts_start'] = timestamp
                self.main_dset.attrs['ts_end'] = timestamp
            if hasattr(self, "n_baselines"):
                self.main_dset.attrs['n_baselines'] = self.n_baselines
            if hasattr(self, "n_stokes"):
                self.main_dset.attrs['n_stokes'] = self.n_stokes
            if hasattr(self, "channel_id"):
                self.main_dset.attrs['channel_id'] = self.channel_id
            if hasattr(self, 'tsamp'):
                self.main_dset.attrs['tsamp'] = self.tsamp
            self.configure(file_obj)

        return file_obj

    def close_file(self, file_obj):
        """
        Closes a file object in use by this manager.
        :param file_obj: The file object to close.
        :return:
        """
        filename = file_obj.filename
        first_full_filename = filename

        if self.use_locks:
            lock = FileLock(first_full_filename)

        file_obj.close()

        if self.use_locks:
            lock.release()

    def open_file(self, filename, mode='r'):
        """
        This file manager will open a file in a specific mode.
        :param filename: Filename (full path) of file to be opened.
        :param mode: HDF5 mode string for file opening 'r', 'r+', 'w'
        :return:
        """
        first_full_filename = filename

        if self.use_locks:
            lock = FileLock(first_full_filename)
            lock.acquire(timeout=None)

        file_obj = h5py.File(filename, mode)
        return file_obj

    def get_prefixes(self):
        """
        Given the file type and DAQ mode set up for this file manager, this method returns the appropriate filename
        prefix.
        :return: File name prefix.
        """
        filename_prefix = ""
        filename_mode_prefix = ""

        if self.type == FileTypes.Raw:
            filename_prefix = "raw_"
        elif self.type == FileTypes.Channel:
            filename_prefix = "channel_"
        elif self.type == FileTypes.Beamformed:
            filename_prefix = "beamformed_"
        elif self.type == FileTypes.Correlation:
            filename_prefix = "correlation_"
        elif self.type == FileTypes.StationBeamformed:
            filename_prefix = "stationbeam_"

        if self.daqmode == FileDAQModes.Integrated:
            filename_mode_prefix = "integ_"
        elif self.daqmode == FileDAQModes.Continuous:
            filename_mode_prefix = "cont_"
        elif self.daqmode == FileDAQModes.Burst:
            filename_mode_prefix = "burst_"

        return filename_prefix, filename_mode_prefix

    def generate_timestamps(self, append_mode=False, file_obj=None, buffer_timestamp=None,timestamp=None,timestamp_pad=None,n_samp=None,sampling_time=None,n_blocks=None):
        # adding timestamp per sample
        if buffer_timestamp is not None:
            padded_timestamp = buffer_timestamp
        else:
            padded_timestamp = timestamp

        padded_timestamp += timestamp_pad  # add timestamp pad from previous partitions

        if timestamp_pad > 0:
            padded_timestamp = padded_timestamp - timestamp
            # since it has already been added for append by the timestap_pad value

        sample_timestamps = numpy.zeros((n_samp, 1), dtype=float)
        if sampling_time not in [0, None]:
            sample_timestamps = numpy.asarray(step_range(low=0, up=sampling_time * n_samp, leng=n_samp))
            sample_timestamps = sample_timestamps + padded_timestamp
            sample_timestamps = sample_timestamps.tolist()
        else:
            sample_timestamps = numpy.asarray(step_range(low=timestamp, up=timestamp, leng=n_samp))
            sample_timestamps += padded_timestamp
            sample_timestamps = sample_timestamps.tolist()

        timestamp_grp = file_obj["sample_timestamps"]
        dset = timestamp_grp["data"]

        if append_mode:
            ds_last_size = n_blocks * n_samp
            if dset.shape[0] < (n_blocks + 1) * n_samp:
                dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data
            dset[ds_last_size:ds_last_size + n_samp, 0] = sample_timestamps
        else:
            # ds_last_size = n_blocks * n_samp
            if dset.shape[0] < 1 * n_samp:
                dset.resize(dset.shape[0] + self.resize_factor, axis=0)  # resize to fit new data
            dset[0: n_samp, 0] = sample_timestamps

        # set new number of written blocks
        if append_mode:
            n_blocks += 1
            self.main_dset.attrs['n_blocks'] = n_blocks
        else:
            n_blocks = 1
            self.main_dset.attrs['n_blocks'] = n_blocks

        # set new final timestamp in file
        if append_mode:
            self.main_dset.attrs['ts_end'] = sample_timestamps[-1]
        else:
            self.main_dset.attrs['ts_start'] = sample_timestamps[0]
            self.main_dset.attrs['ts_end'] = sample_timestamps[-1]

    @contextmanager
    def file_exception_handler(self, file_obj):
        try:
            yield
        except Exception as ex:
            logging.error("Exception in an operation involving HDF5 file. Closing file and releasing locks.")
            if file_obj is not None:
                self.close_file(file_obj=file_obj)
            raise
