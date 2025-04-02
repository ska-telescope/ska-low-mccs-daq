import matplotlib

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



class BeamComparisonPlot():
    def __init__(self, timestamp):

        self.hdf5_realtime_file_name = 'beam_comparison_data/beam_realtime_data_' + timestamp + '.h5'
        self.hdf5_offline_file_name = 'beam_comparison_data/beam_offline_data_' + timestamp + '.h5'

        if not os.path.isfile(self.hdf5_realtime_file_name):
            print("Error! %s does not exist" % self.hdf5_realtime_file_name)
        if not os.path.isfile(self.hdf5_offline_file_name):
            print("Error! %s does not exist" % self.hdf5_offline_file_name)

        self.hdf5_realtime_data = h5py.File(self.hdf5_realtime_file_name, 'r')
        self.hdf5_offline_data = h5py.File(self.hdf5_offline_file_name, 'r')

    def get_plot_data(self, hdf5_data, power_max):
        pol_x = []
        pol_y = []
        ts_list_offset = []
        ts_list = list(hdf5_data.keys())
        for n, ts in enumerate(ts_list):
            ts_data = hdf5_data[ts]
            ts_offset = int(float(ts) - float(ts_list[0]))
            if ts_data[0] < power_max and ts_data[1] < power_max:
                ts_list_offset.append(ts_offset)
                pol_x.append(ts_data[0])
                pol_y.append(ts_data[1])
        print(ts_offset)
        return ts_list_offset, pol_x, pol_y

    def generate_plot(self, power_offset=-36, power_max=1000, pols= 2, show_plot=False):
        realtime_ts, realtime_pol_x, realtime_pol_y = self.get_plot_data(self.hdf5_realtime_data, power_max)
        self.hdf5_realtime_data.close()
        offline_ts, offline_pol_x, offline_pol_y = self.get_plot_data(self.hdf5_offline_data, power_max)
        self.hdf5_offline_data.close()

        print (offline_pol_y[0],offline_pol_x[0])
        # fig, (ax1) = plt.subplots(1, 1)
        fig = plt.figure()
        title = 'Realtime vs Offline Beam Comparison'
        if pols == 0:
            title += " - Pol X"
        if pols == 1:
            title += " - Pol Y"
        fig.suptitle(title)
        
        if pols == 0 or pols > 1:
            line_ax1_realtime_0, = plt.plot(realtime_ts, realtime_pol_x)
            line_ax1_realtime_0.set_label('Realtime Beam Pol X')
            line_ax1_offline_0, = plt.plot(offline_ts, np.asarray(offline_pol_x) + power_offset)
            line_ax1_offline_0.set_label('Offline Beam Pol X (%i dB offset)' % power_offset)
        #ax1.set_ylabel('Pol 0 Power (dB)')
        #ax1.legend()
        
        if pols == 1 or pols > 1:
            line_ax1_realtime_1, = plt.plot(realtime_ts, realtime_pol_y)
            line_ax1_realtime_1.set_label('Realtime Beam Pol Y')
            line_ax1_offline_1, = plt.plot(offline_ts, np.asarray(offline_pol_y) + power_offset)
            line_ax1_offline_1.set_label('Offline Beam Pol Y (%i dB offset)' % power_offset)
        #line_ax1_offline_1.set_ylabel('Power (dB)')
        
        plt.legend()
        plt.ylabel('Power (dB)')
        plt.xlabel('Timestamp offset (s)')
        
        if show_plot:
            plt.show()
        plt.savefig("test.png", dpi=600)


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %test_full_station [options]")
    parser.add_option('-t', action="store", dest="timestamp",
                      type="str", default="", help="File Timestamp")
    parser.add_option('-o', action="store", dest="power_offset",
                      type="float", default=0.0, help="Power Offset")
    parser.add_option('-m', action="store", dest="power_max",
                      type="int", default=1000, help="Power Max")
    parser.add_option('-s', action="store_true", dest="show_plot",
                                  default=False, help="Show plot")
    parser.add_option('-p', action="store", dest="pols",
                      type="int", default=2, help="Polarizations: 0,1,2 (both)")


    (opts, args) = parser.parse_args(argv[1:])
    
    if not opts.show_plot:
        matplotlib.use("Agg")
    from matplotlib import pyplot as plt
        

    inst = BeamComparisonPlot(opts.timestamp)
    inst.generate_plot(opts.power_offset, int(opts.power_max), opts.pols, opts.show_plot)
