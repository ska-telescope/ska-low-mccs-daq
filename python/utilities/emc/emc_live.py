import os
import sys
import time
import logging
import datetime
import calendar

import matplotlib.pyplot as plt
import numpy as np
import netifaces as ni
from pyaavs import station
import pydaq.daq_receiver as monit_daq
from threading import Thread
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget
from pydaq.persisters import ChannelFormatFileManager, FileDAQModes
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.gridspec import GridSpec


def get_if_name(lmc_ip):
    nics = ni.interfaces()
    tpm_nic = ""
    for n in nics:
        conf = ni.ifaddresses(n)
        for k in conf.keys():
            for l in conf[k]:
                if 'addr' in l.keys():
                    if l['addr'] == lmc_ip:
                        tpm_nic = n
                        break
    return tpm_nic


def fname_to_tstamp(date_time_string):
    time_parts = date_time_string.split('_')
    d = datetime.datetime.strptime(time_parts[0], "%Y%m%d")  # "%d/%m/%Y %H:%M:%S"
    timestamp = calendar.timegm(d.timetuple())
    timestamp += int(time_parts[1])# - (60 * 60 * 8)  # Australian Time
    return timestamp


def closest(serie, num):
    return serie.tolist().index(min(serie.tolist(), key=lambda z: abs(z - num)))


def dt_to_timestamp(d):
    return calendar.timegm(d.timetuple())


def ts_to_datestring(tstamp, formato="%Y-%m-%d %H:%M:%S"):
    return datetime.datetime.strftime(datetime.datetime.utcfromtimestamp(tstamp), formato)


def dB2Linear(valueIndB):
    return pow(10, valueIndB / 10.0)


def linear2dB(valueInLinear):
    return 10.0 * np.log10(valueInLinear)


def dBm2Linear(valueIndBm):
    return dB2Linear(valueIndBm) / 1000.


def linear2dBm(valueInLinear):
    return linear2dB(valueInLinear * 1000.)


class MyCanvas(FigureCanvas):
    def __init__(self):
        plt.ion()
        self.fig = Figure(figsize=(14, 9), facecolor='w')
        self.gs = GridSpec(6, 5, left=0.08, right=0.95, bottom=0.1, top=0.96, hspace=1.6, wspace=0.4)
        self.ax_spgr = self.fig.add_subplot(self.gs[0:3, 0:3])
        self.ax_pow = self.fig.add_subplot(self.gs[3:5, 0:3])
        self.ax_delta = self.fig.add_subplot(self.gs[5, 0:3])
        self.ax_spectrum = self.fig.add_subplot(self.gs[0:3, 3:5])
        self.ax_text = self.fig.add_subplot(self.gs[3:6, 3:5])

        self.ax_pow.grid()
        self.ax_pow.set_ylabel("dB", fontsize=12)
        self.ax_pow.set_title("RMS Power")

        self.ax_spgr.yaxis.set_label_text("MHz", fontsize=14)
        self.ax_spgr.set_title("Max Peak Aggregated Spectrogram")

        self.ax_spectrum.grid()
        self.ax_spectrum.set_xlabel("MHz", fontsize=12)
        self.ax_spectrum.set_ylabel("dB", fontsize=12)
        self.ax_spectrum.set_title("Aggregated Spectrum Analysis")

        self.ax_delta.set_ylim(0, 60)
        self.ax_delta.set_xlabel("UTC Time", fontsize=12)
        self.ax_delta.set_ylabel("sec", fontsize=12)
        self.ax_delta.set_title("TPM Packets Timestamp Deltas")

        self.ax_text.set_axis_off()
        self.ax_text.plot(range(100), color='w')
        self.ax_text.set_xlim(0, 100)
        self.t_stamp_text = self.ax_text.annotate("Last Timestamp: ", (0.1, 100), fontsize=12, color='g')
        self.records_text = self.ax_text.annotate("Number of Integrations: ", (0.1, 85), fontsize=12, color='b')

        FigureCanvas.__init__(self, self.fig)
        FigureCanvas.setSizePolicy(self, QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Expanding)
        FigureCanvas.updateGeometry(self)


class MyPlot(QtWidgets.QWidget):
    """ Class encapsulating a matplotlib plot"""
    def __init__(self, parent):
        QtWidgets.QWidget.__init__(self, parent)
        self.canvas = MyCanvas()
        self.updateGeometry()
        self.vbl = QtWidgets.QVBoxLayout()
        self.vbl.addWidget(self.canvas)
        self.setLayout(self.vbl)
        self.show()

    def annotate_tstamp(self, txt):
        self.canvas.t_stamp_text.set_text(txt)

    def annotate_records(self, txt):
        self.canvas.records_text.set_text(txt)

    def updatePlot(self):
        self.canvas.draw()
        self.canvas.flush_events()
        self.show()


# Subclass QMainWindow to customize your application's main window
class MainWindow(QMainWindow):
    signal = QtCore.pyqtSignal()

    def __init__(self, configuration, directory, winlen, wclim):
        super().__init__()
        self.configuration = configuration
        self.directory = directory
        self.wclim = wclim
        self.setWindowTitle("Integrated Spectra Live Monitor")
        self.wg = QWidget()
        self.myPlots = MyPlot(parent=self.wg)
        #self.wg.setGeometry(QtCore.QRect(10, 180, 1131, 681))
        self.setCentralWidget(self.wg)
        self.resize(1500, 1000)
        self.show()
        self.stopThreads = False
        self.tpm_station = None
        self.station_configuration = {}
        self.tpm_nic_name = ""
        self.monitor_daq = None
        self.monitor_tstart = 0
        self.monitor_file_manager = None

        self.freqs = []
        self.sampling_frequency = 8e8
        self.nsamples = 1024
        self.RBW = self.sampling_frequency / self.nsamples
        self.freqs = np.arange(self.nsamples / 2) * self.RBW / 1000.
        self.freqs = self.freqs / 1000.

        self.nof_tiles = len(self.configuration['tiles'])
        self.t_stamps = {}
        self.deltas = {}
        self.orari = {}
        self.decimation = None
        self.skip = None
        self.records = 0
        # for nTpm in range(self.nof_tiles):
        #     self.t_stamps["TPM-%02d" % nTpm] = []
        #     self.deltas["TPM-%02d" % nTpm] = []
        self.t_old = 0
        self.t_cnt = 0
        self.t_new = 0
        self.t_last = 0
        self.t_steps = 0
        self.delta = 0
        self.orario = ""
        self.antenne = np.arange(16)
        self.max_hold = None
        self.min_hold = None
        self.max_hold_ever = None
        self.min_hold_ever = None
        self.channel_power = {}
        self.max_peak_spgram = []
        self.spgr_plot = None
        self.x_tick = []
        self.x_ticklabels = []

        self.delta_lines = {}
        self.power_lines = {}
        self.spectra_max_lines = None
        self.spectra_min_lines = None
        self.spectra_max_hold_lines = None
        self.spectra_min_hold_lines = None
        self.winlen = winlen

        self.procReadData = Thread(target=self.procReadHdf5)
        self.procReadData.start()

        self.initPlots()

    def procReadHdf5(self):
        int_data_port = str(self.configuration['network']['lmc']['lmc_port'])
        int_data_ip = str(self.configuration['network']['lmc']['lmc_ip'])
        if self.configuration['network']['lmc']['use_teng']:
            int_data_port = str(self.configuration['network']['lmc']['integrated_data_port'])
        if not self.configuration['network']['lmc']['use_teng_integrated']:
            int_data_ip = str(self.configuration['network']['lmc']['integrated_data_ip'])
        int_data_if = get_if_name(int_data_ip)
        daq_config = {
            "receiver_interface": int_data_if,
            "receiver_ports": int_data_port,
            "receiver_ip": int_data_ip.encode(),
            "nof_tiles": self.nof_tiles,
            'directory': self.directory}
        if os.path.exists(self.directory):
            self.monitor_daq = monit_daq
            self.monitor_daq.populate_configuration(daq_config)
            log.info("Integrated Data Conf %s:%s on NIC %s" % (int_data_ip, int_data_port, int_data_if))
            self.monitor_daq.initialise_daq()
            self.monitor_daq.start_integrated_channel_data_consumer()
            self.monitor_file_manager = ChannelFormatFileManager(
                root_path=self.directory,
                daq_mode=FileDAQModes.Integrated)
            self.monitor_tstart = dt_to_timestamp(datetime.datetime.utcnow())

        while not os.listdir(self.directory):
            time.sleep(0.5)
        time.sleep(1)

        while not self.stopThreads:
            data, timestamps = self.monitor_file_manager.read_data(tile_id=0, n_samples=1, sample_offset=-1)
            if len(timestamps) > 0:
                # Check if it is a new timestamp
                if not timestamps[0][0] == self.t_old:
                    # New data received, emit signal!
                    self.t_old = timestamps[0][0]
                    self.signal.emit()
            cycle = 0
            while (cycle < 1) and (not self.stopThreads):
                time.sleep(0.1)
                cycle = cycle + 0.1

    def initPlots(self):
        t_stop = dt_to_timestamp(datetime.datetime.utcnow())
        t_start = t_stop - (self.winlen * 60)
        self.t_steps = int(np.ceil((t_stop - t_start) / (float(self.configuration['station']['channel_integration_time'])*8)))
        self.tempi = np.arange(self.t_steps) * float(self.configuration['station']['channel_integration_time']) * 8 + t_start
        self.delta_lines = {}
        self.power_lines = {}
        for nTpm in range(self.nof_tiles):
            self.t_stamps["TPM-%02d" % nTpm] = np.arange(self.t_steps) * float(self.configuration['station']['channel_integration_time']) * 8 + t_start
            self.deltas["TPM-%02d" % nTpm] = np.zeros(self.t_steps)
            self.deltas["TPM-%02d" % nTpm][:] = np.nan
            line, = self.myPlots.canvas.ax_delta.plot(self.t_stamps["TPM-%02d" % nTpm], self.deltas["TPM-%02d" % nTpm])
            self.delta_lines["TPM-%02d" % nTpm] = line
            for ant in self.antenne:
                for npol, pol in enumerate(["Pol-X", "Pol-Y"]):
                    self.channel_power["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)] = np.zeros(self.t_steps)
                    self.channel_power["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)][:] = np.nan
                    line, = self.myPlots.canvas.ax_pow.plot(self.t_stamps["TPM-%02d" % nTpm], self.channel_power["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)])
                    self.power_lines["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)] = line

        nodata = np.zeros(int(self.nsamples/2))
        nodata[:] = np.nan
        self.spectra_max_hold_lines, = self.myPlots.canvas.ax_spectrum.plot(self.freqs, nodata, color='r', label="Max Hold")
        self.spectra_max_lines, = self.myPlots.canvas.ax_spectrum.plot(self.freqs, nodata, color='b', label="Last Max Peak")
        self.spectra_min_lines, = self.myPlots.canvas.ax_spectrum.plot(self.freqs, nodata, color='g', label="Last Min Peak")
        self.spectra_min_hold_lines, = self.myPlots.canvas.ax_spectrum.plot(self.freqs, nodata, color='orange', label="Min Hold")
        self.myPlots.canvas.ax_spectrum.set_xlim(self.freqs[1], self.freqs[-1])
        self.myPlots.canvas.ax_spectrum.set_ylim(0, 50)

        # Compute DateTime Tick for X Axes
        self.x_tick = []
        self.x_ticklabels = []
        prec = datetime.datetime.utcfromtimestamp(t_start).minute - 1
        div = np.array([1, 2, 5, 10, 20, 30])

        for z in self.tempi:
            tz = datetime.datetime.utcfromtimestamp(z)
            if not z == prec:
                self.x_tick += [z]
                self.x_ticklabels += [datetime.datetime.strftime(tz, "%H:%M:%S")]
                prec = z
        self.decimation = div[closest(div, len(self.x_tick) / 10)]
        self.skip = self.decimation - int(self.x_tick[0]) % self.decimation
        self.x_tick = self.x_tick[self.skip::self.decimation]
        self.x_ticklabels = self.x_ticklabels[self.skip::self.decimation]
        self.myPlots.canvas.ax_pow.set_xticks(self.x_tick)
        self.myPlots.canvas.ax_pow.set_xticklabels(self.x_ticklabels, rotation=45, fontsize=8)
        self.myPlots.canvas.ax_pow.set_xlim(self.tempi[0], self.tempi[-1])
        self.myPlots.canvas.ax_delta.set_xticks(self.x_tick)
        self.myPlots.canvas.ax_delta.set_xticklabels(self.x_ticklabels, rotation=45, fontsize=8)
        self.myPlots.canvas.ax_delta.set_xlim(self.tempi[0], self.tempi[-1])
        self.myPlots.canvas.ax_delta.set_ylim(0, np.ceil(float(self.configuration['station']['channel_integration_time']) * 8 * 3))

        self.max_peak_spgram = np.array([np.zeros(512)] * self.t_steps)
        self.max_peak_spgram[:][:] = np.nan
        self.spgr_plot = self.myPlots.canvas.ax_spgr.imshow(np.rot90(self.max_peak_spgram),
                                                            extent=[self.tempi[0], self.tempi[-1], 0, 400],
                                                            interpolation='none', aspect='auto', cmap='jet',
                                                            clim=self.wclim)
        self.myPlots.canvas.ax_spgr.set_xticks(self.x_tick)
        self.myPlots.canvas.ax_spgr.set_xticklabels(self.x_ticklabels, rotation=45, fontsize=8)
        self.myPlots.canvas.ax_spgr.yaxis.set_label_text("MHz", fontsize=14)
        self.myPlots.canvas.ax_spgr.set_title("Max Peak Aggregated Spectrogram")
        self.myPlots.canvas.ax_spectrum.legend()

    def updatePlots(self):
        t_last = 0
        min_chan_power = 50
        max_chan_power = 10
        self.max_hold = None
        self.min_hold = None
        for nTpm in range(self.nof_tiles):
            # Grab tile data
            data, timestamps = self.monitor_file_manager.read_data(tile_id=nTpm, n_samples=1, sample_offset=-1)
            t_last = timestamps[0][0]
            self.deltas["TPM-%02d" % nTpm] = np.roll(self.deltas["TPM-%02d" % nTpm], -1, axis=0)
            if not self.records:
                self.deltas["TPM-%02d" % nTpm][-1] = np.nan
            else:
                self.deltas["TPM-%02d" % nTpm][-1] = t_last - self.t_stamps["TPM-%02d" % nTpm][-1]
            self.t_stamps["TPM-%02d" % nTpm] = np.roll(self.t_stamps["TPM-%02d" % nTpm], -1, axis=0)
            self.t_stamps["TPM-%02d" % nTpm][-1] = t_last

            for ant in self.antenne:
                for npol, pol in enumerate(["Pol-X", "Pol-Y"]):
                    if self.max_hold is None:
                        self.max_hold = data[:, ant, npol, 0]
                        self.min_hold = data[:, ant, npol, 0]
                    else:
                        self.max_hold = np.maximum(self.max_hold, data[:, ant, npol, 0])
                        self.min_hold = np.minimum(self.min_hold, data[:, ant, npol, 0])
                    with np.errstate(divide='ignore'):
                        chan_power = 10 * np.log10(np.sum(data[1:, ant, npol, 0]))
                    if np.isinf(chan_power):
                        chan_power = 0
                    self.channel_power["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)] = np.roll(
                        self.channel_power["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)], -1, axis=0)
                    self.channel_power["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)][-1] = chan_power
                    max_chan_power = max(max_chan_power, np.nanmax(self.channel_power["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)]))
                    min_chan_power = min(min_chan_power, np.nanmin(self.channel_power["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)]))

        # Compute DateTime Tick for X Axes
        self.tempi = np.roll(self.tempi, -1, axis=0)
        self.tempi[-1] = t_last

        if not self.records:
            # Compute DateTime Tick for X Axes
            t_stop = t_last
            t_start = t_stop - (self.winlen * 60)
            self.t_steps = int(
                np.ceil((t_stop - t_start) / (float(self.configuration['station']['channel_integration_time']) * 8)))
            self.tempi = np.arange(self.t_steps) * float(
                self.configuration['station']['channel_integration_time']) * 8 + t_start
            self.x_tick = []
            self.x_ticklabels = []
            prec = datetime.datetime.utcfromtimestamp(t_start).minute - 1
            div = np.array([1, 2, 5, 10, 20, 30])

            for z in self.tempi:
                tz = datetime.datetime.utcfromtimestamp(z)
                if not z == prec:
                    self.x_tick += [z]
                    self.x_ticklabels += [datetime.datetime.strftime(tz, "%H:%M:%S")]
                    prec = z
            self.decimation = div[closest(div, len(self.x_tick) / 10)]
            self.x_tick = self.x_tick[::self.decimation]
            self.x_ticklabels = self.x_ticklabels[::self.decimation]
        else:
            if not self.x_tick[0] in self.tempi:
                self.x_tick = np.roll(self.x_tick, -1, axis=0)
                self.x_tick[-1] = np.nan
                self.x_ticklabels = np.roll(self.x_ticklabels, -1, axis=0)
                self.x_ticklabels[-1] = ""

            if not ((self.t_steps + self.records) % self.decimation):
                self.x_tick[-1] = t_last
                self.x_ticklabels[-1] = datetime.datetime.strftime(datetime.datetime.utcfromtimestamp(t_last), "%H:%M:%S")
        self.records = self.records + 1

        # force -inf to zero:
        with np.errstate(divide='ignore'):
            spettro_max = 10 * np.log10(self.max_hold)
        spettro_max[spettro_max == -np.inf] = 0
        self.max_peak_spgram = np.roll(self.max_peak_spgram, -1, axis=0)
        self.max_peak_spgram[-1][:] = spettro_max
        with np.errstate(divide='ignore'):
            spettro_min = 10 * np.log10(self.min_hold)
        spettro_min[spettro_min == -np.inf] = 0
        self.spgr_plot.set_data(np.rot90(self.max_peak_spgram))
        self.spgr_plot.set_extent([self.tempi[0], self.tempi[-1], 0, 400])
        self.myPlots.canvas.ax_spgr.set_xticks(self.x_tick)
        self.myPlots.canvas.ax_spgr.set_xticklabels(self.x_ticklabels, rotation=45, fontsize=8)

        if self.max_hold_ever is None:
            self.max_hold_ever = spettro_max.copy()
            self.min_hold_ever = spettro_min.copy()
        else:
            self.max_hold_ever = np.maximum(self.max_hold_ever, spettro_max)
            self.min_hold_ever = np.minimum(self.min_hold_ever, spettro_min)

        for nTpm in range(self.nof_tiles):
            self.delta_lines["TPM-%02d" % nTpm].set_data(self.t_stamps["TPM-%02d" % nTpm],
                                                         self.deltas["TPM-%02d" % nTpm])
            for ant in self.antenne:
                for npol, pol in enumerate(["Pol-X", "Pol-Y"]):
                    self.power_lines["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)].set_data(
                        self.t_stamps["TPM-%02d" % nTpm],
                        self.channel_power["TPM-%02d_ADC-%02d_%s" % (nTpm, ant, pol)])
        self.myPlots.canvas.ax_pow.set_xlim(self.tempi[0], self.tempi[-1])
        self.myPlots.canvas.ax_pow.set_ylim(np.ceil(min_chan_power)-2, np.ceil(max_chan_power)+2)
        self.myPlots.canvas.ax_delta.set_xlim(self.tempi[0], self.tempi[-1])
        self.myPlots.canvas.ax_pow.set_xticks(self.x_tick)
        self.myPlots.canvas.ax_pow.set_xticklabels(self.x_ticklabels, rotation=45, fontsize=8)
        self.myPlots.canvas.ax_delta.set_xticks(self.x_tick)
        self.myPlots.canvas.ax_delta.set_xticklabels(self.x_ticklabels, rotation=45, fontsize=8)

        self.spectra_max_lines.set_ydata(spettro_max)
        self.spectra_min_lines.set_ydata(spettro_min)
        self.spectra_max_hold_lines.set_ydata(self.max_hold_ever)
        self.spectra_min_hold_lines.set_ydata(self.min_hold_ever)

        self.myPlots.annotate_tstamp("Last Timestamp: " + ts_to_datestring(t_last) + " UTC")
        self.myPlots.annotate_records("Number of Integrations: %d" % self.records)

        self.myPlots.updatePlot()

    def closeEvent(self, event):
        result = QtWidgets.QMessageBox.question(self, "Confirm Exit...", "Are you sure you want to exit ?",
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        event.ignore()
        if result == QtWidgets.QMessageBox.Yes:
            event.accept()
            self.stopThreads = True
            self.monitor_daq.stop_daq()
            time.sleep(1)


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    app = QtWidgets.QApplication(sys.argv)
    parser = OptionParser(usage="usage: %emc_live_integrated_data [options]")
    parser.add_option("--directory", action="store", dest="directory",
                      default="/storage/integrated_channels_test",
                      help="Directory containing integrated data (default: /storage/integrated_channels_test)")
    parser.add_option("--samplerate", action="store", dest="samplerate", type=int,
                      default=8e8, help="ADC Sample Rate (Default 800 MSPS: 800e6")
    parser.add_option("--window_len", action="store", dest="window_len", type=int,
                      default=5, help="Time window to be shown on Plots (Default 5 minutes)")
    parser.add_option("--wclim", action="store", dest="wclim",
                      default="0,25", help="Waterfall Color Scale Limits (Def: '0,25')")
    parser.add_option("--title", action="store", dest="title",
                      default="", help="String to be added in the picture (example: EMC Test #1)")
    parser.add_option("--config", action="store", dest="config", type=str,
                      default=None, help="Station configuration files to use")
    (opts, args) = parser.parse_args(argv[1:])

    # Set logging
    logging.Formatter.converter = time.gmtime
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    line_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(line_format)
    log.addHandler(ch)

    # Check if a configuration file was defined
    if opts.config is None:
        log.error("A station configuration file is required, exiting")
        exit()

    directory = opts.directory
    if not directory[-1] == "/":
        directory += "/"
    directory += datetime.datetime.strftime(datetime.datetime.utcnow(), "%Y-%m-%d_%H%M%S")
    if not os.path.exists(directory):
        try:
            os.mkdir(directory)
        except:
            log.error("Unable to create directory: " + directory)
            exit()

    window_len = opts.window_len
    if window_len < 1:
        log.error("A time window greater than a minute is required (given %d)" % opts.window_len)
        exit()

    try:
        wclim = (opts.wclim.split(",")[0], opts.wclim.split(",")[1])
    except:
        log.error("Invalid Waterfall plot color format: " + opts.wclim)
        exit()

    station.load_configuration_file(opts.config)

    window = MainWindow(station.configuration, directory, window_len, wclim)
    window.show()

    window.signal.connect(window.updatePlots)
    sys.exit(app.exec_())
