from __future__ import print_function
from __future__ import division

import logging
from builtins import range
from past.utils import old_div
from pydaq.persisters import ChannelFormatFileManager, sys, FileDAQModes, CorrelationFormatFileManager
from multiprocessing.pool import ThreadPool
from threading import Thread
import threading

from optparse import OptionParser
from time import sleep
import numpy as np
import os

# Custom numpy type for creating complex signed 8-bit data
complex_8t = np.dtype([('real', np.int8), ('imag', np.int8)])

# Global variables
channel_file_mgr = None
nof_blocks = None
nof_samples = None
output = None
counter = 0
threads = 4
skip = 1

# Numpy-based ring buffer for communication between consumer and producer
consumer_lock = threading.Lock()
ring_buffer = None
producer = 0
consumer = 0


def correlate(input_data, output_data, nants, npols):
    baseline = 0
    for antenna1 in range(nants):
        for antenna2 in range(antenna1, nants):
            for pol1 in range(npols):
                for pol2 in range(npols):
                    output_data[pol1 * npols + pol2, baseline] = np.correlate(input_data[pol1, antenna1, :],
                                                                              input_data[pol2, antenna2, :])
            baseline += 1


def process_parallel(iteration):
    global channel_file_mgr
    global ring_buffer
    global consumer
    global nof_samples
    global nof_blocks
    global counter
    global output
    global skip

    # Read next data block (data is in channel/antenna/pol/time)
    try:
        # Wait for data to be available in
        consumer_lock.acquire()
        while not ring_buffer[consumer]['full']:
            sleep(0.1)

        # We have data, process it
        data = np.transpose(ring_buffer[consumer]['data'], (1, 0, 2)).copy()
        index = ring_buffer[consumer]['index']

        # All done, release lock
        ring_buffer[consumer]['full'] = False
        consumer = (consumer + 1) % threads
        counter += 1
        consumer_lock.release()

        data = (data['real'] + 1j * data['imag']).astype(np.complex64)

        sys.stdout.write(
            "Processed %d of %d [%.2f%%]     \r" % (counter, nof_blocks,
                                                    (counter / float(nof_blocks)) * 100))
        sys.stdout.flush()

        # Perform correlation
        correlate(data, output[:, :, index], channel_file_mgr.n_antennas, channel_file_mgr.n_pols)
    except Exception as e:
        import traceback
        print(e, traceback.format_exc())


def reader():
    global ring_buffer
    global nof_samples
    global nof_blocks
    global producer
    global consumer

    for i in range(nof_blocks):

        # Copy to ring buffer
        while ring_buffer[producer]['full']:
            sleep(0.1)

        # Read next data block
        ring_buffer[producer]['data'][:] = channel_file_mgr.read_data(n_samples=nof_samples,
                                                                      sample_offset=i * nof_samples * skip)[0][0, :]

        ring_buffer[producer]['index'] = i
        ring_buffer[producer]['full'] = True

        # Update producer pointer
        producer = (producer + 1) % threads


def correlator(directory, samples):
    global channel_file_mgr
    global ring_buffer
    global nof_samples
    global nof_blocks
    global counter
    global output
    global skip

    # Check that directory exists
    if not os.path.exists(directory):
        print("Specified data directory [%s] does not exist" % directory)
        exit()

    data_directory = directory
    nof_samples = samples

    os.system("rm -fr %s/*.lock" % data_directory)

    # Get channel file handler
    channel_file_mgr = ChannelFormatFileManager(root_path=data_directory, daq_mode=FileDAQModes.Continuous)

    # Read one sample to get metadata and calculate number of samples in file
    _, timestamp = channel_file_mgr.read_data(n_samples=1)
    if channel_file_mgr.file_partitions(tile_id=0) == 0:
        total_samples = channel_file_mgr.n_samples * channel_file_mgr.n_blocks
    else:
        total_samples = channel_file_mgr.n_samples * channel_file_mgr.n_blocks * \
                        (channel_file_mgr.file_partitions(tile_id=0))
    nof_baselines = int(0.5 * (channel_file_mgr.n_antennas ** 2 + channel_file_mgr.n_antennas))
    nof_blocks = total_samples / nof_samples

    # Create output buffer
    output = np.zeros((channel_file_mgr.n_pols ** 2, nof_baselines, nof_blocks), dtype=np.complex64)

    # Create ring buffer
    ring_buffer = []
    for i in range(threads):
        ring_buffer.append(
            {'full': False, 'index': 0, 'data': np.zeros((channel_file_mgr.n_antennas, channel_file_mgr.n_pols,
                                                          nof_samples), dtype=complex_8t)})

    # Initialise producer thread
    producer_thread = Thread(target=reader)
    producer_thread.start()

    # Start up consumer thread pool
    pool = ThreadPool(threads)
    pool.map(process_parallel, list(range(nof_blocks)))

    # Join producer
    producer_thread.join()

    # Reshape output
    output = np.transpose(output, (2, 1, 0))

    # All done, write correlations to file
    corr_file = CorrelationFormatFileManager(root_path=data_directory, data_type=b"complex64")
    corr_file.set_metadata(n_chans=1,
                           n_pols=channel_file_mgr.n_pols,
                           n_samples=nof_blocks,
                           n_antennas=channel_file_mgr.n_antennas,
                           n_stokes=channel_file_mgr.n_pols * channel_file_mgr.n_pols,
                           n_baselines=nof_baselines)

    corr_file.ingest_data(append=True,
                          data_ptr=output,
                          timestamp=timestamp,
                          sampling_time=0,
                          buffer_timestamp=timestamp,
                          channel_id=channel_file_mgr.channel_id)


if __name__ == "__main__":
    # Command line options
    p = OptionParser()
    p.set_usage('offline_correlator.py [options] INPUT_FILE')
    p.set_description(__doc__)

    p.add_option('-d', '--directory', dest='directory', action='store', default=".",
                 help="Data directory (default: '.')")
    p.add_option('-s', '--samples', dest='nof_samples', action='store', default=1048576,
                 type='int', help='Number of samples (default: 1048576)')
    opts, args = p.parse_args(sys.argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.DEBUG)
    str_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    from sys import stdout

    ch = logging.StreamHandler(stdout)
    ch.setFormatter(str_format)
    log.addHandler(ch)

    correlator(opts.directory, opts.nof_samples)
