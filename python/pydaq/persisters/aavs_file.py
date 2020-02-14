from __future__ import division
from builtins import next
from builtins import str
from builtins import range
from builtins import object
from past.utils import old_div
import datetime
import h5py
import fnmatch
import math
import os
import sys
import time
import logging
from abc import abstractmethod
import ntpath

from lockfile import FileLock
from pydaq.persisters.definitions import *


class PlotTypes(Enum):
    """" An enumerated type for all the supported plot types """
    RealPart = 1
    ImagPart = 2
    Magnitude = 3
    Power = 4
    Phase = 5
    ChanTime = 6


class AAVSFileManager(object):
    """ A superclass for all DAQ persister operations. This class acts primarily as a file manager for AAVS data
    files. For instance, creation, closing, opening of files (HDF5), management of partitions of the same file,
    integrity checks on files, creation and updating of metadata, as well as real-time monitoring of a DAQ directory
     for real-time plotting functionality. This class also contains method signatures for read/write/plot operations
     which are then implemented in subclasses."""

    # A constant value for the approximate size limit to file partitions. If a file partition gets bigger than this size
    # following an append operation, the next append operation will be placed in a new partition.
    FILE_SIZE_GIGABYTES = 4.0  # 0.1GB

    def __init__(self, root_path=None, file_type=None, daq_mode=None, data_type=None):
        """
        Constructor for the AAVSFileManager
        :param root_path: Directory where all file operations will take place.
        :param file_type: The file type for this manager (RAW, CHANNEL or BEAM)
        :param daq_mode: The DAQ type (e.g. normal (none), integrated, etc.
        :param data_type: The data type for all data in this file set/sequence.
        """

        # check root path and set default if no path is provided
        if root_path is None:
            self.root_path = '.'
        else:
            self.root_path = root_path

        if daq_mode is None:
            self.daqmode = FileDAQModes.Void
        else:
            self.daqmode = daq_mode

        # check data type and set default if no type is provided
        if data_type is None:
            self.data_type = complex_8t
            self.data_type_name = b'complex'
        elif data_type in list(DATA_TYPE_MAP.keys()):
            self.data_type = DATA_TYPE_MAP[data_type]
            self.data_type_name = data_type
        else:
            logging.error("Invalid data type specified")
            return

        self.type = file_type

        # some initialization values
        self.real_time_date_time = self._get_date_time(timestamp=0)
        self.real_time_timestamp = 0
        self.real_time_timesamp = 0
        self.main_dset = None

        # TODO: remove redundant properties
        # second set of initialization values
        self.resize_factor = 1024
        self.tile_id = 0
        self.n_antennas = 16
        self.n_pols = 2
        self.n_beams = 1
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
        self.station_id = 0
        self.tsamp = 0

    @abstractmethod
    def configure(self, file_obj):
        """
        Abstract method for file configuration. To be implemented by all subclasses.
        :param file_obj: The file object to be configured.
        :return:
        """
        pass

    @abstractmethod
    def read_data(self, timestamp=0, tile_id=0, channels=None, antennas=None, polarizations=None, n_samples=0,
                  sample_offset=0, start_ts=None, end_ts=None, **kwargs):
        """
        Abstract method to read data from a file for a given query. To be implemented by all subclasses. Queries can be
        done based on sample indexes, or timestamps.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be searched.
        :param tile_id: The tile identifier for a file batch.
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
    def _append_data(self, data_ptr=None, timestamp=None, sampling_time=None, buffer_timestamp=None, tile_id=0,
                     timestamp_pad=0, **kwargs):
        """
        Abstract method to append data to a file. To be implemented by all subclasses.
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
        pass

    @abstractmethod
    def _write_data(self, data_ptr=None, timestamp=None, buffer_timestamp=None, sampling_time=None, tile_id=0,
                    partition_id=0, timestamp_pad=0, **kwargs):
        """
        Abstract method to write data to a file. To be implemented by all subclasses.
        :param data_ptr: A data array.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be written to.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param sampling_time: Time per sample.
        :param tile_id: The tile identifier for a file batch.
        :param partition_id: When creating the file, this will indicate which partition for the batch is being created.
        :param timestamp_pad: Padded timestamp from the end of previous partitions in the file batch.
        :param kwargs: dictionary of keyword arguments
        :return:
        """
        pass

    # TODO: Clean up redundant/unused properties.
    def set_metadata(self, n_antennas=16, n_pols=2, n_beams=1, n_chans=512,
                     n_samples=0, n_baselines=0, n_stokes=4, channel_id=0, station_id=0, n_blocks=0, timestamp=0, date_time="",
                     data_mode=""):
        """
        A method that has to be called soon after any AAVS File Manager object is created, to let us know what config
        to be used in all subsequent operations.
        :param n_antennas: The number of antennas for this file set.
        :param n_pols: The number of polarizations for this file set.
        :param n_beams: The number of beams for this file set.
        :param n_chans: The number of channels for this file set.
        :param n_samples: The number of samples to expect in operations for this file set.
        :param n_baselines: The number of baselines for correlation.
        :param n_stokes: The number of stokes for correlation.
        :param channel_id: The channel ID.
        :param station_id: The station ID.
        :param n_blocks: The number of blocks to start this file set.
        :param timestamp: The timestamp for this file set.
        :param date_time: The date time string for this file set.
        :param data_mode: The data mode for this file set (unused).
        :return:
        """
        self.n_antennas = n_antennas
        self.n_pols = n_pols
        self.n_beams = n_beams
        self.n_chans = n_chans
        self.n_samples = n_samples
        self.n_baselines = n_baselines
        self.n_stokes = n_stokes
        self.n_blocks = n_blocks
        self.timestamp = timestamp
        self.date_time = date_time
        self.data_mode = data_mode
        self.n_stokes = n_stokes
        # self.channel_id = channel_id

    @staticmethod
    def time_range(low, up, leng):
        """
        This method returns a range from low to up, with a particular step size dependent on how many items should be
        in the range..
        :param low: Range start.
        :param up: Range limit.
        :param leng: Number of items in the range.
        :return: A range of values.
        """
        return numpy.linspace(low,up,leng, dtype=numpy.float128)
        # sample_timestamps = numpy.linspace(0, sampling_time * n_samp - sampling_time, leng, dtype=numpy.float128)
        # step = ((up - low) * 1.0 / leng)
        # return [low + i * step for i in xrange(leng)]

    @staticmethod
    def complex_imaginary(value):
        """
        Returns the imaginary part of a complex tuple value.
        :param value: A complex number tuple (real and imaginary parts)
        :return:
        """
        return value[1]

    @staticmethod
    def complex_real(value):
        """
        Returns the real part of a complex tuple value.
        :param value: A complex number tuple (real and imaginary parts)
        :return:
        """
        return value[0]

    @staticmethod
    def complex_phase(value):
        """
        Returns the phase of a complex tuple value.
        :param value: A complex number tuple (real and imaginary parts)
        :return:
        """
        return math.atan2(value[1], value[0])

    @staticmethod
    def complex_abs(value):
        """
        Returns the absolute (amplitude) of a complex tuple value as the square root of the PSD
        :param value: A complex number tuple (real and imaginary parts)
        :return:
        """
        return math.sqrt((value[0] ** 2) + (value[1] ** 2))

    @staticmethod
    def complex_power(value):
        """
        Returns the power of a complex tuple value.
        :param value: A complex number tuple (real and imaginary parts)
        :return:
        """
        return (value[0] ** 2) + (value[1] ** 2)

    @staticmethod
    def get_timestamp(date_time_string):
        """
        Returns a UNIX timestamp from a data/time string.
        :param date_time_string: A date/time string of the form %Y%m%d_seconds
        :return: A UNIX timestamp (seconds)
        """
        time_parts = date_time_string.split('_')
        d = datetime.datetime.strptime(time_parts[0], "%Y%m%d")  # "%d/%m/%Y %H:%M:%S"
        timestamp = time.mktime(d.timetuple())
        timestamp += int(time_parts[1])
        return timestamp

    @staticmethod
    def _get_date_time(timestamp=None):
        """
        Returns a string date/time from a UNIX timestamp.
        :param timestamp: A UNIX timestamp.
        :return: A date/time string of the form yyyymmdd_secs
        """
        if timestamp is None:
            timestamp = 0

        datetime_object = datetime.datetime.fromtimestamp(timestamp)
        hours = datetime_object.hour
        minutes = datetime_object.minute
        seconds = datetime_object.second
        full_seconds = seconds + (minutes * 60) + (hours * 60 * 60)
        full_seconds_formatted = format(full_seconds, '05')
        base_date_string = datetime.datetime.fromtimestamp(timestamp).strftime('%Y%m%d')
        full_date_string = base_date_string + '_' + full_seconds_formatted
        return full_date_string

    @staticmethod
    def range_array(start_idx, end_idx):
        """
        Creates an array with a range of values (integers)
        :param start_idx: Start of range
        :param end_idx: End of range
        :return:
        """
        if sys.version_info.major == 2:
            return list(range(start_idx, end_idx))
        elif sys.version_info.major == 3:
            return list(range(start_idx, end_idx))

    def ingest_data(self, data_ptr=None, timestamp=None, append=False, sampling_time=0,
                    buffer_timestamp=None, tile_id=0, beam_id=0, **kwargs):
        """
        Data ingestion operation for writing/appending.
        :param data_ptr: A data array.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be ingested to.
        :param append: If true, append_data() is invoked, else write_data() is invoked.
        :param sampling_time: Time per sample.
        :param buffer_timestamp: Timestamp for this particular input buffer (ahead of file timestamp).
        :param tile_id: The tile identifier for a file batch.
        :param kwargs: dictionary of keyword arguments
        :return:
        """

        # for correlator files
        if 'channel_id' in list(kwargs.keys()):
            if kwargs["channel_id"] is not None:
                tile_id = kwargs["channel_id"]
                self.channel_id = kwargs["channel_id"]

        # for stationbeam files
        if 'station_id' in list(kwargs.keys()):
            if kwargs["station_id"] is not None:
                tile_id = kwargs["station_id"]
                self.station_id = kwargs["station_id"]

        self.tsamp = sampling_time

        if append:
            n_parts = self.file_partitions(timestamp=timestamp, tile_id=tile_id)
            if n_parts > 0:
                final_timestamp = self.file_final_timestamp(timestamp=timestamp, tile_id=tile_id, partition=n_parts - 1)
            else:
                final_timestamp = 0.0
        else:
            final_timestamp = 0.0

        if final_timestamp > 0.0:
            timestamp_pad = final_timestamp + sampling_time
        else:
            timestamp_pad = final_timestamp

        # check file size
        current_size = self.file_size(timestamp=timestamp, tile_id=tile_id)
        if current_size < self.FILE_SIZE_GIGABYTES:
            if append:
                return self._append_data(data_ptr=data_ptr,
                                         timestamp=timestamp,
                                         sampling_time=sampling_time,
                                         buffer_timestamp=buffer_timestamp,
                                         tile_id=tile_id,
                                         timestamp_pad=timestamp_pad,
                                         **kwargs)
            else:
                return self._write_data(data_ptr=data_ptr,
                                        timestamp=timestamp,
                                        buffer_timestamp=buffer_timestamp,
                                        sampling_time=sampling_time,
                                        tile_id=tile_id,
                                        partition_id=0,
                                        timestamp_pad=timestamp_pad,
                                        **kwargs)
        else:
            last_partition = self.file_partitions(timestamp=timestamp, tile_id=tile_id)
            final_timestamp = self.file_final_timestamp(timestamp=timestamp, tile_id=tile_id)
            new_partition = last_partition + 1
            return self._write_data(data_ptr=data_ptr,
                                    timestamp=timestamp,
                                    buffer_timestamp=buffer_timestamp,
                                    sampling_time=sampling_time,
                                    tile_id=tile_id,
                                    partition_id=new_partition,
                                    timestamp_pad=final_timestamp + sampling_time,
                                    **kwargs)

    @staticmethod
    def check_root_integrity(file_obj):
        """
        Method to check if all metadata of a file is well structured.
        :param file_obj: An HDF5 file object.
        :return: True, if integrity is OK.
        """
        integrity = True
        # noinspection PyBroadException
        try:
            file_obj.require_dataset("root", shape=(1,), dtype='float16', exact=True)
            file_dset = file_obj.get("root", default=None)
            if file_dset is not None:
                attrs_found = list(file_dset.attrs.items())
                dict_attrs_found = dict(attrs_found)
                if len(dict_attrs_found) >= 17:
                    if "timestamp" not in dict_attrs_found:
                        integrity = False
                    if "n_antennas" not in dict_attrs_found:
                        integrity = False
                    if "n_pols" not in dict_attrs_found:
                        integrity = False
                    if "n_beams" not in dict_attrs_found:
                        integrity = False
                    if "tile_id" not in dict_attrs_found:
                        integrity = False
                    if "n_chans" not in dict_attrs_found:
                        integrity = False
                    if "n_samples" not in dict_attrs_found:
                        integrity = False
                    if "n_blocks" not in dict_attrs_found:
                        integrity = False
                    if "type" not in dict_attrs_found:
                        integrity = False
                    if "data_type" not in dict_attrs_found:
                        integrity = False
                    if "date_time" not in dict_attrs_found:
                        integrity = False
                    if "data_mode" not in dict_attrs_found:
                        integrity = False
                    if "ts_start" not in dict_attrs_found:
                        integrity = False
                    if "ts_end" not in dict_attrs_found:
                        integrity = False
                    if "n_baselines" not in dict_attrs_found:
                        integrity = False
                    if "n_stokes" not in dict_attrs_found:
                        integrity = False
                    if "channel_id" not in dict_attrs_found:
                        integrity = False
                    # if "tsamp" not in dict_attrs_found:
                    #     integrity = False
                else:
                    integrity = False
            else:
                integrity = False
        except:
            integrity = False
        finally:
            return integrity

    def get_metadata(self, timestamp=None, tile_id=None):
        """
        Returns the metadata for a file batch, given by file timestamp and tile id.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be retrieved).
        :param tile_id: The tile identifier for a file batch.
        :return: A metadata dictionary.
        """
        # if tile_id is None:
        #     tile_id = 0

        file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id, mode='r')
        metadata_dict = {}
        if file_obj:
            # noinspection PyBroadException
            try:
                metadata_dict["dataset_root"] = str(self.main_dset)
                metadata_dict["n_antennas"] = self.n_antennas
                metadata_dict["n_pols"] = self.n_pols
                metadata_dict["n_beams"] = self.n_beams
                metadata_dict["tile_id"] = self.tile_id
                metadata_dict["n_chans"] = self.n_chans
                metadata_dict["n_samples"] = self.n_samples
                metadata_dict["n_blocks"] = self.n_blocks
                metadata_dict["written_samples"] = self.n_blocks * self.n_samples
                metadata_dict["timestamp"] = float(self.timestamp)
                metadata_dict["date_time"] = str(self.date_time)
                metadata_dict["data_type"] = str(self.data_type)
                metadata_dict["n_baselines"] = self.n_baselines
                metadata_dict["n_stokes"] = self.n_stokes
                metadata_dict["channel_id"] = self.channel_id
                metadata_dict["station_id"] = self.station_id
                if self.tsamp is not None:
                    metadata_dict["tsamp"] = self.tsamp
                # metadata_dict["data_mode"] = str(self.data_mode)

                self.close_file(file_obj=file_obj)
                return metadata_dict
            except Exception:
                return "File not loaded."

    def file_final_timestamp(self, timestamp=None, tile_id=None, partition=None):
        """
        For a particular timestamp and tile id combination, this method returns the timestamp of the last stored sample
        of the last file partition.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be retrieved).
        :param tile_id: The tile identifier for a file batch.
        :param partition: The particular partition to open, if None, the max partition returned by file_partitions is
        used.
        :return:
        """
        # if tile_id is None:
        #     tile_id = 0

        file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id, mode='r', partition=partition)
        if file_obj is not None:
            ts_end = self.ts_end
            self.close_file(file_obj=file_obj)
        else:
            ts_end = 0
        return ts_end

    def file_partitions(self, timestamp=None, tile_id=None):
        """
        Returns the largest partition ID (number of existing partitions) for a file set (based on timestamp and tile ID)
        :param timestamp: file timestamp, if None, latest timestamp in directory is fetched
        :param tile_id: tile_id for files to fetch, default of 0
        :return: Largest partition ID, or -1 if file set does not exist
        """

        filename_prefix, filename_mode_prefix = self.get_prefixes()
        largest_partition_id = -1

        if timestamp is None:
            date_time = None
        else:
            date_time = self._get_date_time(timestamp=timestamp)

        if tile_id is None:
            tile_id_str = ''
        else:
            tile_id_str = str(tile_id)

        matched_files = []
        if date_time is not None:
            files = next(os.walk(self.root_path))[2]
            for file_obj in files:
                if file_obj.startswith(filename_prefix + filename_mode_prefix + tile_id_str + "_" + str(
                        date_time) + "_") and file_obj.endswith(".hdf5"):
                    matched_files.append(os.path.join(self.root_path, file_obj))
        else:
            files = next(os.walk(self.root_path))[2]
            for file_obj in files:
                if file_obj.startswith(filename_prefix + filename_mode_prefix + tile_id_str) \
                        and file_obj.endswith(".hdf5"):
                    file_obj_filename = ntpath.basename(file_obj)
                    if len(filename_mode_prefix) > 0:
                        file_tile = file_obj_filename.split('_')[2]
                    else:
                        file_tile = file_obj_filename.split('_')[1]
                    if int(file_tile) == tile_id:
                        matched_files.append(os.path.join(self.root_path, file_obj))

        latest_file_time = 0
        if len(matched_files) > 0:
            # We have a list of matched filename, sort by last modified date and get latest one
            latest_file_time = 0
            for file_obj in matched_files:
                file_obj_filename = ntpath.basename(file_obj)
                if len(filename_mode_prefix) > 0:
                    file_time1 = file_obj_filename.split('_')[3]
                    file_time2 = file_obj_filename.split('_')[4]
                else:
                    file_time1 = file_obj_filename.split('_')[2]
                    file_time2 = file_obj_filename.split('_')[3]
                file_time_str = file_time1 + file_time2
                file_time = int(file_time_str)
                if file_time > latest_file_time:
                    latest_file_time = file_time

        filtered_matched_files = []
        for file_obj in matched_files:
            file_obj_filename = ntpath.basename(file_obj)
            if len(filename_mode_prefix) > 0:
                file_time1 = file_obj_filename.split('_')[3]
                file_time2 = file_obj_filename.split('_')[4]
            else:
                file_time1 = file_obj_filename.split('_')[2]
                file_time2 = file_obj_filename.split('_')[3]
            file_time_str = file_time1 + file_time2
            file_time = int(file_time_str)
            if file_time == latest_file_time:
                filtered_matched_files.append(os.path.join(self.root_path, file_obj))

        # filter matched files for timestamp
        for file_obj in filtered_matched_files:
            file_obj_filename = ntpath.basename(file_obj)
            if len(filename_mode_prefix) > 0:
                file_partition = file_obj_filename.split('_')[5]
            else:
                file_partition = file_obj_filename.split('_')[4]
            file_partition = file_partition.replace(".hdf5", "")
            if int(file_partition) > largest_partition_id:
                largest_partition_id = int(file_partition)

        return largest_partition_id

    def file_size(self, timestamp=None, tile_id=0):
        """
        Returns the size of the data section of the HDF5 file in gigabytes.
        :param timestamp: file timestamp, if None, latest timestamp in directory is fetched
        :param tile_id: tile_id for files to fetch, default of 0
        :return: Size in gigabytes, 0.0 if file does not exist.
        """
        gigabytes_in_file = 0.0
        file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id)

        if file_obj is not None:
            file_bytes = os.path.getsize(file_obj.filename)
            gigabytes_in_file = file_bytes * 1e-9
            self.close_file(file_obj = file_obj)

        return gigabytes_in_file

    def get_total_samples_in_all_partitions(self, timestamp=None, tile_id=0):
        # Get number of partitions
        nof_partitions = self.file_partitions(timestamp=timestamp, tile_id=tile_id) + 1

        # Sum number of samples in each partition
        total_samples = 0
        for partition_id in range(0,nof_partitions):
            file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id, partition=0)
            total_samples += self.n_samples * self.n_blocks
            self.close_file(file_obj=file_obj)

        return total_samples

    def get_file_partition_indexes_to_read_given_samples(self, timestamp=None, tile_id=0, query_samples_read=0,
                                                         query_sample_offset=0):
        """
        Returns an array of the form: [{"partition":partition,"indexes":[partition_start_idx,partition_end_idx]}]
        which contains the indexes range of which partitions need to be included when reading from a set of files
        (split into partitions) for a particular start and end sample index
        :param timestamp: Mother timestamp of the file series
        :param tile_id: The tile ID to pick files for
        :param query_samples_read: The number of samples to read
        :param query_sample_offset: The start sample index of interest
        :return:
        """

        # get total samples
        total_samples_in_all_files = self.get_total_samples_in_all_partitions(timestamp=timestamp, tile_id=tile_id)

        if query_sample_offset < 0: # if reading from the back
            query_sample_offset = total_samples_in_all_files+query_sample_offset

        if query_sample_offset+query_samples_read > total_samples_in_all_files:
            query_samples_read = query_samples_read - ((query_sample_offset+query_samples_read) - total_samples_in_all_files)


        # Get number of partitions
        nof_partitions = self.file_partitions(timestamp=timestamp, tile_id=tile_id) + 1

        # Get number of samples in each partition
        file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id, partition=0)
        samples_per_partition = self.n_samples * self.n_blocks

        # Get partition number given file offset
        start_partition = old_div(query_sample_offset, samples_per_partition)
        end_partition = old_div((query_sample_offset + query_samples_read), (samples_per_partition + 1))

        # Check whether partitions exist
        if end_partition >= nof_partitions or start_partition >= nof_partitions:
            return []

        # Get number of samples in last partition
        if end_partition == start_partition:
            samples_in_last_partition = self.n_samples * self.n_blocks
            self.close_file(file_obj=file_obj)
        else:
            self.close_file(file_obj=file_obj)
            file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id, partition=end_partition)
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

    def get_file_partition_indexes_to_read_given_ts(self, timestamp=None, tile_id=0, query_ts_start=0, query_ts_end=0):
        """
        Returns an array of the form: [{"partition":partition,"indexes":[partition_start_idx,partition_end_idx]}]
        which contains the indexes range of which partitions need to be included when reading from a set of files
        (split into partitions) for a particular start and end timestamp
        :param timestamp: Mother timestamp of the file series
        :param tile_id: The tile ID to pick files for
        :param query_ts_start: The start timestamp of interest
        :param query_ts_end: The end timestamp of interest
        :return:
        """
        max_partition = self.file_partitions(timestamp=timestamp, tile_id=tile_id)

        partition_list = []

        for partition in range(0, max_partition + 1):
            file_obj = self.load_file(timestamp=timestamp, tile_id=tile_id, partition=partition)
            if self.ts_start <= query_ts_end:  # we need it, so find indexes where timestamp window matches
                nof_items = self.n_samples * self.n_blocks
                timestamp_buffer = numpy.empty((nof_items, 1))
                timestamp_grp = file_obj["sample_timestamps"]
                dset = timestamp_grp["data"]
                timestamp_buffer[0:nof_items] = dset[0:nof_items]

                # noinspection PyBroadException
                try:
                    partition_start_idx = numpy.where(timestamp_buffer >= query_ts_start)[0][0]
                    # noinspection PyBroadException
                    try:
                        partition_end_idx = (numpy.where(timestamp_buffer > query_ts_end)[0][0]) - 1
                    except:
                        # no index, so we take all of the rest of this partition
                        partition_end_idx = timestamp_buffer.size - 1

                    partition_list.append({"partition": partition, "indexes": [partition_start_idx, partition_end_idx]})
                except:
                    pass
            self.close_file(file_obj=file_obj)
        return partition_list

    def load_file(self, timestamp=None, tile_id=0, mode='r', partition=None):
        """
        Loads a file for a particular timestamp, tile id, load mode, and particular partition.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be retrieved).
        :param tile_id: The tile identifier for a file batch.
        :param mode: The HDF5 mode string for loading 'r', 'r+', 'w'
        :param partition: The particular partition to open, if None, the max partition returned by file_partitions is
        used.
        :return: An HDF5 file object if no errors and file exists, None otherwise.
        """
        filename_prefix, filename_mode_prefix = self.get_prefixes()
        max_partition = self.file_partitions(timestamp=timestamp, tile_id=tile_id)

        if partition is None:
            load_partition = max_partition
        else:
            load_partition = partition

        full_filename = None
        if timestamp is None:
            date_time = None
        else:
            date_time = self._get_date_time(timestamp=timestamp)

        if tile_id is None:
            tile_id_str = ''
        else:
            tile_id_str = str(tile_id)

        if date_time is not None:
            full_filename = os.path.join(self.root_path,
                                         filename_prefix + filename_mode_prefix + tile_id_str + "_" + str(
                                             date_time) + "_" + str(load_partition) + ".hdf5")

        if date_time is None:
            matched_files = []
            files = next(os.walk(self.root_path))[2]
            for file_obj in files:
                if file_obj.startswith(filename_prefix + filename_mode_prefix) and \
                        file_obj.endswith('_' + str(load_partition) + ".hdf5"):
                    file_obj_filename = ntpath.basename(file_obj)
                    if len(filename_mode_prefix) > 0:
                        file_tile = file_obj_filename.split('_')[2]
                    else:
                        file_tile = file_obj_filename.split('_')[1]
                    if int(file_tile) == tile_id:
                        matched_files.append(os.path.join(self.root_path, file_obj))

            if len(matched_files) > 0:
                # We have a list of matched filename, sort by last modified date and get latest one
                latest_file_time = 0
                for file_obj in matched_files:
                    file_obj_filename = ntpath.basename(file_obj)
                    if len(filename_mode_prefix) > 0:
                        file_time1 = file_obj_filename.split('_')[3]
                        file_time2 = file_obj_filename.split('_')[4]
                    else:
                        file_time1 = file_obj_filename.split('_')[2]
                        file_time2 = file_obj_filename.split('_')[3]
                    file_time_str = file_time1 + file_time2
                    file_time = int(file_time_str)
                    # file_time = int(file_time1) + int(file_time2)
                    if file_time > latest_file_time:
                        latest_file_time = file_time
                        full_filename = file_obj
            else:
                logging.error("No file matching arguments were found. Check data directory")
                return None

        if full_filename is not None:
            if os.path.isfile(full_filename):
                generic_full_filename = full_filename
                try:
                    file_obj = self.open_file(generic_full_filename, mode=mode)
                    if AAVSFileManager.check_root_integrity(file_obj):
                        self.main_dset = file_obj["root"]
                        self.n_antennas = self.main_dset.attrs['n_antennas']
                        self.n_pols = self.main_dset.attrs['n_pols']
                        self.n_beams = self.main_dset.attrs['n_beams']
                        self.tile_id = self.main_dset.attrs['tile_id']
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

                        if 'station_id' in list(self.main_dset.attrs.keys()):
                            self.station_id = self.main_dset.attrs['station_id']

                        # if sys.version_info.major == 3:
                        #     self.timestamp = str(self.main_dset.attrs['timestamp'], encoding='utf-8')
                        #     self.data_type_name = str(self.main_dset.attrs['data_type'], encoding='utf-8')
                        #     self.data_type = DATA_TYPE_MAP[self.data_type_name]
                        # elif sys.version_info.major == 2:
                        self.timestamp = self.main_dset.attrs['timestamp']
                        self.data_type_name = self.main_dset.attrs['data_type']
                        self.data_type = DATA_TYPE_MAP[self.data_type_name]

                        if self.n_samples == 1:
                            self.resize_factor = 1024
                        else:
                            self.resize_factor = self.n_samples

                        if self.n_samples == 1:
                            self.resize_factor = 1024
                        else:
                            self.resize_factor = self.n_samples

                        if self.n_baselines > 0:
                            self.resize_factor = self.n_baselines

                        return file_obj
                    else:
                        logging.error("File root integrity check failed, can't load file.")
                        return None
                except Exception as e:
                    logging.error(str(e))
                    raise
            else:
                return None
        else:
            logging.error("Expected file does not exist.")
            return None

    def create_file(self, timestamp=None, tile_id=0, partition_id=0):
        """
        Creates a file for a particular timestamp, tile id, and particular partition.
        :param timestamp: The base timestamp for a file batch (this timestamp is part of the resolved file name that
        will be retrieved).
        :param tile_id: The tile identifier for a file batch.
        :param partition_id: The particular partition to open, if None, the max partition returned by file_partitions is
        used.
        :return: An HDF5 file object if no errors occurred.
        """
        filename_prefix, filename_mode_prefix = self.get_prefixes()

        if timestamp is None:
            date_time = None
        else:
            date_time = self._get_date_time(timestamp=timestamp)

        if tile_id is None:
            tile_id_str = ''
        else:
            tile_id_str = str(tile_id)

        full_filename = os.path.join(self.root_path, filename_prefix + filename_mode_prefix + tile_id_str + "_" +
                                     date_time + "_" + str(partition_id) + ".hdf5")

        # Check if file exists, delete if it does (we want to create here!)
        for file_obj in os.listdir(os.path.join(self.root_path)):
            if fnmatch.fnmatch(file_obj, os.path.join(self.root_path, filename_prefix + filename_mode_prefix +
                    tile_id_str + "_" + date_time + "_" + str(partition_id) + ".hdf5")):
                os.remove(file_obj)

        first_full_filename = os.path.join(self.root_path, filename_prefix + filename_mode_prefix + tile_id_str +
                                           "_" + date_time + "_" + str(partition_id) + ".hdf5")

        file_obj = self.open_file(full_filename, 'w')
        os.chmod(first_full_filename, 0o776)

        self.main_dset = file_obj.create_dataset("root", (1,), chunks=True, dtype='float16')
        self.n_blocks = 0

        self.main_dset.attrs['timestamp'] = timestamp
        self.main_dset.attrs['date_time'] = date_time
        self.main_dset.attrs['n_antennas'] = self.n_antennas
        self.main_dset.attrs['n_pols'] = self.n_pols
        self.main_dset.attrs['n_beams'] = self.n_beams
        self.main_dset.attrs['tile_id'] = tile_id if tile_id is not None else -1
        self.main_dset.attrs['n_chans'] = self.n_chans
        self.main_dset.attrs['n_samples'] = self.n_samples
        self.main_dset.attrs['n_blocks'] = 0
        self.main_dset.attrs['type'] = self.type.value
        self.main_dset.attrs['data_type'] = self.data_type_name
        self.main_dset.attrs['data_mode'] = self.data_mode
        self.main_dset.attrs['ts_start'] = timestamp
        self.main_dset.attrs['ts_end'] = timestamp
        self.main_dset.attrs['n_baselines'] = self.n_baselines
        self.main_dset.attrs['n_stokes'] = self.n_stokes
        self.main_dset.attrs['channel_id'] = self.channel_id
        self.main_dset.attrs['station_id'] = self.station_id
        if self.tsamp is not None:
            self.main_dset.attrs['tsamp'] = self.tsamp

        # TODO: REMOVE MARCIN'S CODE BELOW
        # this is only a temporary code to make sure the channel is filled when we call the script ~/aavs-calibration/sensitivity/daq/channels_sweep.py which writes current channel to a local file current_channel.txt
        # if int( self.main_dset.attrs['channel_id'] ) <= 0 :
        #    channel_file = "current_channel.txt"
        #    if os.path.exists( channel_file ) :
        #       file=open( channel_file , 'r' )
        #       data=file.readlines()
        #       if len(data) >= 1 :
        #          words = data[0].split(' ')
        #          if len(words) > 0 :
        #             channel_id = int( words[0] )
        #             self.main_dset.attrs['channel_id'] = channel_id
        #             print "Set HDF5 attribute channel_id = %d" % (channel_id)

        self.configure(file_obj)
        return file_obj

    @staticmethod
    def close_file(file_obj):  # mode='w'
        """
        Closes a file object in use by this manager.
        :param file_obj: The file object to close.
        :return:
        """
        filename = file_obj.filename
        first_full_filename = filename

        lock = FileLock(first_full_filename)
        file_obj.close()
        lock.release()

    @staticmethod
    def open_file(filename, mode='r'):
        """
        This file manager will open a file in a specific mode.
        :param filename: Filename (full path) of file to be opened.
        :param mode: HDF5 mode string for file opening 'r', 'r+', 'w'
        :return:
        """
        first_full_filename = filename

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
        elif self.daqmode == FileDAQModes.Void:
            filename_mode_prefix = "burst_"

        return filename_prefix, filename_mode_prefix
