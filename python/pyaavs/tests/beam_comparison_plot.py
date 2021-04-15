import matplotlib
# matplotlib.use("Agg")
from matplotlib import pyplot as plt

from datetime import datetime, timedelta, timezone
from config_manager import ConfigManager
from pyaavs import station
from multiprocessing import Process
from spead_beam_power_realtime import SpeadRxBeamPowerRealtime
from spead_beam_power_offline import SpeadRxBeamPowerOffline
import spead_beam_power_realtime
import spead_beam_power_offline
import test_functions as tf
import numpy as np
import datetime
import logging
import shutil
import h5py
import time
import os
import os.path



class BeamComparisonPlot():
    def __init__(self, timestamp):

        self.hdf5_realtime_file_name = 'beam_comparison_data/beam_realtime_data_' + timestamp + '.h5'
        self.hdf5_offline_file_name = 'beam_comparison_data/beam_offline_data_' + timestamp + '.h5'

        if not os.path.isfile(self.hdf5_realtime_file_name):
            print("Error! %s does not exist" % self.hdf5_realtime_file_name)
            return -1
        if not os.path.isfile(self.hdf5_offline_file_name):
            print("Error! %s does not exist" % self.hdf5_offline_file_name)
            return -1

        self.hdf5_realtime_data = h5py.File(self.hdf5_realtime_file_name, 'r')
        self.hdf5_offline_data = h5py.File(self.hdf5_offline_file_name, 'r')

    def get_plot_data(self, hdf5_data):
        pol_x = []
        pol_y = []
        ts_list_offset = []
        ts_list = list(hdf5_data.keys())
        for n, ts in enumerate(ts_list):
            ts_data = hdf5_data[ts]
            ts_offset = int(float(ts) - float(ts_list[0]))
            ts_list_offset.append(ts_offset)
            pol_x.append(ts_data[0])
            pol_y.append(ts_data[1])
        return ts_list_offset, pol_x, pol_x

    def generate_plot(self, power_offset=-18):
        realtime_ts, realtime_pol_x, realtime_pol_y = self.get_plot_data(self.hdf5_realtime_data)
        self.hdf5_realtime_data.close()
        offline_ts, offline_pol_x, offline_pol_y = self.get_plot_data(self.hdf5_offline_data)
        self.hdf5_offline_data.close()

        fig, (ax1, ax2) = plt.subplots(2, 1)
        fig.suptitle('Realtime vs Offline Beam Comparison')

        line_ax1_realtime, = ax1.plot(realtime_ts, realtime_pol_x, '.')
        line_ax1_realtime.set_label('Realtime Beam')
        line_ax1_offline, = ax1.plot(offline_ts, np.asarray(offline_pol_x) + power_offset, '.')
        line_ax1_offline.set_label('Offline Beam %d dB offset' % power_offset)
        ax1.set_ylabel('Pol 0 Power (dB)')
        ax1.legend()

        line_ax2_realtime, = ax2.plot(realtime_ts, realtime_pol_y, '.')
        line_ax2_realtime.set_label('Realtime Beam')
        line_ax2_offline, = ax2.plot(offline_ts, np.asarray(offline_pol_y) + power_offset, '.')
        line_ax2_offline.set_label('Offline Beam with %d dB offset' % power_offset)
        ax2.set_ylabel('Pol 1 Power (dB)')
        ax2.legend()

        plt.xlabel('Timestamp offset (s)')

        plt.show()



if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout
    
    parser = OptionParser(usage="usage: %test_full_station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option('-t', action="store", dest="timestamp",
                      type="str", default="", help="File Timestamp")

    (opts, args) = parser.parse_args(argv[1:])

    inst = BeamComparisonPlot(opts.timestamp)
    inst.generate_plot()
