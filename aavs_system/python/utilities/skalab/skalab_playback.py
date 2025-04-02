#!/usr/bin/env python
import datetime

import h5py
from PyQt5.QtCore import pyqtSignal

from skalab_base import SkalabBase
from skalab_log import SkalabLog
import sys
import os
import fnmatch
import gc
import glob
from pathlib import Path

import numpy as np
from PyQt5 import QtWidgets, uic, QtCore, QtGui
from skalab_utils import dB2Linear, linear2dB, MiniPlots, read_data, COLORI, findtiles, calc_disk_usage
from skalab_utils import calcolaspettro, closest, moving_average, clickableQLabel
from pyaavs import station
from pydaq.persisters import FileDAQModes, RawFormatFileManager

default_app_dir = str(Path.home()) + "/.skalab/"
default_profile = "Default"
profile_filename = "playback.ini"

# import warnings
# warnings.filterwarnings('ignore')
# warnings.warn('*GtkDialog mapped*')


def clickable(widget):
    class Filter(QtCore.QObject):
        clicked = QtCore.pyqtSignal()

        def eventFilter(self, obj, event):
            if obj == widget:
                if event.type() == QtCore.QEvent.MouseButtonRelease:
                    if obj.rect().contains(event.pos()):
                        self.clicked.emit()
                        return True
            return False
    filter = Filter(widget)
    widget.installEventFilter(filter)
    return filter.clicked


configuration = {'tiles': None,
                 'time_delays': None,
                 'station': {
                     'id': 0,
                     'name': "Unnamed",
                     "number_of_antennas": 256,
                     'program': False,
                     'initialise': False,
                     'program_cpld': False,
                     'enable_test': False,
                     'start_beamformer': False,
                     'bitfile': None,
                     'channel_truncation': 5,
                     'channel_integration_time': -1,
                     'beam_integration_time': -1,
                     'equalize_preadu': 0,
                     'default_preadu_attenuation': 0,
                     'beamformer_scaling': 4,
                     'pps_delays': 0},
                 'observation': {
                     'bandwidth': 8 * (400e6 / 512.0),
                     'start_frequency_channel': 50e6},
                 'network': {
                     'lmc': {
                         'tpm_cpld_port': 10000,
                         'lmc_ip': "10.0.10.200",
                         'use_teng': True,
                         'lmc_port': 4660,
                         'lmc_mac': 0x248A078F9D38,
                         'integrated_data_ip': "10.0.0.2",
                         'integrated_data_port': 5000,
                         'use_teng_integrated': True},
                     'csp_ingest': {
                         'src_ip': "10.0.10.254",
                         'dst_mac': 0x248A078F9D38,
                         'src_port': None,
                         'dst_port': 4660,
                         'dst_ip': "10.0.10.200",
                         'src_mac': None}
                    }
                 }


class Playback(SkalabBase):
    """ Main UI Window class """

    def __init__(self, config="", uiFile="", profile="Default", size=[1190, 936], swpath=default_app_dir):
        """ Initialise main window """
        self.wg = uic.loadUi(uiFile)
        self.wgProBox = QtWidgets.QWidget(self.wg.qtab_conf)
        self.wgProBox.setGeometry(QtCore.QRect(1, 1, 800, 860))
        self.wgProBox.setVisible(True)
        self.wgProBox.show()
        super(Playback, self).__init__(App="playback", Profile=profile, Path=swpath, parent=self.wgProBox)
        self.logger = SkalabLog(parent=self.wg.qw_log, logname=__name__, profile=self.profile)
        self.setCentralWidget(self.wg)
        self.resize(size[0], size[1])

        # Populate the playback plots for the spectra, and power data
        self.miniPlots = MiniPlots(parent=self.wg.qplot_spectra, nplot=16)

        # Populate the playback plots for the spectrogram
        self.spectrogramPlots = MiniPlots(parent=self.wg.qplot_spectrogram,
                                          nplot=16, xlabel="samples", ylabel="MHz",
                                          xlim=[0, 100], ylim=[0, 400])

        # Populate the playback plots for the Power
        self.powerPlots = MiniPlots(parent=self.wg.qplot_power,
                                          nplot=16, xlabel="time samples", ylabel="dB",
                                          xlim=[0, 100], ylim=[-100, 0])

        # Populate the playback plots for the Raw Data
        self.rawPlots = MiniPlots(parent=self.wg.qplot_raw,
                                          nplot=16, xlabel="time samples", ylabel="ADU",
                                          xlim=[0, 32768], ylim=[-10000, 10000])

        # Populate the playback plots for the RMS
        self.rmsPlots = MiniPlots(parent=self.wg.qplot_rms,
                                          nplot=16, xlabel="time samples", ylabel="ADU RMS",
                                          xlim=[0, 100], ylim=[0, 50])

        # Populate the playback plots for the spectrogram
        self.tempPlots = MiniPlots(parent=self.wg.qplot_temp,
                                          nplot=1, xlabel="samples", ylabel="deg",
                                          xlim=[0, 100], ylim=[20, 100], title="Temperatures")

        self.load_extras()

        self.config_file = config
        self.temp_fname = ""
        self.check_icon = None
        self.check_ok = False
        self.datasets = []
        self.saved_path = ""
        self.selected = True
        self.traces_enabled = []
        self.traces_disabled = []

        self.station_name = ""
        self.folder = ""
        self.nof_files = 0
        self.nof_tiles = 0
        self.data_tiles = []
        self.nof_antennas = 0
        self.bitfile = ""
        self.truncation = 0
        self.resolutions = 2 ** np.array(range(16)) * (800000.0 / 2 ** 15)
        self.rbw = 100
        self.avg = 2 ** self.rbw
        self.nsamples = int(2 ** 15 / self.avg)
        self.RBW = (self.avg * (400000.0 / 16384.0))
        self.asse_x = np.arange(self.nsamples/2 + 1) * self.RBW * 0.001
        self.show_rms = self.wg.qcheck_rms.isChecked()
        self.show_spectra_grid = self.wg.qcheck_spectra_grid.isChecked()
        self.show_raw_grid = self.wg.qcheck_raw_grid.isChecked()
        self.show_rms_grid = self.wg.qcheck_rms_grid.isChecked()
        self.show_power_grid = self.wg.qcheck_power_grid.isChecked()
        self.move_avg = {}

        self.input_list = np.arange(1, 17)
        self.channels_line = self.wg.qline_channels.text()

        self.xAxisRange = [float(self.wg.qline_band_from.text()), float(self.wg.qline_band_to.text())]
        self.yAxisRange = [float(self.wg.qline_level_min.text()), float(self.wg.qline_level_max.text())]

        self.tiles = []
        self.current_tile = None
        self.data = []
        self.power = {}
        self.raw = {}
        self.rms = {}

        self.show()
        self.load_events()

        # Show only the first plot view
        self.wg.qplot_spectra.show()
        self.wg.qplot_spectrogram.hide()
        self.wg.qplot_power.hide()
        self.wg.qplot_raw.hide()
        self.wg.qplot_rms.hide()

        # Show only the first plot ctrl
        self.wg.ctrl_spectrogram.hide()
        self.wg.ctrl_power.hide()
        self.wg.ctrl_raw.hide()
        self.wg.ctrl_rms.hide()
        self.wg.ctrl_spectra.show()
        self.populate_help(uifile=uiFile)

    def load_events(self):
        # RAW
        self.wg.qbutton_browse.clicked.connect(lambda: self.browse_raw_folder())
        self.wg.qbutton_load.clicked.connect(lambda: self.load_data())
        self.wg.qbutton_plot.clicked.connect(lambda: self.plot_data())
        self.wg.qcombo_tpm.currentIndexChanged.connect(self.calc_data_volume)
        self.wg.qbutton_export.clicked.connect(lambda: self.export_data())
        self.wg.qcheck_spectra_grid.stateChanged.connect(self.cb_show_spectra_grid)
        self.wg.qcheck_raw_grid.stateChanged.connect(self.cb_show_raw_grid)
        self.wg.qcheck_power_grid.stateChanged.connect(self.cb_show_power_grid)
        self.wg.qcheck_rms_grid.stateChanged.connect(self.cb_show_rms_grid)
        self.wg.qradio_power.toggled.connect(lambda: self.check_power(self.wg.qradio_power))
        self.wg.qradio_raw.toggled.connect(lambda: self.check_raw(self.wg.qradio_raw))
        self.wg.qradio_rms.toggled.connect(lambda: self.check_rms(self.wg.qradio_rms))
        self.wg.qradio_spectrogram.toggled.connect(lambda: self.check_spectrogram(self.wg.qradio_spectrogram))
        self.wg.qradio_avg.toggled.connect(lambda: self.check_avg_spectra(self.wg.qradio_avg))
        self.wg.qline_level_min.textEdited.connect(lambda: self.applyEnable())
        self.wg.qline_level_max.textEdited.connect(lambda: self.applyEnable())
        self.wg.qline_band_from.textEdited.connect(lambda: self.applyEnable())
        self.wg.qline_band_to.textEdited.connect(lambda: self.applyEnable())
        #self.wg.qbutton_apply.clicked.connect(lambda: self.applyPressed())
        self.wg.qcheck_xpol_sp.stateChanged.connect(self.cb_show_xline)
        self.wg.qcheck_ypol_sp.stateChanged.connect(self.cb_show_yline)
        self.wg.qcheck_rms.stateChanged.connect(self.cb_show_rms)
        self.wg.qbutton_save.clicked.connect(lambda: self.savePicture())
        # TEMP
        self.wg.qbutton_temp_browse.clicked.connect(lambda: self.browse_temp_file())
        self.wg.qline_filter.textChanged.connect(lambda: self.temp_filter())
        self.wg.qline_temp_ymin.returnPressed.connect(self.apply_zoom)
        self.wg.qline_temp_ymax.returnPressed.connect(self.apply_zoom)
        self.wg.qcheck_temp_grid.stateChanged.connect(self.temp_grid)
        self.wg.qcheck_temp_legend.stateChanged.connect(self.temp_legend)
        self.wg.qcheck_temp_noline.stateChanged.connect(self.temp_noline)

    def load_extras(self):
        self.qlabel_folder = clickableQLabel(self.wg.qtabRaw)
        self.qlabel_folder.setGeometry(QtCore.QRect(540, 166, 18, 18))
        self.qlabel_folder.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.qlabel_folder.setAutoFillBackground(True)
        self.qlabel_folder.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.qlabel_folder.setStyleSheet("background-color: rgb(251, 251, 251);")
        self.qlabel_folder.setText("")
        self.qlabel_folder.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.qlabel_folder.setObjectName("qlabel_folder")
        self.qlabel_folder.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_folder_16.svg"))
        self.qlabel_folder.clicked.connect(lambda: self.open_fmanager(0))
        self.qlabel_folder.setEnabled(True)

        self.qlabel_folder_2 = clickableQLabel(self.wg.qtabTemp)
        self.qlabel_folder_2.setGeometry(QtCore.QRect(230, 137, 34, 34))
        self.qlabel_folder_2.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.qlabel_folder_2.setAutoFillBackground(True)
        self.qlabel_folder_2.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.qlabel_folder_2.setStyleSheet("background-color: rgb(251, 251, 251);")
        self.qlabel_folder_2.setText("")
        self.qlabel_folder_2.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.qlabel_folder_2.setObjectName("qlabel_folder")
        self.qlabel_folder_2.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_folder_32.svg"))
        self.qlabel_folder_2.clicked.connect(lambda: self.open_fmanager(1))
        self.qlabel_folder_2.setEnabled(True)

        self.qlabel_select = clickableQLabel(self.wg.qtabTemp)
        self.qlabel_select.setGeometry(QtCore.QRect(900, 144, 32, 32))
        self.qlabel_select.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.qlabel_select.setAutoFillBackground(True)
        self.qlabel_select.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.qlabel_select.setStyleSheet("background-color: rgb(251, 251, 251);")
        self.qlabel_select.setText("")
        self.qlabel_select.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.qlabel_select.setObjectName("qlabel_select")
        self.qlabel_select.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_none_32.png"))
        self.qlabel_select.clicked.connect(self.temp_selection)

        self.wg.qcheck_temp_datetime.setToolTip("DateTime format: yyyy-mm-dd hh:mm:ss\nRecords format from 0 to lenght of data")
        self.wg.qlabel_check_icon.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_folder_32.svg"))

    def setup_config(self):
        if not self.config_file == "":
            station.load_configuration_file(self.config_file)
            self.station_name = station.configuration['station']['name']
            self.nof_tiles = len(station.configuration['tiles'])
            self.nof_antennas = int(station.configuration['station']['number_of_antennas'])
            self.bitfile = station.configuration['station']['bitfile']
            self.truncation = int(station.configuration['station']['channel_truncation'])
            self.wg.qcombo_tpm.clear()
            self.tiles = []
            for n, i in enumerate(station.configuration['tiles']):
                self.wg.qcombo_tpm.addItem("TILE-%02d (%s)" % (n + 1, i))
                self.tiles += [i]
        else:
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText("PLAYBACK: Please SELECT a valid configuration file first...")
            msgBox.setWindowTitle("Error!")
            msgBox.exec_()

    def play_tpm_update(self):
        # Update TPM list
        self.wg.qcombo_tpm.clear()
        for i in self.data_tiles:
            self.wg.qcombo_tpm.addItem("TILE-%02d" % (i + 1))

    # def reload(self):
    #     self.wg.qline_configfile.setText(self.profile['Playback']['station_file'])

    def browse_raw_folder(self):
        fd = QtWidgets.QFileDialog()
        fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        options = fd.options()
        self.folder = fd.getExistingDirectory(self, caption="Choose a data folder",
                                              directory=self.profile['Playback']['data_path'], options=options)
        self.wg.qline_datapath.setText(self.folder)
        self.check_dir()
        self.calc_data_volume()
        if not self.data_tiles:
            self.wg.qbutton_load.setEnabled(False)
        else:
            self.wg.qbutton_load.setEnabled(True)

    def browse_temp_file(self):
        fd = QtWidgets.QFileDialog()
        fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        fd.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        options = fd.options()
        self.temp_fname = fd.getOpenFileName(self, caption="Choose a data file",
                                         directory=self.profile['Playback']['data_path'], options=options)[0]
        self.wg.qlabel_temp_datapath.setText(self.temp_fname[self.temp_fname.rfind("/")+1:])
        self.wg.qlabel_path.setText(self.temp_fname[:self.temp_fname.rfind("/")+1])
        self.check_file()
        if self.check_ok:
            self.load_temp()
            self.plot_temp()

    def check_dir(self):
        if not self.wg.qline_datapath.text() == "":
            self.data_tiles = findtiles(directory=self.wg.qline_datapath.text())
            if len(self.data_tiles):
                self.wg.qlabel_check_icon_raw.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_ok_32.png"))
                if len(self.data_tiles) > 1:
                    self.wg.qlabel_dircheck.setText("Found %d Tiles" % len(self.data_tiles))
                else:
                    self.wg.qlabel_dircheck.setText("Found 1 Tile")
            else:
                self.wg.qlabel_check_icon_raw.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_error_32.png"))
                self.wg.qlabel_dircheck.setText("Empty directory!")
            self.play_tpm_update()
        else:
            self.wg.qlabel_check_icon_raw.clear()

    def open_fmanager(self, code):
        if code == 0:
            if self.saved_path == "":
                os.system("xdg-open /") # + self.saved_path)
            else:
                os.system("xdg-open " + self.saved_path)
        elif code == 1:
            if self.wg.qlabel_path.text() != "-":
                os.system("xdg-open " + self.wg.qlabel_path.text())
            else:
                os.system("xdg-open /")


    def check_file(self):
        data_range = "Data Range:     -"
        if not self.wg.qlabel_temp_datapath.text() == "":
            if os.path.exists(self.temp_fname):
                try:
                    f = h5py.File(self.temp_fname)
                    self.datasets = []
                    for k in sorted(f.keys()):
                        if f[k].shape[1] == 1:
                            self.datasets += [k]
                        else:
                            for n in np.arange(f[k].shape[1]):
                                self.datasets += [k + "_Sens-%02d" % (n + 1)]

                    # self.wg.cb_datasets.clear()
                    # self.wg.cb_datasets.addItems(["None"] + sorted(self.datasets))
                    # self.wg.cb_datasets.setCurrentIndex(0)
                    if "timestamp" in self.datasets:
                        self.wg.qlabel_records.setText("%d" % len(f['timestamp']))
                        self.wg.qline_temp_xmin.setText("0")
                        self.wg.qline_temp_xmax.setText("%d" % len(f['timestamp']))
                        data_range = datetime.datetime.strftime(datetime.datetime.utcfromtimestamp(f['timestamp'][:, 0].tolist()[0]), "Data Range:     %Y-%m-%d %H:%M:%S")
                        data_range += datetime.datetime.strftime(datetime.datetime.utcfromtimestamp(f['timestamp'][:, 0].tolist()[-1]), "  -   %Y-%m-%d %H:%M:%S  UTC")
                        #self.wg.cb_datasets.setCurrentText("timestamp")
                    else:
                        self.wg.qlabel_records.setText("{:d}".format(len(f[f.keys()[0]])))
                        self.wg.qlabel_check_icon.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_warning_32.png"))
                        self.wg.qlabel_check_icon.setToolTip("WARNING: Timestamps not found!!!")
                        data_range = "Data Range:     Missing Timestamp Dataset in the HDF5 File"
                    f.close()
                    self.wg.qlabel_check_icon.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_ok_32.png"))
                    self.wg.qlabel_check_icon.setToolTip("HDF5 File check OK")
                    self.check_ok = True
                except Exception as error:
                    self.wg.qlabel_datacheck.setText("ERROR: This HDF5 File is corrupted!!!")
                    self.wg.qlabel_check_icon.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_error_32.png"))
                    self.wg.qlabel_check_icon.setToolTip("ERROR: This HDF5 File is corrupted!!!")
                    self.wg.qlabel_records.setText("-")
                    # self.wg.cb_datasets.clear()
                    self.temp_fname = ""
                    self.check_ok = False
                    print(error)
            else:
                self.wg.qlabel_records.setText("-")
                # self.wg.cb_datasets.clear()
                self.temp_fname = ""
                self.check_ok = False
                self.wg.qlabel_check_icon.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_warning_32.png"))
                self.wg.qlabel_check_icon.setToolTip("This file does not exist...")
        else:
            self.wg.qlabel_check_icon.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_folder_32.svg"))
            self.wg.qlabel_check_icon.setToolTip("Please select a Temperature file...")
            self.wg.qlabel_path.setText("-")
            self.wg.qlabel_records.setText("-")
            # self.wg.cb_datasets.clear()
            self.temp_fname = ""
            self.check_ok = False
        self.wg.qlabel_temp_datarange.setText(data_range)

    def load_temp(self):
        if self.check_ok:
            self.traces_enabled = []
            self.traces_disabled = []
            f = h5py.File(self.temp_fname)
            self.temp_data = {}
            n_elem = 0
            for j, k in enumerate(sorted(f.keys())):
                if k == "timestamp":
                    self.temp_data[k] = {}
                    self.temp_data[k]['data'] = {}
                    self.temp_data[k]['data'] = f[k][:, 0].tolist()
                    # self.temp_data[k]['str'] = [""] * len(self.temp_data[k]['data'])
                    # for n, tstamp in enumerate(self.temp_data[k]['data']):
                    #     self.temp_data[k]['str'][n] = datetime.datetime.strftime(
                    #         datetime.datetime.utcfromtimestamp(int(tstamp)), "%Y-%m-%d %H:%M:%S")
                else:
                    if f[k].shape[1] == 1:
                        colore = COLORI[n_elem]
                        self.temp_data[k] = {}
                        self.temp_data[k]['data'] = f[k][:, 0].tolist()
                        self.temp_data[k]['color'] = colore
                        self.temp_data[k]['cbox'] = QtWidgets.QCheckBox(self.wg.qscroll_content)
                        self.temp_data[k]['cbox'].setChecked(True)
                        self.temp_data[k]['cbox'].stateChanged.connect(lambda t=k:  self.enable_trace(t))
                        self.temp_data[k]['cbox'].setText(k)
                        self.temp_data[k]['cbox'].setStyleSheet("color: rgb(" + str(colore.red()) + ", " +
                                                                str(colore.green()) + ", " +
                                                                str(colore.blue()) + ");")
                        self.wg.tracesGridLayout.addWidget(self.temp_data[k]['cbox'], n_elem, 0, 1, 1)
                        self.traces_enabled += [k]
                        n_elem = n_elem + 1
                    else:
                        for n in np.arange(f[k].shape[1]):
                            new_name = k + "_Sens-%02d" % (n + 1)
                            colore = COLORI[n_elem]
                            self.temp_data[new_name] = {}
                            self.temp_data[new_name]['data'] = f[k][:, n].tolist()
                            self.temp_data[new_name]['color'] = colore
                            self.temp_data[new_name]['cbox'] = QtWidgets.QCheckBox(self.wg.qscroll_content)
                            self.temp_data[new_name]['cbox'].setChecked(True)
                            self.temp_data[new_name]['cbox'].stateChanged.connect(lambda state, t=new_name:
                                                                                  self.enable_trace(state, t))
                            self.temp_data[new_name]['cbox'].setText(new_name)
                            self.temp_data[new_name]['cbox'].setStyleSheet("color: rgb(" + str(colore.red()) + ", " +
                                                                    str(colore.green()) + ", " +
                                                                    str(colore.blue()) + ");")
                            self.wg.tracesGridLayout.addWidget(self.temp_data[new_name]['cbox'], n_elem, 0, 1, 1)
                            self.traces_enabled += [new_name]
                            n_elem = n_elem + 1
            f.close()

    def enable_trace(self, state, trace):
        if state:
            self.tempPlots.hide_line(trace, True)
        else:
            self.tempPlots.hide_line(trace, False)
        self.traces_enabled = []
        self.traces_disabled = []
        for d in self.datasets:
            if not d == 'timestamp':
                if fnmatch.fnmatch(d, self.wg.qline_filter.text()):
                    if self.temp_data[d]['cbox'].isChecked():
                        self.traces_enabled += [d]
                    else:
                        self.traces_disabled += [d]
                else:
                    self.traces_disabled += [d]
        self.temp_noline()
        self.temp_legend()

    def temp_selection(self):
        if self.selected:
            self.tempPlots.hide_lines(self.traces_enabled, False)
            self.qlabel_select.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_all_32.png"))
            self.selected = False
            # for d in self.traces_enabled:
            #     if not d == "timestamp":
            #         self.temp_data[d]['cbox'].setChecked(False)
        else:
            self.tempPlots.hide_lines(self.traces_enabled, True)
            self.qlabel_select.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_none_32.png"))
            self.selected = True
            # for d in self.traces_enabled:
            #     if not d == "timestamp":
            #         self.temp_data[d]['cbox'].setChecked(True)
        self.temp_noline()
        self.temp_legend()

    def temp_filter(self):
        #print("Removing %d elements from grid" % self.wg.tracesGridLayout.count())
        for i in range(self.wg.tracesGridLayout.count()):
            item = self.wg.tracesGridLayout.takeAt(0)
            item.widget().setVisible(False)
        #self.wg.tracesGridLayout.update()
        n_elem = 0
        self.traces_enabled = []
        self.traces_disabled = []
        #print(self.datasets)
        for d in self.datasets:
            if not d == 'timestamp':
                if fnmatch.fnmatch(d, self.wg.qline_filter.text()):
                    #print(self.wg.qline_filter.text(), "--->", d, "--->  True")
                    self.wg.tracesGridLayout.addWidget(self.temp_data[d]['cbox'], n_elem, 0, 1, 1)
                    self.temp_data[d]['cbox'].setVisible(True)
                    # self.traces_enabled += [d]
                    # self.temp_data[d]['cbox'].setChecked(True)
                    n_elem = n_elem + 1
                    if self.temp_data[d]['cbox'].isChecked():
                        self.traces_enabled += [d]
                    else:
                        self.traces_disabled += [d]
                else:
                    self.traces_disabled += [d]
                    #print(self.wg.qline_filter.text(), "--->", d, "--->  False")
                    #self.temp_data[d]['cbox'].setChecked(False)
        self.tempPlots.hide_lines(self.traces_enabled, True)
        self.tempPlots.hide_lines(self.traces_disabled, False)
        #print("Showing %d elements in grid" % self.wg.tracesGridLayout.count())
        self.temp_noline()
        self.temp_legend()

    def plot_temp(self):
        for n, k in enumerate(self.datasets):
            if not k == "timestamp":
                self.tempPlots.plotCurve(self.temp_data['timestamp']['data'],
                                         self.temp_data[k]['data'], 0, name=k,
                                         xAxisRange=[self.temp_data['timestamp']['data'][0],
                                                     self.temp_data['timestamp']['data'][-1]],
                                         yAxisRange=[20, 100], title="TPM Station Temperatures", xLabel="timestamp",
                                         yLabel="deg", colore=COLORI[n], annotate_rms=False, markersize=3,
                                         grid=self.wg.qcheck_temp_grid.isChecked(), lw=2,
                                         show_line=(not self.wg.qcheck_temp_noline.isChecked()))
        self.tempPlots.updatePlot()

    def apply_zoom(self):
        try:
            ymin = float(self.wg.qline_temp_ymin.text())
            ymax = float(self.wg.qline_temp_ymax.text())
            self.tempPlots.set_y_limits([ymin, ymax])
        except:
            pass

    def temp_grid(self):
        self.tempPlots.showGrid(self.wg.qcheck_temp_grid.isChecked())

    def temp_legend(self):
        if self.wg.qcheck_temp_legend.isChecked():
            self.tempPlots.showLegend(self.traces_enabled)
        else:
            self.tempPlots.showLegend([])

    def temp_noline(self):
        if self.wg.qcheck_temp_noline.isChecked():
            self.tempPlots.set_line_width(self.traces_enabled, 0)
        else:
            self.tempPlots.set_line_width(self.traces_enabled, 2)

    def calc_data_volume(self):
        if not self.wg.qline_datapath.text() == "":
            if len(self.data_tiles):
                self.wg.qlabel_dataload.setText("Data Volume: " + calc_disk_usage(self.wg.qline_datapath.text(),
                        "raw_burst_%d_*.hdf5" % int(self.data_tiles[self.wg.qcombo_tpm.currentIndex()])))
                # self.wg.qlabel_dataload.setText("# Files: %d" %
                #         dircheck(self.wg.qline_datapath.text(),
                #                  int(self.data_tiles[self.wg.qcombo_tpm.currentIndex()])) +
                #         ", Data Volume: " + calc_disk_usage(self.wg.qline_datapath.text(),
                #         "raw_burst_%d_*.hdf5" % int(self.data_tiles[self.wg.qcombo_tpm.currentIndex()])))

    def load_data(self):
        if not self.wg.qline_datapath.text() == "":
            if os.path.isdir(self.wg.qline_datapath.text()):
                lista = sorted(glob.glob(self.wg.qline_datapath.text() + "/raw_burst_%d_*hdf5" % int(
                    self.data_tiles[self.wg.qcombo_tpm.currentIndex()])))
                self.nof_files = len(lista)
                if self.nof_files:
                    progress_format = "TILE-%02d   " % (self.data_tiles[self.wg.qcombo_tpm.currentIndex()] + 1) + "%p%"
                    self.wg.qprogress_load.setFormat(progress_format)

                    file_manager = RawFormatFileManager(root_path=self.wg.qline_datapath.text(),
                                                        daq_mode=FileDAQModes.Burst)
                    del self.data
                    gc.collect()
                    self.data = []
                    for nn, l in enumerate(lista):
                        # Call the data Load
                        t, d = read_data(fmanager=file_manager,
                                         hdf5_file=l,
                                         tile=self.data_tiles[self.wg.qcombo_tpm.currentIndex()],
                                         nof_tiles=self.nof_tiles)
                        self.current_tile = self.data_tiles[self.wg.qcombo_tpm.currentIndex()] + 1
                        if t:
                            self.data += [{'timestamp': t, 'data': d}]
                        self.wg.qprogress_load.setValue(int((nn + 1) * 100 / len(lista)))
                    self.wg.qline_sample_start.setText("1")
                    self.wg.qline_sample_stop.setText("%d" % len(lista))
                    self.wg.qline_avg_sample_stop.setText("%d" % len(lista))
                    self.wg.qline_power_sample_stop.setText("%d" % len(lista))
                    self.wg.qline_rms_sample_stop.setText("%d" % len(lista))
                    self.wg.qlabel_raw_filenum.setText("Select File Number (%d-%d)" % (1, self.nof_files))
                    self.wg.qline_raw_filenum.setText("1")
                else:
                    self.wg.qlabel_raw_filenum.setText("Select File Number (#)")
                    self.wg.qline_raw_filenum.setText("0")
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Please SELECT a valid data directory first...")
                msgBox.setWindowTitle("Error!")
                msgBox.exec_()
        else:
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText("Please SELECT a valid data directory first...")
            msgBox.setWindowTitle("Error!")
            msgBox.exec_()

    def plot_data(self):
        if not self.wg.qline_channels.text() == self.channels_line:
            self.reformat_plots()

        self.resolutions = 2 ** np.array(range(16)) * (800000.0 / 2 ** 15)
        if self.wg.qradio_spectrogram.isChecked():
            self.rbw = int(closest(self.resolutions, float(self.wg.qline_spg_rbw.text())))
        elif self.wg.qradio_power.isChecked():
            self.rbw = int(closest(self.resolutions, float(self.wg.qline_power_rbw.text())))
        else:
            self.rbw = int(closest(self.resolutions, float(self.wg.qline_rbw.text())))
        self.avg = 2 ** self.rbw
        self.nsamples = int(2 ** 15 / self.avg)
        self.RBW = (self.avg * (400000.0 / 16384.0))
        self.asse_x = np.arange(self.nsamples / 2 + 1) * self.RBW * 0.001

        if self.wg.qradio_spectrogram.isChecked():
            self.wg.qcheck_rms.setEnabled(False)
            xAxisRange = (float(self.wg.qline_spg_band_from.text()),
                          float(self.wg.qline_spg_band_to.text()))
            xmin = closest(self.asse_x, xAxisRange[0])
            xmax = closest(self.asse_x, xAxisRange[1])
            yticksteps = int((xAxisRange[1] - xAxisRange[0]) / 5)

            pol = 0
            if self.wg.qcheck_ypol_spg.isChecked():
                pol = 1
            if not self.data == []:
                self.miniPlots.plotClear()
                allspgram = []
                gc.collect()
                wclim = (int(self.wg.qline_spg_color_min.text()), int(self.wg.qline_spg_color_max.text()))
                for n in range(len(self.input_list)):
                    allspgram += [[]]
                    allspgram[n] = np.empty((3, xmax - xmin + 1,))
                    allspgram[n][:] = np.nan
                t_start = int(self.wg.qline_sample_start.text())
                t_stop = int(self.wg.qline_sample_stop.text())
                for k in range(t_start, t_stop):
                    for num, tpm_input in enumerate(self.input_list):
                        spettro, rfpow, rms = calcolaspettro(self.data[k]['data'][tpm_input - 1, pol, :], self.nsamples)
                        allspgram[num] = np.concatenate((allspgram[num], [spettro[xmin:xmax + 1]]), axis=0)
                    self.wg.qprogress_plot.setValue(int((k - t_start + 1) * 100 / (t_stop - t_start)))
                for num, tpm_input in enumerate(self.input_list):
                    first_empty, allspgram[num] = allspgram[num][:3], allspgram[num][3:]
                    self.spectrogramPlots.plotSpectrogram(spettrogramma=allspgram[num], ant=num, ytickstep=yticksteps,
                                                          xmin=t_start, xmax=t_stop, startfreq=xAxisRange[0],
                                                          stopfreq=xAxisRange[1], title="INPUT-%02d" % int(tpm_input),
                                                          wclim=wclim)
                self.spectrogramPlots.updatePlot()
                self.wg.qbutton_save.setEnabled(True)

        elif self.wg.qradio_avg.isChecked():
            lw = 1
            if self.wg.qcheck_spectra_noline.isChecked():
                lw = 0
            if not self.data == []:
                #self.miniPlots.plotClear()
                spettri_x = [np.zeros(len(self.asse_x))] * len(self.input_list)
                rms_x = [0] * len(self.input_list)
                spettri_y = [np.zeros(len(self.asse_x))] * len(self.input_list)
                # rms_y = [[] for _ in range(len(self.input_list))]
                rms_y = [0] * len(self.input_list)
                avgnum = int(self.wg.qline_avg_sample_stop.text()) - int(self.wg.qline_avg_sample_start.text())
                for k in range(int(self.wg.qline_avg_sample_start.text())-1,
                               int(self.wg.qline_avg_sample_stop.text())-1):
                    for n, i in enumerate(self.input_list):
                        # Plot X Pol
                        spettro, rfpow, rms = calcolaspettro(self.data[k]['data'][i - 1, 0, :], self.nsamples)
                        spettri_x[n] = np.add(spettri_x[n], dB2Linear(spettro))
                        rms_x[n] = np.add(rms_x[n], dB2Linear(rfpow))

                        # Plot Y Pol
                        spettro, rfpow, rms = calcolaspettro(self.data[k]['data'][i - 1, 1, :], self.nsamples)
                        spettri_y[n] = np.add(spettri_y[n], dB2Linear(spettro))
                        rms_y[n] = np.add(rms_y[n], dB2Linear(rfpow))
                    self.wg.qprogress_plot.setValue(int((k + 1) * 100 / avgnum))
                for n, i in enumerate(self.input_list):
                    # Plot X Pol
                    spettro = linear2dB(spettri_x[n] / avgnum)
                    rms = linear2dB(rms_x[n] / avgnum)
                    self.miniPlots.plotCurve(self.asse_x, spettro, n, xAxisRange=self.xAxisRange,
                                             yAxisRange=self.yAxisRange, title="INPUT-%02d" % i,
                                             xLabel="MHz", yLabel="dB", colore=COLORI[0], rfpower=rms,
                                             annotate_rms=self.show_rms, grid=self.show_spectra_grid, lw=lw,
                                             show_line=self.wg.qcheck_xpol_sp.isChecked(),
                                             rms_position=float(self.wg.qline_rms_pos.text()))
                    # Plot Y Pol
                    spettro = linear2dB(spettri_y[n] / avgnum)
                    rms = linear2dB(rms_y[n] / self.nof_files)
                    self.miniPlots.plotCurve(self.asse_x, spettro, n, xAxisRange=self.xAxisRange,
                                             yAxisRange=self.yAxisRange, colore=COLORI[1], rfpower=rms,
                                             annotate_rms=self.show_rms, grid=self.show_spectra_grid, lw=lw,
                                             show_line=self.wg.qcheck_ypol_sp.isChecked(),
                                             rms_position=float(self.wg.qline_rms_pos.text()))
                self.wg.qcheck_rms.setEnabled(True)
                self.wg.qcheck_spectra_grid.setEnabled(True)
                self.miniPlots.updatePlot()
                self.wg.qbutton_save.setEnabled(True)
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Please LOAD a data set first...")
                msgBox.setWindowTitle("Error!")
                msgBox.exec_()

        elif self.wg.qradio_power.isChecked():
            move_avg_len = int(float(self.wg.qline_movavgwdw.text()))
            if self.wg.qcheck_movavg.isChecked() and (move_avg_len < 2):
                self.logger.logger.error("Invalid Moving Average Window Length. It must be greater than 1. (found %d)"
                               % move_avg_len)
            else:
                lw = 1
                if self.wg.qcheck_power_noline.isChecked():
                    lw = 0
                if not self.data == []:
                    xAxisRange = (float(self.wg.qline_power_sample_start.text()),
                                  float(self.wg.qline_power_sample_stop.text()))
                    yAxisRange = (float(self.wg.qline_power_level_min.text()),
                                  float(self.wg.qline_power_level_max.text()))
                    self.powerPlots.plotClear()
                    for n, i in enumerate(self.input_list):
                        for npol, pol in enumerate(["Pol-X", "Pol-Y"]):
                            self.power["Input-%02d_%s" % (i, pol)] = []
                            self.power["Input-%02d_%s_adc-clip" % (i, pol)] = []
                    self.power_x = []
                    for k in range(self.nof_files):
                        self.power_x += [self.data[k]['timestamp']]
                        for n, i in enumerate(self.input_list):
                            for npol, pol in enumerate(["Pol-X", "Pol-Y"]):
                                if 127 in self.data[k]['data'][i - 1, npol, :] or \
                                        -128 in self.data[k]['data'][i - 1, npol, :]:
                                    self.power["Input-%02d_%s_adc-clip" % (i, pol)] += [self.data[k]['timestamp']]
                                spettro, rfpow, rms = calcolaspettro(self.data[k]['data'][i - 1, npol, :], self.nsamples, log=False)
                                bandpower = np.sum(spettro[closest(self.asse_x, float(self.wg.qline_power_band_from.text())): closest(self.asse_x, float(self.wg.qline_power_band_to.text()))])
                                if not len(self.power["Input-%02d_%s" % (i, pol)]):
                                    self.power["Input-%02d_%s" % (i, pol)] = [linear2dB(bandpower)]
                                else:
                                    self.power["Input-%02d_%s" % (i, pol)] += [linear2dB(bandpower)]
                        self.wg.qprogress_plot.setValue(int((k + 1) * 100 / self.nof_files))

                    if not self.wg.qcheck_datetime.isChecked():
                        self.power_x = range(len(self.power_x))
                    self.move_avg = {}
                    if self.wg.qcheck_movavg.isChecked():
                        if move_avg_len > len(self.power_x):
                            self.logger.logger.error("Invalid Moving Average Window Length. "
                                           "Forced to the maximum allowed length as size of data vector %d" % len(x))
                            move_avg_len = len(self.power_x)
                            self.power_x = [self.power_x[int(move_avg_len / 2)]]
                        elif move_avg_len == 2:
                            self.power_x = self.power_x[1:]
                        else:
                            self.power_x = self.power_x[int(move_avg_len / 2): - (move_avg_len - (int(move_avg_len / 2))) + 1]
                        xAxisRange = (self.power_x[0], self.power_x[-1])
                    for n, i in enumerate(self.input_list):
                        # Plot X Pol
                        self.move_avg["Input-%02d_Pol-X" % i] = self.power["Input-%02d_Pol-X" % i].copy()
                        if self.wg.qcheck_movavg.isChecked():
                            self.move_avg["Input-%02d_Pol-X" % i] = moving_average(self.power["Input-%02d_Pol-X" % i].copy(), move_avg_len)

                        self.powerPlots.plotPower(self.power_x, self.move_avg["Input-%02d_Pol-X" % i], n, xAxisRange=xAxisRange,
                                                  yAxisRange=yAxisRange, title="INPUT-%02d" % i, xLabel="time samples",
                                                  yLabel="dB", colore=COLORI[0], grid=self.show_power_grid, lw=lw,
                                                  show_line=self.wg.qcheck_xpol_power.isChecked(),
                                                  xdatetime=self.wg.qcheck_datetime.isChecked())
                        self.move_avg["Input-%02d_Pol-Y" % i] = self.power["Input-%02d_Pol-Y" % i].copy()
                        if self.wg.qcheck_movavg.isChecked():
                            self.move_avg["Input-%02d_Pol-Y" % i] = moving_average(self.power["Input-%02d_Pol-Y" % i].copy(), move_avg_len)
                        self.powerPlots.plotPower(self.power_x, self.move_avg["Input-%02d_Pol-Y" % i], n, xAxisRange=xAxisRange,
                                                  colore=COLORI[1], show_line=self.wg.qcheck_ypol_power.isChecked(), lw=lw,
                                                  xdatetime=self.wg.qcheck_datetime.isChecked())
                    self.powerPlots.updatePlot()
                    self.wg.qbutton_export.setEnabled(True)
                    self.wg.qbutton_save.setEnabled(True)
                    # print("First tstamp: %d" % int(self.data[0]['timestamp']))
                    # print("Last  tstamp: %d" % int(self.data[self.nof_files - 1]['timestamp']))

        elif self.wg.qradio_raw.isChecked():
            if 1 <= int(self.wg.qline_raw_filenum.text()) <= self.nof_files:
                lw = 1
                msize = 0
                if self.wg.qcheck_raw_noline.isChecked():
                    lw = 0
                    msize = 1
                if not self.data == []:
                    xAxisRange = (float(self.wg.qline_raw_start.text()),
                                  float(self.wg.qline_raw_stop.text()))
                    yAxisRange = (float(self.wg.qline_raw_min.text()),
                                  float(self.wg.qline_raw_max.text()))
                    #self.rawPlots.plotClear()
                    for n, i in enumerate(self.input_list):
                        for npol, pol in enumerate(["Pol-X", "Pol-Y"]):
                            self.raw["Input-%02d_%s" % (i, pol)] = []
                            self.raw["Input-%02d_%s_adc-clip" % (i, pol)] = []
                    for k in [int(self.wg.qline_raw_filenum.text()) - 1]:
                        for n, i in enumerate(self.input_list):
                            for npol, pol in enumerate(["Pol-X", "Pol-Y"]):
                                if 127 in self.data[k]['data'][i - 1, npol, :] or \
                                        -128 in self.data[k]['data'][i - 1, npol, :]:
                                    self.raw["Input-%02d_%s_adc-clip" % (i, pol)] += [self.data[k]['timestamp']]
                                self.raw["Input-%02d_%s" % (i, pol)] = self.data[k]['data'][i - 1, npol, :]
                    for n, i in enumerate(self.input_list):
                        self.rawPlots.plotCurve(np.arange(len(self.raw["Input-%02d_Pol-X" % i])),
                                                 self.raw["Input-%02d_Pol-X" % i], n, xAxisRange=xAxisRange,
                                                 yAxisRange=yAxisRange, title="INPUT-%02d" % i, xLabel="samples",
                                                 yLabel="ADU", colore=COLORI[0], annotate_rms=False, markersize=msize,
                                                 grid=self.show_raw_grid, lw=lw, rms_position=140,
                                                 show_line=self.wg.qradio_raw_x.isChecked())
                        self.rawPlots.plotCurve(np.arange(len(self.raw["Input-%02d_Pol-Y" % i])),
                                                 self.raw["Input-%02d_Pol-Y" % i], n, xAxisRange=xAxisRange,
                                                 yAxisRange=yAxisRange, title="INPUT-%02d" % i, xLabel="samples",
                                                 yLabel="ADU", colore=COLORI[1], annotate_rms=False, markersize=msize,
                                                 grid=self.show_raw_grid, lw=lw, rms_position=140,
                                                 show_line=self.wg.qradio_raw_y.isChecked())
                        self.wg.qprogress_plot.setValue(int((k + 1) * 100 / 1))
                    self.rawPlots.updatePlot()
                self.wg.qbutton_export.setEnabled(True)
                self.wg.qbutton_save.setEnabled(True)

            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Please select a file number within the range 1-%d." % self.nof_files)
                msgBox.setWindowTitle("Error!")
                msgBox.exec_()

        elif self.wg.qradio_rms.isChecked():
            lw = 1
            if self.wg.qcheck_rms_noline.isChecked():
                lw = 0
            if not self.data == []:
                xAxisRange = (float(self.wg.qline_rms_sample_start.text()),
                              float(self.wg.qline_rms_sample_stop.text()))
                if self.wg.qcheck_raw_dbm.isChecked():
                    yAxisRange = (float(self.wg.qline_rms_level_min.text()),
                                  float(self.wg.qline_rms_level_max.text()))
                else:
                    yAxisRange = (float(self.wg.qline_rms_min.text()),
                                  float(self.wg.qline_rms_max.text()))

                self.rmsPlots.plotClear()
                for n, i in enumerate(self.input_list):
                    for npol, pol in enumerate(["Pol-X", "Pol-Y"]):
                        self.rms["Input-%02d_%s" % (i, pol)] = []
                for k in range(self.nof_files):
                    for n, i in enumerate(self.input_list):
                        for npol, pol in enumerate(["Pol-X", "Pol-Y"]):
                            spettro, rfpow, rms = calcolaspettro(self.data[k]['data'][i - 1, npol, :], self.nsamples,
                                                                 log=False)
                            #print("FILE:", k, "INPUT:", i-1, "POL:", pol, "RMS:", rms)
                            if self.wg.qcheck_raw_dbm.isChecked():
                                self.rms["Input-%02d_%s" % (i, pol)] = np.append(self.rms["Input-%02d_%s" % (i, pol)], rfpow)
                            else:
                                self.rms["Input-%02d_%s" % (i, pol)] = np.append(self.rms["Input-%02d_%s" % (i, pol)], rms)
                    self.wg.qprogress_plot.setValue(int((k + 1) * 100 / self.nof_files))

                for n, i in enumerate(self.input_list):
                    # Plot X Pol
                    self.rmsPlots.plotPower(range(len(self.rms["Input-%02d_Pol-X" % i])),
                                            self.rms["Input-%02d_Pol-X" % i] , n, xAxisRange=xAxisRange,
                                            yAxisRange=yAxisRange, title="INPUT-%02d" % i, xLabel="time samples",
                                            yLabel="ADU RMS", colore=COLORI[0], grid=self.show_rms_grid, lw=lw,
                                            show_line=self.wg.qcheck_xpol_rms.isChecked())
                    self.rmsPlots.plotPower(range(len(self.rms["Input-%02d_Pol-Y" % i])),
                                            self.rms["Input-%02d_Pol-Y" % i], n, colore=COLORI[1],
                                            show_line=self.wg.qcheck_ypol_rms.isChecked(), lw=lw)
                self.rmsPlots.updatePlot()
                self.wg.qbutton_save.setEnabled(True)

    def export_data(self):
        if self.wg.qradio_spectrogram.isChecked():
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText("Spectrogram Data Export is not yet implemented")
            msgBox.setWindowTitle("Message")
            msgBox.exec_()
            pass
        elif self.wg.qradio_avg.isChecked():
            pass
        elif self.wg.qradio_power.isChecked():
            msg = "Are you sure you want to export %d files?\n(both x-y pols will be saved)" % (
                        len(self.input_list) * 2)
            result = QtWidgets.QMessageBox.question(self, "Export Data...", msg,
                                                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if result == QtWidgets.QMessageBox.Yes:
                fpath = str(QtWidgets.QFileDialog.getExistingDirectory(self, "Select a destination Directory"))
                if os.path.exists(fpath) and fpath:
                    self.logger.logger.info("Saving data in " + fpath)
                    for k in self.move_avg.keys():
                        self.logger.logger.info("Saving: " + fpath + "/" + k + ".txt")
                        with open(fpath + "/" + k + ".txt", "w") as f:
                            for n, d in enumerate(self.move_avg[k]):
                                f.write("%d\t%6.3f\n" % (self.power_x[n], d))

        elif self.wg.qradio_raw.isChecked():
            result = QtWidgets.QMessageBox.question(self, "Export Data...",
                        "Are you sure you want to export %d files?" % (len(self.input_list)),
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if result == QtWidgets.QMessageBox.Yes:
                print("Saving data")
            else:
                print("ciao")

    def savePicture(self):
        if self.current_tile is not None:
            if self.wg.qradio_spectrogram.isChecked():
                result = QtWidgets.QMessageBox.question(self, "Save Picture...",
                            "Are you sure you want to save this picture?",
                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if result == QtWidgets.QMessageBox.Yes:
                    self.saved_path = str(QtWidgets.QFileDialog.getExistingDirectory(self, "Select a destination Directory"))
                    if os.path.exists(self.saved_path) and self.saved_path:
                        tnow = "TILE-%02d_SPECTOGRAM_SAVED_ON_" % self.current_tile
                        tnow += datetime.datetime.strftime(datetime.datetime.utcnow(), "%Y-%m-%d_%H%M%S.png")
                        self.logger.logger.info("Saving: " + self.saved_path + "/" + tnow)
                        self.spectrogramPlots.savePicture(self.saved_path + "/" + tnow)
                        self.wg.qlabel_check_icon_action.setPixmap(
                            QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_ok_16.png"))
                        self.qlabel_folder.setEnabled(True)
                        self.wg.qlabel_action_comment.setText("Saved picture: " + tnow)

            elif self.wg.qradio_avg.isChecked():
                result = QtWidgets.QMessageBox.question(self, "Save Picture...",
                            "Are you sure you want to save this picture?",
                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if result == QtWidgets.QMessageBox.Yes:
                    self.saved_path = str(QtWidgets.QFileDialog.getExistingDirectory(self, "Select a destination Directory"))
                    if os.path.exists(self.saved_path) and self.saved_path:
                        tnow = "TILE-%02d_AVERAGED_SPECTRA_SAVED_ON_" % self.current_tile
                        tnow += datetime.datetime.strftime(datetime.datetime.utcnow(), "%Y-%m-%d_%H%M%S.png")
                        self.logger.logger.info("Saving: " + self.saved_path + "/" + tnow)
                        self.miniPlots.savePicture(self.saved_path + "/" + tnow)
                        self.wg.qlabel_check_icon_action.setPixmap(
                            QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_ok_16.png"))
                        self.wg.qlabel_action_comment.setText("Saved picture: " + tnow)
                        self.qlabel_folder.setEnabled(True)

            elif self.wg.qradio_raw.isChecked():
                result = QtWidgets.QMessageBox.question(self, "Save Picture...",
                            "Are you sure you want to save this picture?",
                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if result == QtWidgets.QMessageBox.Yes:
                    self.saved_path = str(QtWidgets.QFileDialog.getExistingDirectory(self, "Select a destination Directory"))
                    if os.path.exists(self.saved_path) and self.saved_path:
                        tnow = "TILE-%02d_ADC-RAW-DATA_SAVED_ON_" % self.current_tile
                        tnow += datetime.datetime.strftime(datetime.datetime.utcnow(), "%Y-%m-%d_%H%M%S.png")
                        self.logger.logger.info("Saving: " + self.saved_path + "/" + tnow)
                        self.rawPlots.savePicture(self.saved_path + "/" + tnow)
                        self.wg.qlabel_check_icon_action.setPixmap(
                            QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_ok_16.png"))
                        self.wg.qlabel_action_comment.setText("Saved picture: " + tnow)
                        self.qlabel_folder.setEnabled(True)

            elif self.wg.qradio_rms.isChecked():
                result = QtWidgets.QMessageBox.question(self, "Save Picture...",
                            "Are you sure you want to save this picture?",
                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if result == QtWidgets.QMessageBox.Yes:
                    self.saved_path = str(QtWidgets.QFileDialog.getExistingDirectory(self, "Select a destination Directory"))
                    if os.path.exists(self.saved_path) and self.saved_path:
                        tnow = "TILE-%02d_RMS_SAVED_ON_" % self.current_tile
                        tnow += datetime.datetime.strftime(datetime.datetime.utcnow(), "%Y-%m-%d_%H%M%S.png")
                        self.logger.logger.info("Saving: " + self.saved_path + "/" + tnow)
                        self.rmsPlots.savePicture(self.saved_path + "/" + tnow)
                        self.wg.qlabel_check_icon_action.setPixmap(
                            QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_ok_16.png"))
                        self.wg.qlabel_action_comment.setText("Saved picture: " + tnow)
                        self.qlabel_folder.setEnabled(True)

            elif self.wg.qradio_power.isChecked():
                result = QtWidgets.QMessageBox.question(self, "Save Picture...",
                            "Are you sure you want to save this picture?",
                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if result == QtWidgets.QMessageBox.Yes:
                    self.saved_path = str(QtWidgets.QFileDialog.getExistingDirectory(self, "Select a destination Directory"))
                    if os.path.exists(self.saved_path) and self.saved_path:
                        tnow = "TILE-%02d_POWER_SAVED_ON_" % self.current_tile
                        tnow += datetime.datetime.strftime(datetime.datetime.utcnow(), "%Y-%m-%d_%H%M%S.png")
                        self.logger.logger.info("Saving: " + self.saved_path + "/" + tnow)
                        self.powerPlots.savePicture(self.saved_path + "/" + tnow)
                        self.wg.qlabel_check_icon_action.setPixmap(
                            QtGui.QPixmap(os.getcwd() + "/Pictures/Icons/icon_ok_16.png"))
                        self.wg.qlabel_action_comment.setText("Saved picture: " + tnow)
                        self.qlabel_folder.setEnabled(True)


    def reformat_plots(self):
        try:
            new_input_list = []
            for i in self.wg.qline_channels.text().split(","):
                if "-" in i:
                    for a in range(int(i.split("-")[0]), int(i.split("-")[1]) + 1):
                        new_input_list += [a]
                else:
                    new_input_list += [int(i)]
            self.miniPlots.plotClear()
            self.spectrogramPlots.plotClear()
            self.powerPlots.plotClear()
            del self.miniPlots
            del self.spectrogramPlots
            del self.powerPlots
            del self.rawPlots
            del self.rmsPlots
            gc.collect()
            self.input_list = new_input_list
            self.miniPlots = MiniPlots(self.wg.qplot_spectra, len(self.input_list))
            self.spectrogramPlots = MiniPlots(parent=self.wg.qplot_spectrogram,
                                              nplot=len(self.input_list), xlabel="samples", ylabel="MHz",
                                              xlim=[0, 100], ylim=[0, 400])
            self.powerPlots = MiniPlots(parent=self.wg.qplot_power, nplot=len(self.input_list),
                                        xlabel="time samples", ylabel="dB", xlim=[0, 100], ylim=[-100, 0])
            self.rmsPlots = MiniPlots(parent=self.wg.qplot_rms, nplot=len(self.input_list),
                                        xlabel="time samples", ylabel="ADU RMS", xlim=[0, 100], ylim=[0, 50])
            self.rawPlots = MiniPlots(parent=self.wg.qplot_raw,
                                      nplot=len(self.input_list), xlabel="time samples", ylabel="ADU",
                                      xlim=[0, 32768], ylim=[-150, 150])

            self.channels_line = self.wg.qline_channels.text()
        except ValueError:
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText("Value Error: please check the Channels string syntax")
            msgBox.setWindowTitle("Error!")
            msgBox.exec_()

    def cb_show_spectra_grid(self, state):
        if state == QtCore.Qt.Checked:
            self.show_spectra_grid = True
            self.miniPlots.showGrid(show_grid=True)
        else:
            self.show_spectra_grid = False
            self.miniPlots.showGrid(show_grid=False)

    def cb_show_raw_grid(self, state):
        if state == QtCore.Qt.Checked:
            self.show_raw_grid = True
            self.rawPlots.showGrid(show_grid=True)
        else:
            self.show_raw_grid = False
            self.rawPlots.showGrid(show_grid=False)

    def cb_show_power_grid(self, state):
        if state == QtCore.Qt.Checked:
            self.show_power_grid = True
            self.powerPlots.showGrid(show_grid=True)
        else:
            self.show_power_grid = False
            self.powerPlots.showGrid(show_grid=False)

    def cb_show_rms_grid(self, state):
        if state == QtCore.Qt.Checked:
            self.show_rms_grid = True
            self.rmsPlots.showGrid(show_grid=True)
        else:
            self.show_rms_grid = False
            self.rmsPlots.showGrid(show_grid=False)

    def cb_show_xline(self, state):
        times = [0] #if self.wg.qradio_avg.isChecked() else range(self.nof_files)
        if state == QtCore.Qt.Checked:
            for k in times:
                self.miniPlots.hide_line("b", True)
            self.miniPlots.hide_annotation(["b"], self.wg.qcheck_rms.isChecked())
        else:
            for k in times:
                self.miniPlots.hide_line("b", False)
            self.miniPlots.hide_annotation(["b"], False)

    def cb_show_yline(self, state):
        times = [0] #if self.wg.qradio_avg.isChecked() else range(self.nof_files)
        if state == QtCore.Qt.Checked:
            for k in times:
                self.miniPlots.hide_line("g", True)
            self.miniPlots.hide_annotation(["g"], self.wg.qcheck_rms.isChecked())
        else:
            for k in times:
                self.miniPlots.hide_line("g", False)
            self.miniPlots.hide_annotation(["g"], False)

    def cb_show_rms(self, state):
        times = [0] #if self.wg.qradio_avg.isChecked() else range(len(self.lines))
        if state == QtCore.Qt.Checked:
            self.show_rms = True
            for k in times:
                self.miniPlots.hide_annotation(["b"], visu=self.wg.qcheck_xpol_sp.isChecked())
                self.miniPlots.hide_annotation(["g"], visu=self.wg.qcheck_ypol_sp.isChecked())
        else:
            self.show_rms = False
            for k in times:
                self.miniPlots.hide_annotation(["b", "g"], visu=False)

    def check_power(self, b):
        if b.isChecked():
            # Show only power plot
            self.wg.qplot_spectrogram.hide()
            self.wg.qplot_spectra.hide()
            self.wg.qplot_raw.hide()
            self.wg.qplot_rms.hide()
            self.wg.qplot_power.show()
            # Show only power ctrl
            self.wg.ctrl_spectrogram.hide()
            self.wg.ctrl_spectra.hide()
            self.wg.ctrl_raw.hide()
            self.wg.ctrl_rms.hide()
            self.wg.ctrl_power.show()

    def check_spectrogram(self, b):
        if b.isChecked():
            #self.wg.qcheck_rms.setEnabled(False)
            #self.wg.qcheck_grid.setEnabled(False)
            # Show only spectrogram plot
            self.wg.qplot_spectra.hide()
            self.wg.qplot_power.hide()
            self.wg.qplot_raw.hide()
            self.wg.qplot_rms.hide()
            self.wg.qplot_spectrogram.show()
            # Show only spectrogram ctrl
            self.wg.ctrl_spectrogram.show()
            self.wg.ctrl_spectra.hide()
            self.wg.ctrl_raw.hide()
            self.wg.ctrl_rms.hide()
            self.wg.ctrl_power.hide()

    def check_avg_spectra(self, b):
        if b.isChecked():
            # Show only spectra plot
            self.wg.qplot_power.hide()
            self.wg.qplot_spectrogram.hide()
            self.wg.qplot_raw.hide()
            self.wg.qplot_rms.hide()
            self.wg.qplot_spectra.show()
            # Show only spectra ctrl
            self.wg.ctrl_spectrogram.hide()
            self.wg.ctrl_power.hide()
            self.wg.ctrl_raw.hide()
            self.wg.ctrl_rms.hide()
            self.wg.ctrl_spectra.show()

    def check_raw(self, b):
        if b.isChecked():
            # Show only raw plot
            self.wg.qplot_power.hide()
            self.wg.qplot_spectrogram.hide()
            self.wg.qplot_spectra.hide()
            self.wg.qplot_rms.hide()
            self.wg.qplot_raw.show()
            # Show only raw ctrl
            self.wg.ctrl_spectrogram.hide()
            self.wg.ctrl_power.hide()
            self.wg.ctrl_spectra.hide()
            self.wg.ctrl_rms.hide()
            self.wg.ctrl_raw.show()

    def check_rms(self, b):
        if b.isChecked():
            # Show only rms plot
            self.wg.qplot_power.hide()
            self.wg.qplot_spectrogram.hide()
            self.wg.qplot_spectra.hide()
            self.wg.qplot_raw.hide()
            self.wg.qplot_rms.show()
            # Show only rms ctrl
            self.wg.ctrl_spectrogram.hide()
            self.wg.ctrl_power.hide()
            self.wg.ctrl_spectra.hide()
            self.wg.ctrl_raw.hide()
            self.wg.ctrl_rms.show()

    def check_tab_show(self, b, index):
        if b.isChecked():
            QtWidgets.QTabWidget.setTabVisible(self.wg.qtabMain, index, True)
        else:
            QtWidgets.QTabWidget.setTabVisible(self.wg.qtabMain, index, False)

    def applyEnable(self):
        # try:
        #     if self.xAxisRange[0] == float(self.wg.qline_band_from.text()) \
        #             and self.xAxisRange[1] == float(self.wg.qline_band_to.text()) \
        #             and self.yAxisRange[0] == float(self.wg.qline_level_min.text()) \
        #             and self.yAxisRange[1] == float(self.wg.qline_level_max.text()):
        # # self.wg.qbutton_apply.setEnabled(False)
        # # else:
        # # self.wg.qbutton_apply.setEnabled(True)
        # # pass
        # except ValueError:
            pass

    def applyPressed(self):
        #if not self.xAxisRange[0] == float(self.wg.qline_band_from.text()) \
        #        or not self.xAxisRange[1] == float(self.wg.qline_band_to.text()):
        self.xAxisRange = [float(self.wg.qline_band_from.text()), float(self.wg.qline_band_to.text())]
        self.miniPlots.set_x_limits(self.xAxisRange)
        # self.wg.qbutton_apply.setEnabled(False)

        #if not self.yAxisRange[0] == float(self.wg.qline_level_min.text())\
        #        or not self.yAxisRange[1] == float(self.wg.qline_level_max.text()):
        self.yAxisRange = [float(self.wg.qline_level_min.text()), float(self.wg.qline_level_max.text())]
        self.miniPlots.set_y_limits(self.yAxisRange)
        # self.wg.qbutton_apply.setEnabled(False)

    def cmdClose(self):
        self.stopThreads = True
        self.logger.logger.info("Stopping Threads")
        self.logger.stopLog()

    def closeEvent(self, event):
        result = QtWidgets.QMessageBox.question(self,
                                                "Confirm Exit...",
                                                "Are you sure you want to exit ?",
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        event.ignore()

        if result == QtWidgets.QMessageBox.Yes:
            event.accept()
            self.cmdClose()


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station_playback [options]")
    parser.add_option("--profile", action="store", dest="profile",
                      type="str", default="Default", help="Profile file")
    (opt, args) = parser.parse_args(argv[1:])

    app = QtWidgets.QApplication(sys.argv)
    window = Playback(profile=opt.profile, uiFile="Gui/skalab_playback.ui")
    window.resize(1160, 900)
    window.setWindowTitle("SKALAB Playback")

    sys.exit(app.exec_())
