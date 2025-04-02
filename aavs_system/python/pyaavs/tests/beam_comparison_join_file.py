from datetime import datetime, timedelta
from multiprocessing import Process
import numpy as np
import datetime
import logging
import shutil
import h5py
import time
import os
import os.path


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %test_full_station [options]")
    parser.add_option('-i', action="store", dest="timestamp_head",
                      type="str", default="", help="File Timestamp Head")
    parser.add_option('-t', action="store", dest="timestamp_tail",
                      type="str", default="", help="File Timestamp Tail")

    (opts, args) = parser.parse_args(argv[1:])
    
    timestamp_head = opts.timestamp_head
    timestamp_tail = opts.timestamp_tail
    
    hdf5_realtime_file_name = []
    hdf5_offline_file_name = []
    
    hdf5_realtime_file_name.append('beam_comparison_data/beam_realtime_data_' + timestamp_head + '.h5')
    hdf5_realtime_file_name.append('beam_comparison_data/beam_realtime_data_' + timestamp_tail + '.h5')
    hdf5_offline_file_name.append('beam_comparison_data/beam_offline_data_' + timestamp_head + '.h5')
    hdf5_offline_file_name.append('beam_comparison_data/beam_offline_data_' + timestamp_tail + '.h5')
    hdf5_realtime_output_file_name = 'beam_comparison_data/beam_realtime_data_join_' + timestamp_head + '.h5'
    hdf5_offline_output_file_name = 'beam_comparison_data/beam_offline_data_join_' + timestamp_head + '.h5'
    
    for data_type in ["realtime", "offline"]:
        data_join = {}
        nof_samples = 0
        if data_type == "realtime":
            hdf5_data_join = h5py.File(hdf5_realtime_output_file_name, 'w')
            for n in range(2):
                hdf5_data = h5py.File(hdf5_realtime_file_name[n], 'r')
                for ts in list(hdf5_data.keys()):
                    hdf5_data_join.create_dataset(ts, data=list(hdf5_data[ts]))
                    nof_samples += 1
                hdf5_data.close()
            print(nof_samples)
            hdf5_data_join.close()
        else:
            hdf5_data_join = h5py.File(hdf5_offline_output_file_name, 'w')
            for n in range(2):
                hdf5_data = h5py.File(hdf5_offline_file_name[n], 'r')
                for ts in list(hdf5_data.keys()):
                    hdf5_data_join.create_dataset(ts, data=list(hdf5_data[ts]))
                    nof_samples += 1
                hdf5_data.close()
            print(nof_samples)
            hdf5_data_join.close()
            