import gc
import logging
import socket
import numpy as np
from pyaavs import station
from pyaavs.station import configuration
from skalab_base import SkalabBase
from monitor_utils import *
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QSize, QByteArray, QRectF, pyqtProperty
from PyQt5.QtWidgets import QWidget, QStyleOption
from PyQt5.QtGui import QPainter
from colorsys import rgb_to_hls, hls_to_rgb
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QWidget
from time import sleep
from pyfabil import TPMGeneric
from future.utils import iteritems
from pyfabil.base.definitions import LibraryError, BoardError



class TileInitialization(SkalabBase):
    """
    Class for initializing tiles in the monitoring application.

    Attributes:
    - signal_station_init (pyqtSignal): PyQt signal for station initialization.

    Methods:
    - __init__(self, profile, swpath=""): Constructor for the TileInitialization class.
    - populate_table_station(self): Populates the station table with configuration details.
    - loadEventStation(self): Loads the event station.

    Parameters:
    - profile: Profile information for initialization.
    - swpath (str): Path to the software.

    Attributes (in constructor):
    - station_connected (bool): Flag indicating whether the station is connected.
    - config_file (str): Configuration file path.
    - wg (Widget): Widget for handling UI components.
    - text_editor (str): Text editor for handling configuration file editing.
    - station_name (str): Name of the station.
    - nof_tiles (int): Number of tiles in the station.
    - nof_antennas (int): Number of antennas in the station.
    - bitfile (str): Bitfile information.
    - truncation (int): Channel truncation value.

    Widget Components:
    - wgProBox: Parent widget.
    - wg.qline_configfile: QLineEdit for displaying the configuration file path.
    - wg.initbar, wg.initbar1, wg.initbar2: ProgressBar widgets for initialization progress.
    - wg.qlabel_bitfile: QLabel for displaying bitfile information.

    Signals:
    - signal_station_init: PyQt signal emitted when the station is initialized.

    Example Usage:
    ```python
    profile_info = {...}  # Provide the profile information
    tile_init = TileInitialization(profile_info, "/path/to/software")
    tile_init.populate_table_station()
    tile_init.loadEventStation()
    ```

    Note: Ensure that the station's configuration file is set in the profile under 'Init'.
    """

    signal_station_init = QtCore.pyqtSignal()

    def __init__(self, profile, swpath="") -> None:
        """
        Constructor for the TileInitialization class.

        Parameters:
        - profile: Profile information for initialization.
        - swpath (str): Path to the software.

        Returns:
        None
        """
        super(TileInitialization, self).__init__(App="monitor", Profile=profile, Path=swpath, parent=self.wgProBox)
        self.station_connected = False
        self.config_file = self.profile['Init']['station_file']
        self.wg.qline_configfile.setText(self.config_file)
        if 'Extras' in self.profile.keys():
            if 'text_editor' in self.profile['Extras'].keys():
                self.text_editor = self.profile['Extras']['text_editor']
        self.wg.initbar.hide()
        self.wg.initbar1.hide()
        self.wg.initbar2.hide()

        if self.config_file:  
            station.load_configuration_file(self.config_file)
            self.station_name = station.configuration['station']['name']
            self.nof_tiles = len(station.configuration['tiles'])
            self.nof_antennas = int(station.configuration['station']['number_of_antennas'])
            self.bitfile = station.configuration['station']['bitfile']
            if len(self.bitfile) > 52:
                self.wg.qlabel_bitfile.setText("..." + self.bitfile[-52:])
            else:
                self.wg.qlabel_bitfile.setText(self.bitfile)
            self.truncation = int(station.configuration['station']['channel_truncation'])
            self.populate_table_station()
            self.loadEventStation()
            

    def loadEventStation(self):
        """
        Connects UI buttons to corresponding functions and signals.

        - qbutton_station_connect: Connects to the `station_connect` function.
        - qbutton_station_init and qbutton_station_init1: Connect to the `station_init` function.
        - qbutton_load_configuration: Connects to the `setup_config` function.
        - qbutton_browse: Connects to the `browse_config` function.
        - qbutton_edit: Connects to the `editClone` function for editing the configuration file.
        - qbutton_load (in wgProfile): Connects to the `reload_station` function.

        Returns:
        None
        """
        self.wg.qbutton_station_connect.clicked.connect(lambda: self.station_connect())
        self.wg.qbutton_station_init.clicked.connect(lambda: self.station_init())
        self.wg.qbutton_station_init1.clicked.connect(lambda: self.station_init())
        self.wg.qbutton_load_configuration.clicked.connect(lambda: self.setup_config())
        self.wg.qbutton_browse.clicked.connect(lambda: self.browse_config())
        self.wg.qbutton_edit.clicked.connect(lambda: editClone(self.wg.qline_configfile.text(), self.text_editor))
        self.wgProfile.qbutton_load.clicked.connect(lambda: self.reload_station())

    def reload_station(self):
        """
        Reloads the station configuration.

        - Updates the configuration file path.
        - Calls `setup_config` to reload the configuration.

        Returns:
        None
        """
        self.config_file = self.profile['Init']['station_file']
        self.wg.qline_configfile.setText(self.config_file)        
        self.setup_config()

    def browse_config(self):
        """
        Opens a file dialog to browse and select a station configuration file.

        - Updates the configuration file path.
        - Calls `setup_config` to reload the configuration.

        Returns:
        None
        """
        fd = QtWidgets.QFileDialog()
        fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        options = fd.options()
        self.config_file = fd.getOpenFileName(self, caption="Select a Station Config File...",
                                              directory="/opt/aavs/config/", options=options)[0]
        self.wg.qline_configfile.setText(self.config_file)

    def setup_config(self):
        """
        Sets up the station configuration.

        - Loads the station configuration from the selected file.
        - Updates configuration details in the UI.
        - Calls `populate_table_station` and `populateTileInstance` to update UI components.

        Returns:
        None
        """
        if not self.config_file == "":
            station.configuration = configuration.copy()
            station.load_configuration_file(self.config_file)
            self.wg.qline_configfile.setText(self.config_file)
            self.station_name = station.configuration['station']['name']
            self.nof_tiles = len(station.configuration['tiles'])
            self.nof_antennas = int(station.configuration['station']['number_of_antennas'])
            self.bitfile = station.configuration['station']['bitfile']
            self.wg.qlabel_bitfile.setText(self.bitfile)
            self.truncation = int(station.configuration['station']['channel_truncation'])
            self.populate_table_station()
            # if not self.wgPlay == None:
            #     self.wgPlay.wg.qcombo_tpm.clear()
            # if not self.wgLive == None:
            #     self.wgLive.wg.qcombo_tpm.clear()
            self.tiles = []
            for n, i in enumerate(station.configuration['tiles']):
                # if not self.wgPlay == None:
                #     self.wgPlay.wg.qcombo_tpm.addItem("TPM-%02d (%s)" % (n + 1, i))
                # if not self.wgLive == None:
                #     self.wgLive.wg.qcombo_tpm.addItem("TPM-%02d (%s)" % (n + 1, i))
                self.tiles += [i]
            self.populateTileInstance()
        else:
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText("SKALAB: Please SELECT a valid configuration file first...")
            msgBox.setWindowTitle("Error!")
            msgBox.exec_()


    def do_station_init(self):
        """
        Initiates the station setup process.

        - Updates progress bars (initbar, initbar1) to indicate progress.
        - Sets station configuration flags for initialization and programming.
        - Attempts to create a `Station` instance (`tpm_station`) using the loaded configuration.
        - Disables station initialization and connection buttons during the process.
        - Connects to the station.
        - Updates UI elements and LEDs based on the station connection status.
        - Handles exceptions and cleans up resources.
        - Enables station initialization and connection buttons after completion.

        Returns:
        None
        """
        self.wg.initbar.setValue(40)
        self.wg.initbar1.setValue(40)
        station.configuration['station']['initialise'] = True
        station.configuration['station']['program'] = True
        try:
            self.tpm_station = station.Station(station.configuration)
            self.wg.qbutton_station_init.setEnabled(False)
            self.wg.qbutton_station_init1.setEnabled(False)
            self.wg.qbutton_station_connect.setEnabled(False)
            self.wg.initbar.setValue(70)
            self.wg.initbar1.setValue(70)
            self.tpm_station.connect()
            self.wg.initbar.hide()
            self.wg.initbar1.hide()
            station.configuration['station']['initialise'] = False
            station.configuration['station']['program'] = False
            if self.tpm_station.properly_formed_station:
                self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(78, 154, 6);")
                self.wg.qbutton_station_init1.setStyleSheet("background-color: rgb(78, 154, 6);")
                self.wg.qbutton_station_connect.setStyleSheet("background-color: rgb(78, 154, 6);")
                self.station_connected = True
                for k in range(len(self.tpm_slot_ip)):
                    if self.tpm_slot_ip[k] in self.tpm_station.configuration['tiles'] and self.tpm_slot_ip[k] != '0' :
                        self.tpm_initialized[k] = True
                        self.tpm_station.configuration['tiles'].index(self.tpm_slot_ip[k])
                        self.tpm_active[k] = self.tpm_station.tiles[self.tpm_station.configuration['tiles'].index(self.tpm_slot_ip[k])]
                        for led in self.qled_tpm[k]:
                            led.Colour = Led.Green
                self.tpmStatusChanged()
                #Start threads
                ##self.wait_check_tpm.set()
                # # Switch On the PreADUs
                # for tile in self.tpm_station.tiles:
                #     tile["board.regfile.enable.fe"] = 1
                #     sleep(0.1)
                # sleep(1)
                # self.tpm_station.set_preadu_attenuation(0)
                # self.logger.info("TPM PreADUs Powered ON")
                if 'ethernet_pause_1gbe' in station.configuration['station']:
                    self.logger.info("Set ETH Pause")
                    self.tpm_station['board.regfile.ethernet_pause'] = station.configuration['station']['ethernet_pause_1gbe']
            else:
                self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(204, 0, 0);")
                self.wg.qbutton_station_init1.setStyleSheet("background-color: rgb(204, 0, 0);")
                self.wg.qbutton_station_connect.setStyleSheet("background-color: rgb(204, 0, 0);")
            self.wg.qbutton_station_init.setEnabled(True)
            self.wg.qbutton_station_init1.setEnabled(True)
            self.wg.qbutton_station_connect.setEnabled(True)
            self.station_connected = False
            del self.tpm_station
            gc.collect()
        except:
            self.wg.qbutton_station_init.setEnabled(True)
            self.wg.qbutton_station_init1.setEnabled(True)
            self.wg.qbutton_station_connect.setEnabled(True)
            self.station_connected = False
        self.tpm_station = None


    def station_init(self):
        """
        Initiates the station setup process based on the loaded configuration file.

        - Prompts the user to confirm the action.
        - Acquires the TPM lock to stop threads during initialization.
        - Loads the station configuration file.
        - Checks if TPMs forming the station are powered ON.
        - Compares TPM IPs from the config file with those powered ON in the subrack.
        - Displays warnings or errors for power-off or IP mismatches.
        - Creates TPM instances and retrieves TPM versions.
        - Initiates station setup (`do_station_init`) if all TPMs are reachable.
        - Handles errors and displays appropriate messages.
        - Releases the TPM lock to start threads after completion.

        Returns:
        None
        """
        result = QtWidgets.QMessageBox.question(self.wg.monitor_tab, "Confirm Action -IP",
                                            "Are you sure to Program and Init the Station?",
                                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if result == QtWidgets.QMessageBox.Yes:
            # Stop threads
            self._tpm_lock.acquire()
            if self.config_file:
                tpm_ip_from_subrack = []
                self.wg.initbar.show()
                self.wg.initbar1.show()
                
                # Create station
                station.load_configuration_file(self.config_file)
                # Check wether the TPM are ON or OFF
                station_on = True
                tpm_ip_list = list(station.configuration['tiles'])
                # TODO : self.client.get_attribute('tpm_ips')['value'] sometimes gives None 
                """  with self._subrack_lock:
                    self.tpm_status_info['tpm_ips'] = self.client.get_attribute('tpm_ips')['value'] # update tpm ip
                tpm_ip_from_subrack = self.tpm_status_info['tpm_ips'] """
                
                # workaround
                for i in range(8):
                    if self.tpm_status_info['tpm_on_off'][i]:
                        tpm_ip_from_subrack.append(self.tpm_status_info['assigned_tpm_ip_adds'][i])
                if not len(tpm_ip_list) == len(tpm_ip_from_subrack):
                    self.wg.initbar.hide()
                    self.wg.initbar1.hide()
                    msgBox = QtWidgets.QMessageBox()
                    message = "STATION\nOne or more TPMs forming the station are OFF\nPlease check the power!"
                    msgBox.setText(message)
                    msgBox.setWindowTitle("ERROR: TPM POWERED OFF")
                    msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                    details = "STATION IP LIST FROM CONFIG FILE (%d): " % len(tpm_ip_list)
                    for i in tpm_ip_list:
                        details += "\n%s" % i
                    details += "\n\nSUBRACK IP LIST OF TPM POWERED ON: (%d): " % len(tpm_ip_from_subrack)
                    for i in tpm_ip_from_subrack:
                        details += "\n%s" % i
                    msgBox.setDetailedText(details)
                    msgBox.exec_()
                    # Start threads
                    self._tpm_lock.release()
                    return
                else:
                    if not np.array_equal(tpm_ip_list, tpm_ip_from_subrack):
                        msgBox = QtWidgets.QMessageBox()
                        message = "STATION\nIPs provided by the Subrack are different from what defined in the " \
                                "config file.\nINIT will use the new assigned IPs."
                        msgBox.setText(message)
                        msgBox.setWindowTitle("WARNING: IP mismatch")
                        msgBox.setIcon(QtWidgets.QMessageBox.Warning)
                        details = "STATION IP LIST FROM CONFIG FILE (%d): " % len(tpm_ip_list)
                        for i in tpm_ip_list:
                            details += "\n%s" % i
                        details += "\n\nSUBRACK IP LIST OF TPM POWERED ON: (%d): " % len(tpm_ip_from_subrack)
                        for i in tpm_ip_from_subrack:
                            details += "\n%s" % i
                        msgBox.setDetailedText(details)
                        msgBox.exec_()
                        station.configuration['tiles'] = list(tpm_ip_from_subrack)
                        self.wgLive.setupNewTilesIPs(list(tpm_ip_from_subrack))
                for tpm_ip in station.configuration['tiles']:
                    try:
                        tpm = TPMGeneric()
                        tpm_version = tpm.get_tpm_version(socket.gethostbyname(tpm_ip), 10000)
                    except (BoardError, LibraryError):
                        station_on = False
                        # Start threads
                        self._tpm_lock.release()
                        break
                if station_on:
                    #self.signal_station_init.emit()
                    self.do_station_init()
                else:
                    msgBox = QtWidgets.QMessageBox()
                    msgBox.setText("STATION\nOne or more TPMs forming the station is unreachable\n"
                                "Please check the power or the connection!")
                    msgBox.setWindowTitle("ERROR: TPM UNREACHABLE")
                    msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                    details = "STATION IP LIST FROM CONFIG FILE (%d): " % len(tpm_ip_list)
                    for i in tpm_ip_list:
                        details += "\n%s" % i
                    details += "\n\nSUBRACK IP LIST OF TPM POWERED ON: (%d): " % len(tpm_ip_from_subrack)
                    for i in tpm_ip_from_subrack:
                        details += "\n%s" % i
                    msgBox.setDetailedText(details)
                    msgBox.exec_()
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("SKALAB: Please LOAD a configuration file first...")
                msgBox.setWindowTitle("Error!")
                msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                msgBox.exec_()
            # Start threads
            self._tpm_lock.release()

    def station_connect(self):
        """
        Initiates the connection to the station.

        - Shows the initialization progress bar (`initbar2`).
        - Checks if the station is not already connected.
        - Loads the station configuration from the profile.
        - Creates a station instance (`tpm_station`).
        - Connects to the station and sets the GUI elements accordingly.
        - Handles errors and displays appropriate messages.
        - Sets the station status to connected if successful.

        Returns:
        None
        """
        self.wg.initbar2.show()
        if not self.station_connected:
            # Load station configuration
            self.config_file = self.profile['Init']['station_file']
            station.load_configuration_file(self.config_file)
            self.wg.initbar2.setValue(20)
            self.station_configuration = station.configuration
            # if self.newTilesIPs is not None:
            #     station.configuration['tiles'] = self.newTilesIPs
            #     self.updateComboIps(self.newTilesIPs)
            try:
                # if True:
                # Create station
                self.wg.initbar2.setValue(40)
                self.tpm_station = station.Station(station.configuration)
                # Connect station (program, initialise and configure if required)
                self.tpm_station.connect()
                self.wg.initbar2.setValue(60)
                self.preadu = []
                status = True
                for t in self.tpm_station.tiles:
                    status = status * t.is_programmed()
                    #self.preadu += [Preadu(tpm=t, preadu_version=self.preadu_version)]
                #self.wpreadu.setConfiguration(conf=self.preadu[self.wg.qcombo_tpm.currentIndex()].readConfiguration())
                if status:
                    #self.wg.qlabel_connection.setText("Connected")
                    self.wg.qbutton_station_connect.setStyleSheet("background-color: rgb(78, 154, 6);")
                    self.wg.qbutton_station_connect.setText("ONLINE")
                    self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(78, 154, 6);")
                    self.wg.qbutton_station_init1.setStyleSheet("background-color: rgb(78, 154, 6);")
                    if self.tpm_station.tiles[0].tpm_version() == "tpm_v1_2":
                        self.rms_remap = [1, 0, 3, 2, 5, 4, 7, 6,
                                          8, 9, 10, 11, 12, 13, 14, 15,
                                          17, 16, 19, 18, 21, 20, 23, 22,
                                          24, 25, 26, 27, 28, 29, 30, 31]
                    else:
                        # This must be verified when PYAAVS will be adapted to TPM1.6
                        # self.rms_remap = [0, 1, 2, 3, 4, 5, 6, 7,
                        #                   9, 8, 11, 10, 13, 12, 15, 14,
                        #                   16, 17, 18, 19, 20, 21, 22, 23,
                        #                   25, 24, 27, 26, 29, 28, 31, 30]
                        self.rms_remap = np.arange(32)
                    self.station_connected = True
                    self.wg.initbar2.setValue(80)
                    for k in range(len(self.tpm_slot_ip)):
                        if self.tpm_slot_ip[k] in self.tpm_station.configuration['tiles'] and self.tpm_slot_ip[k] != '0' :
                            self.tpm_initialized[k] = True
                            self.tpm_station.configuration['tiles'].index(self.tpm_slot_ip[k])
                            self.tpm_active[k] = self.tpm_station.tiles[self.tpm_station.configuration['tiles'].index(self.tpm_slot_ip[k])]
                            for led in self.qled_tpm[k]:
                                led.Colour = Led.Green
                    self.tpmStatusChanged()

                    #self.setupDAQ()
                    # self.preadu.setTpm(self.tpm_station.tiles[self.wg.qcombo_tpm.currentIndex()])
                else:
                    self.wg.initbar2.hide()
                    msgBox = QtWidgets.QMessageBox()
                    msgBox.setText("Some TPM is not programmed,\nplease initialize the Station first!")
                    msgBox.setWindowTitle("Error!")
                    msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                    msgBox.exec_()
            #else:
            except Exception as e:
                self.wg.initbar2.hide()
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("An exception occurred while trying to connect to the Station.\n\nException: " + str(e))
                msgBox.setWindowTitle("Error!")
                msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                msgBox.exec_()
                #self.wg.qlabel_connection.setText("ERROR: Unable to connect to the TPMs Station. Retry...")
                self.wg.qbutton_station_connect.setStyleSheet("background-color: rgb(204, 0, 0);")
                self.wg.qbutton_station_connect.setText("OFFLINE")
                self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(204, 0, 0);")
                self.wg.qbutton_station_init1.setStyleSheet("background-color: rgb(204, 0, 0);")
                self.station_connected = False
        else:
            self.station_disconnect()
        self.wg.initbar2.hide()

    def station_disconnect(self):
        """
        Disconnects the station.

        - Delays for 0.5 seconds.
        - Sets the value of `initbar2` progress bar to 40.
        - Deletes the `tpm_station` and associated `preadu` instances.
        - Clears and resets GUI elements to indicate offline status.
        - Updates status flags and resets initialization progress.
        - Updates the TPM status to disconnected.

        Returns:
        None
        """
        sleep(0.5)
        self.wg.initbar2.setValue(40)
        del self.tpm_station
        for p in self.preadu:
            del p
        gc.collect()
        self.preadu = []
        # if self.monitor_daq is not None:
        #     self.closeDAQ()
        self.tpm_station = None
        self.wg.qbutton_station_connect.setStyleSheet("background-color: rgb(204, 0, 0);")
        self.wg.qbutton_station_connect.setText("OFFLINE")
        self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(204, 0, 0);")
        self.wg.qbutton_station_init1.setStyleSheet("background-color: rgb(204, 0, 0);")
        self.station_connected = False
        self.initMonitor = True
        self.wg.initbar2.setValue(80)
        for k in range(len(self.tpm_slot_ip)):
            self.tpm_initialized[k] = False
            self.tpm_active[k] = None
        self.tpmStatusChanged()
    
    def apply_config_file(self,input_dict, output_dict):
        """
        Recursively applies configuration settings from `input_dict` to `output_dict`.

        - Copies values from `input_dict` to `output_dict` recursively.
        - Skips items not present in `output_dict` with a warning.
        
        Args:
        - input_dict (dict): Input configuration dictionary.
        - output_dict (dict): Output configuration dictionary to be updated.

        Returns:
        None
        """ 
        for k, v in iteritems(input_dict):
            if type(v) is dict:
                self.apply_config_file(v, output_dict[k])
            elif k not in list(output_dict.keys()):
                logging.warning("{} not a valid configuration item. Skipping".format(k))
            else:
                output_dict[k] = v

    def populate_table_station(self):
        """
        Populates three tables in the GUI with station configuration details.

        1. Station Configuration Table: Displays general station configuration settings.
        2. TPM Configuration Table: Displays TPM-specific details such as IP addresses and delays.
        3. Network Configuration Table: Displays network-related configuration settings.

        - Clears existing table spans.
        - Sets up the Station Configuration Table with headers and data.
        - Sets up the TPM Configuration Table with headers and data.
        - Sets up the Network Configuration Table with headers and data.
        
        Returns:
        None
        """
        # TABLE STATION
        self.wg.qtable_station.clearSpans()
        #self.wg.qtable_station.setGeometry(QtCore.QRect(20, 140, 171, 31))
        self.wg.qtable_station.setObjectName("conf_qtable_station")
        self.wg.qtable_station.setColumnCount(1)
        self.wg.qtable_station.setRowCount(len(station.configuration['station'].keys()) - 1)
        n = 0
        for i in station.configuration['station'].keys():
            if not i == "bitfile":
                self.wg.qtable_station.setVerticalHeaderItem(n, QtWidgets.QTableWidgetItem(i.upper()))
                n = n + 1

        item = QtWidgets.QTableWidgetItem()
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        item.setText("SECTION: STATION")
        self.wg.qtable_station.setHorizontalHeaderItem(0, item)
        __sortingEnabled = self.wg.qtable_station.isSortingEnabled()
        self.wg.qtable_station.setSortingEnabled(False)
        n = 0
        for i in station.configuration['station'].keys():
            if not i == "bitfile":
                item = QtWidgets.QTableWidgetItem(str(station.configuration['station'][i]))
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.wg.qtable_station.setItem(n, 0, item)
                n = n + 1
        self.wg.qtable_station.horizontalHeader().setStretchLastSection(True)
        self.wg.qtable_station.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_station.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_station.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)

        # TABLE TPM
        self.wg.qtable_tpm.clearSpans()
        #self.wg.qtable_tpm.setGeometry(QtCore.QRect(20, 180, 511, 141))
        self.wg.qtable_tpm.setObjectName("conf_qtable_tpm")
        self.wg.qtable_tpm.setColumnCount(2)
        self.wg.qtable_tpm.setRowCount(len(station.configuration['tiles']))
        for i in range(len(station.configuration['tiles'])):
            self.wg.qtable_tpm.setVerticalHeaderItem(i, QtWidgets.QTableWidgetItem("TPM-%02d" % (i + 1)))
        item = QtWidgets.QTableWidgetItem("IP ADDR")
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        self.wg.qtable_tpm.setHorizontalHeaderItem(0, item)
        item = QtWidgets.QTableWidgetItem("DELAYS")
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        self.wg.qtable_tpm.setHorizontalHeaderItem(1, item)
        for n, i in enumerate(station.configuration['tiles']):
            item = QtWidgets.QTableWidgetItem(str(i))
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.wg.qtable_tpm.setItem(n, 0, item)
        for n, i in enumerate(station.configuration['time_delays']):
            item = QtWidgets.QTableWidgetItem(str(i))
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.wg.qtable_tpm.setItem(n, 1, item)
        self.wg.qtable_tpm.horizontalHeader().setStretchLastSection(True)
        self.wg.qtable_tpm.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_tpm.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_tpm.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)

        # TABLE NETWORK
        self.wg.qtable_network.clearSpans()
        #self.wg.qtable_network.setGeometry(QtCore.QRect(600, 230, 511, 481))
        self.wg.qtable_network.setObjectName("conf_qtable_network")
        self.wg.qtable_network.setColumnCount(1)

        total_rows = len(station.configuration['network'].keys()) + 1
        for i in station.configuration['network'].keys():
            if type(station.configuration['network'][i]) is dict:
                total_rows = total_rows + len(station.configuration['network'][i])
            else:
                total_rows = total_rows + 1
        self.wg.qtable_network.setRowCount(total_rows)
        item = QtWidgets.QTableWidgetItem("SECTION: NETWORK")
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        item.setFlags(QtCore.Qt.ItemIsEnabled)
        self.wg.qtable_network.setHorizontalHeaderItem(0, item)
        n = 0
        for i in station.configuration['network'].keys():
            if n:
                item = QtWidgets.QTableWidgetItem(" ")
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.wg.qtable_network.setVerticalHeaderItem(n, item)
                item = QtWidgets.QTableWidgetItem(" ")
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.wg.qtable_network.setItem(n, 0, item)
                n = n + 1
            item = QtWidgets.QTableWidgetItem(str(i).upper())
            item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            font = QtGui.QFont()
            font.setBold(True)
            font.setWeight(75)
            item.setFont(font)
            self.wg.qtable_network.setVerticalHeaderItem(n, item)
            item = QtWidgets.QTableWidgetItem(" ")
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.wg.qtable_network.setItem(n, 0, item)
            n = n + 1
            if type(station.configuration['network'][i]) is dict:
                for k in sorted(station.configuration['network'][i].keys()):
                    self.wg.qtable_network.setVerticalHeaderItem(n, QtWidgets.QTableWidgetItem(str(k).upper()))
                    if "MAC" in str(k).upper() and not str(station.configuration['network'][i][k]) == "None":
                        item = QtWidgets.QTableWidgetItem(hex(station.configuration['network'][i][k]).upper())
                    else:
                        item = QtWidgets.QTableWidgetItem(str(station.configuration['network'][i][k]))
                    item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                    item.setFlags(QtCore.Qt.ItemIsEnabled)
                    self.wg.qtable_network.setItem(n, 0, item)
                    n = n + 1
            else:
                if station.configuration['network'][i] is None:
                    item = QtWidgets.QTableWidgetItem("None")
                else:
                    item = QtWidgets.QTableWidgetItem(station.configuration['network'][i])
                item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.wg.qtable_network.setItem(n-1, 0, item)
        self.wg.qtable_network.horizontalHeader().setStretchLastSection(True)
        self.wg.qtable_network.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_network.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_network.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)


