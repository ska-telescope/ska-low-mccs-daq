from multiprocessing.pool import ThreadPool
import glob
import re
import datetime
import numpy as np
import threading
import time
import sys
import os

from pydaq.persisters import FileDAQModes, ChannelFormatFileManager, CorrelationFormatFileManager


class Correlator:
    # Custom numpy type for creating complex signed 8-bit data
    complex_8t = np.dtype([('real', np.int8), ('imag', np.int8)])

    def __init__(self, nof_samples: int = 1048576, nof_threads=8):
        """ Class initializer """

        self._nof_samples = nof_samples
        self._nof_threads = nof_threads
        self._skip = 1

        # Processing variables
        self._correlated_data = None
        self._sorted_tile_ids = None
        self._channel_reader = None
        self._nof_blocks = None
        self._nof_baselines = 0
        self._nof_antennas = 0
        self._nof_channels = 0
        self._nof_pols = 0

        # Numpy-based ring buffer for communication between consumer and producer
        self._consumer_lock = threading.Lock()
        self._ring_buffer = None
        self._producer = 0
        self._consumer = 0
        self._counter = 0

        self._filename_re = re.compile(r"channel_(?P<mode>\w+)_(?P<tile>\d+)_(?P<timestamp>\d+_\d+)_\d+.hdf5")

    def correlate(self, input_directory):
        """ Correlate channel files in provided directory"""

        # Check that file exists
        input_directory = os.path.abspath(os.path.expanduser(input_directory))
        if not os.path.exists(input_directory) or not os.path.isdir(input_directory):
            print("Specified directory [%s] does not exist or is not a directory" % input_directory)
            return

        # Get list of files in directory
        timestamps = []
        tiles_to_process = []
        mode = 'burst'
        for f in glob.glob(os.path.join(input_directory, '*.hdf5')):
            # Determine whether file is valid
            f = os.path.basename(os.path.abspath(f))
            match = re.match(self._filename_re, f)
            if match is not None:
                params = match.groupdict()
                mode = params['mode']
                tiles_to_process.append(int(params['tile']))
                timestamps.append(params['timestamp'])

        # If no tiles were detected, then there are no valid files to process
        if len(tiles_to_process) == 0:
            print("No channel files found. Not correlating.")
            return

        self._sorted_tile_ids = sorted(tiles_to_process)
        if not (min(self._sorted_tile_ids) == 0 and len(set(self._sorted_tile_ids)) == max(self._sorted_tile_ids) + 1):
            print("Missing tiles detected. Not correlating.")
            return

        # Check whether all timestamps are the same
        if len(set(timestamps)) != 1:
            print("Different timestamps detected. Not correlating.")
            return

        # Valid data to process. Extract timestamp
        try:
            time_parts = timestamps[0].split('_')
            sec = datetime.timedelta(seconds=int(time_parts[1]))
            date = datetime.datetime.strptime(time_parts[0], '%Y%m%d') + sec
            timestamp = time.mktime(date.timetuple())
        except Exception as e:
            print("Could not convert date in filename to a timestamp: {}. Not correlating.".format(e))
            return

        # Remove pending file locks
        os.system(f"rm -fr {input_directory}/*.lock")

        # Create channel_reader
        if mode == "burst":
            self._channel_reader = ChannelFormatFileManager(root_path=input_directory,
                                                            daq_mode=FileDAQModes.Burst)
        else:
            self._channel_reader = ChannelFormatFileManager(root_path=input_directory,
                                                            daq_mode=FileDAQModes.Continuous)

        # Read one sample to get metadata and calculate number of samples in file
        _ = self._channel_reader.read_data(n_samples=1)
        total_samples = self._channel_reader.n_samples * self._channel_reader.n_blocks * \
                        (self._channel_reader.file_partitions(tile_id=0) + 1)

        self._nof_antennas = self._channel_reader.n_antennas * len(self._sorted_tile_ids)
        self._nof_channels = self._channel_reader.n_chans
        self._nof_blocks = int(total_samples / self._nof_samples)
        self._nof_pols = self._channel_reader.n_pols
        self._nof_baselines = int(0.5 * self._nof_antennas ** 2 + self._nof_antennas)

        # Create output buffer
        # Input data is in channels / antennas / pols / samples order
        # Output data should be in channels / baselines / blocks order
        self._correlated_data = np.zeros((self._nof_pols * self._nof_pols, self._nof_channels,
                                          self._nof_baselines, self._nof_blocks),
                                         dtype=np.complex64)

        # Reset counters (as correlate can be called multiple times)
        self._producer = 0
        self._consumer = 0
        self._counter = 0

        # Create ring buffer
        # self._ring_buffer = []
        # for i in range(self._nof_threads * 2):
        #     self._ring_buffer.append(
        #         {'full': False,
        #          'index': 0,
        #          'data': np.zeros((self._nof_antennas,
        #                            self._nof_pols,
        #                            self._nof_samples),
        #                           dtype=self.complex_8t)})
        #
        # # Initialise producer thread
        # producer_thread = threading.Thread(target=self._reader)
        # producer_thread.start()
        #
        # # Start up consumer thread pool
        # start = time.time()
        # pool = ThreadPool(self._nof_threads)
        # pool.map(self._process_parallel, range(self._nof_blocks * self._nof_channels))
        # end = time.time()
        # print("Took {}s to correlate {} blocks of {} samples each".format(end - start, self._nof_blocks,
        #                                                                   self._nof_samples))
        #
        # # Join producer
        # producer_thread.join()

        # Transpose data to match output format
        self._correlated_data = np.transpose(self._correlated_data, (3, 1, 2, 0))

        # Generate output file
        self._generate_output_file(input_directory, timestamp)

    def _generate_output_file(self, directory, timestamp):

        # All done, write correlations to file
        for channel in range(self._nof_channels):
            corr_file = CorrelationFormatFileManager(root_path=directory, data_type="complex64")
            corr_file.set_metadata(n_chans=1,
                                   n_pols=self._nof_pols,
                                   n_samples=self._nof_blocks,
                                   n_antennas=self._nof_antennas,
                                   n_stokes=self._nof_pols * self._nof_pols,
                                   n_baselines=self._nof_baselines)

            corr_file.ingest_data(data_ptr=self._correlated_data[:, channel, :, :],
                                  timestamp=timestamp,
                                  sampling_time=0,
                                  buffer_timestamp=timestamp,
                                  channel_id=channel)

    def _correlate(self, input_data, output):
        baseline, stokes = 0, 0
        for antenna1 in range(self._nof_antennas):
            for antenna2 in range(antenna1, self._nof_antennas):
                stokes = 0
                for pol1 in range(self._nof_pols):
                    for pol2 in range(self._nof_pols):
                        ans = np.correlate(input_data[antenna1, pol1, :],
                                           input_data[antenna2, pol2, :])
                        output[stokes, baseline] = ans[0]
                        stokes += 1
            baseline += 1

    def _process_parallel(self, _):

        # Read next data block (data is in sample/channel/antenna)
        try:
            # Wait for data to be available in
            self._consumer_lock.acquire()
            while not self._ring_buffer[self._consumer]['full']:
                time.sleep(0.1)

            # We have data, process it
            data = self._ring_buffer[self._consumer]['data']
            index = self._ring_buffer[self._consumer]['index']
            channel = self._ring_buffer[self._consumer]['channel']

            # All done, release lock
            self._ring_buffer[self._consumer]['full'] = False
            self._consumer = (self._consumer + 1) % self._nof_threads
            self._counter += 1
            self._consumer_lock.release()

            t0 = time.time()
            data = (data['real'] + 1j * data['imag']).astype(np.complex64)

            total_blocks = self._nof_blocks * self._nof_channels
            sys.stdout.write(
                "Processed %d of %d [%.2f%%]     \r" % (self._counter, total_blocks,
                                                        (self._counter / float(total_blocks)) * 100))
            sys.stdout.flush()

            # Perform correlation
            self._correlate(data, self._correlated_data[:, channel, :, index])

        except Exception as e:
            import traceback
            print(e, traceback.format_exc())

    def _reader(self):

        for block in range(self._nof_blocks):
            for channel in range(self._nof_channels):

                # Copy to ring buffer
                while self._ring_buffer[self._producer]['full']:
                    time.sleep(0.1)

                # Read data
                t0 = time.time()
                data_ptr = self._ring_buffer[self._producer]['data']
                for tile_id in self._sorted_tile_ids:
                    data, _ = self._channel_reader.read_data(tile_id=tile_id,
                                                             n_samples=self._nof_samples,
                                                             sample_offset=block * self._nof_samples,
                                                             channels=[channel])
                    data_ptr[tile_id * 16: (tile_id + 1) * 16, :, :] = data

                self._ring_buffer[self._producer]['index'] = block
                self._ring_buffer[self._producer]['channel'] = channel
                self._ring_buffer[self._producer]['full'] = True

                # Update producer pointer
                self._producer = (self._producer + 1) % self._nof_threads


if __name__ == "__main__":
    from optparse import OptionParser

    # Command line options
    p = OptionParser()
    p.set_usage('offline_correlator.py [options] INPUT_FILE')
    p.set_description(__doc__)

    p.add_option('-s', '--samples', dest='nof_samples', action='store', default=int(65536),
                 type='int', help='Number of samples (default: 1048576)')
    p.add_option('-d', '--directory', dest='directory', action='store', default='.',
                 help='If specified, correlate all .dat files in directory (default: None)')
    opts, args = p.parse_args(sys.argv[1:])

    # Create correlator object
    correlator = Correlator(nof_samples=opts.nof_samples)
    correlator.correlate(opts.directory)
