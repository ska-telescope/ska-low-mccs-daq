from __future__ import print_function
from __future__ import division
from builtins import range
from past.utils import old_div
from pydaq.persisters import *
import numpy as np
import os

# Custom numpy type for creating complex signed 8-bit data
complex_8t = np.dtype([('real', np.int8), ('imag', np.int8)])


def combine_tiles(data_directory, nof_tiles):
    """ Combine continuous channel data from multiple tiles """
    block_size = 65536

    # Get channel file handler
    channel_file_mgr = ChannelFormatFileManager(root_path=data_directory, daq_mode=FileDAQModes.Continuous)

    # Read one sample to get metadata and calculate number of samples in file
    sample, timestamp = channel_file_mgr.read_data(n_samples=1)
    if channel_file_mgr.file_partitions(tile_id=0) == 0:
        total_samples = channel_file_mgr.n_samples * channel_file_mgr.n_blocks
    else:
        total_samples = channel_file_mgr.n_samples * channel_file_mgr.n_blocks * \
                        (channel_file_mgr.file_partitions(tile_id=0))

    # Create new output directory in data directory to store combined data
    output_directory = os.path.join(data_directory, 'output')
    if not os.path.exists(output_directory):
        os.mkdir(output_directory)

    # Create persister for output file
    output_file = ChannelFormatFileManager(root_path=output_directory, daq_mode=FileDAQModes.Continuous)
    output_file.set_metadata(n_chans=1,
                             n_antennas=nof_tiles * 16,
                             n_pols=2,
                             n_samples=block_size,
                             channel_id=channel_file_mgr.channel_id)

    # Copy data in blocks
    channel_data = np.zeros((block_size, nof_tiles * 32), dtype=complex_8t)
    timestamps = np.zeros(block_size)
    for i in range(0, total_samples, block_size):
        print((old_div(i, block_size), old_div(total_samples, block_size)))
        # Loop over antennas
        for t in range(nof_tiles):
            # Read data from current tile
            current_samples, current_timestamps = channel_file_mgr.read_data(n_samples=block_size,
                                                                             sample_offset=i,
                                                                             tile_id=t)

            # Reshape and transpose data
            current_samples = np.transpose(np.squeeze(current_samples.reshape(32, block_size)), (1, 0))

            channel_data[:, t * 32: (t + 1) * 32] = current_samples
            timestamps = current_timestamps.flatten()

        # Write combined data to output file
        output_file.ingest_data(append=True,
                                data_ptr=channel_data.flatten(),
                                timestamp=timestamp,
                                sampling_time=timestamps[1] - timestamps[0],
                                buffer_timestamp=timestamp[0])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Combine continuous tiles from multiple elements into one file')
    parser.add_argument('-d', '--directory', action="store", default='.', help="Data directory (default: '.'")
    parser.add_argument('-t', '--tiles', action="store", default=16, type=int, help="Number of tiles (default: 16")
    args = parser.parse_args()

    # Check that directory exists
    if not os.path.exists(args.directory):
        print("Specified data directory [%s] does not exist".format(args.directory))
        exit()

    # Remove locks
    os.system("rm -fr %s/*.lock".format(args.directory))

    combine_tiles(args.directory, args.tiles)
