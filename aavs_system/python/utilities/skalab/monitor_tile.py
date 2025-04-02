import numpy as np
import logging
import yaml
import datetime
import copy

from pyaavs import station
from PyQt5 import QtWidgets, uic, QtCore
from PyQt5.QtGui import QColor
from monitor_station_init import *
from skalab_log import SkalabLog
from skalab_utils import colors,h5py
from threading import Thread, Event, Lock
from time import sleep, time
from pathlib import Path

def populateSlots(grid):
    """
    Populate slots with QButtons for TPM.

    Parameters:
    - grid (QtWidgets.QGridLayout): The grid layout to which buttons are added.

    Returns:
    List[QtWidgets.QPushButton]: A list of QButtons for TPM.
    """
    qbutton_tpm = []
    for i in range(8):
        qbutton_tpm.append(QtWidgets.QPushButton("TPM #%d" % (i + 1)))
        grid.addWidget(qbutton_tpm[i],int(i/4), int(i/4)*(-4)+i)
        qbutton_tpm[i].setGeometry(QtCore.QRect(10, 80 + (66 * (i)), 80, 30))
        qbutton_tpm[i].setObjectName("qbutton_tpm_%d" % i)
        qbutton_tpm[i].setEnabled(False)
    return qbutton_tpm

def populateTpmTable(frame, table, alarm):
    """
    Populate TPM tables in the UI.

    Parameters:
    - frame: The frame containing the UI elements.
    - table (List[Dict[str, str]]): List of dictionaries containing table names and address attributes.
    - alarm: Alarm data.

    Returns:
    Tuple[List[List[QtWidgets.QTableWidget]], List[QtWidgets.QTableWidget]]: 
    A tuple containing a list of QTableWidgets for TPM data and a list of QTableWidgets for voltage data.
    """
    qtable_tpm = [None] * 8 
    voltage_table = []
    for i in range(8): #Select TPM
        qtable_tpm[i] = []
        for j in range(len(table)): #Select table number
            for k,v in table[j].items(): #Get table name and address attribute
                splitting = None
                if k == 'voltage':
                    voltage_table.append(getattr(frame, f"{k}_tab2_{i+1}"))
                    voltage_table[-1].setColumnCount(2)
                    voltage_table[-1].setHorizontalHeaderLabels(("Value", "Warn/Alrm"))
                qtable_tpm[i].append(getattr(frame, f"{k}_tab_{i+1}"))
                qtable_tpm[i][-1].verticalHeader().setVisible(True)
                qtable_tpm[i][-1].setColumnCount(2)
                qtable_tpm[i][-1].setHorizontalHeaderLabels(("Value", "Warn/Alrm"))
                # Use eval to access the value in the dictionary
                if isinstance(v,list):
                    result = []
                    for attribute in v:
                        if isinstance(eval("alarm" + attribute),bool):
                            a = attribute[2:-2].replace('"]["',',').split(',')
                            result.append(a[-1])
                        else:
                            result.extend(list(eval("alarm" + attribute)))
                elif not(isinstance(eval("alarm" + v),tuple)) and not(isinstance(eval("alarm" + v),bool)) :
                    result = list(eval("alarm" + v))
                else:
                    a = v.replace('][','],[').split(',')
                    result = eval(a[-1])
                    qtable_tpm[i][-1].setRowCount(len(result))
                    qtable_tpm[i][-1].setVerticalHeaderLabels(result)
                    qtable_tpm[i][-1].horizontalHeader().setFixedHeight(20)
                    qtable_tpm[i][-1].resizeRowsToContents()
                    break 
                if k == 'voltage':
                    splitting = int(len(result)/2)
                    voltage_table[-1].setRowCount(len(result[splitting:]))
                    voltage_table[-1].setVerticalHeaderLabels(result[splitting:])
                    voltage_table[-1].horizontalHeader().setFixedHeight(20)
                    voltage_table[-1].resizeRowsToContents()
                qtable_tpm[i][-1].setRowCount(len(result[0:splitting]))
                qtable_tpm[i][-1].setVerticalHeaderLabels(result[0:splitting])
                qtable_tpm[i][-1].horizontalHeader().setFixedHeight(20)
                if not(j in {4,5,6}):
                    qtable_tpm[i][-1].resizeRowsToContents()                
    return qtable_tpm,voltage_table


class MonitorTPM(TileInitialization):
    """
    Monitor TPM class for handling TPM telemetry.

    Attributes:
    - signal_update_tpm_attribute (QtCore.pyqtSignal): Signal for updating TPM attributes.

    Parameters:
    - config (str): Configuration information.
    - uiFile (str): Path to the UI file.
    - profile (str): Profile information.
    - size (list): Size information.
    - swpath (str): Software path.

    Methods:
    - __init__(self, config="", uiFile="", profile="", size=[], swpath=""): Initialize the main window.
    - populate_table_profile(self): Populate the table based on the profile.
    - set_tpm_threshold(self, warning_factor): Set TPM threshold based on the warning factor.
    - populate_tpm_led(self, monitoring_points): Populate TPM LEDs based on monitoring points.
    - setup_tpm_hdf5(self): Set up HDF5 for TPM monitoring.
    - monitoring_tpm(self): Thread function for monitoring TPM.
    """

    signal_update_tpm_attribute = QtCore.pyqtSignal(dict,int)
   
    def __init__(self, config="", uiFile="", profile="", size=[], swpath=""):
        """
        Initialize the main window.

        Parameters:
        - config (str): Configuration information.
        - uiFile (str): Path to the UI file.
        - profile (str): Profile information.
        - size (list): Size information.
        - swpath (str): Software path.
        """
        # Load window file
        self.wg = uic.loadUi(uiFile)
        
        self.wgProBox = QtWidgets.QWidget(self.wg.qtab_conf)
        self.wgProBox.setGeometry(QtCore.QRect(1, 1, 800, 860))
        self.wgProBox.setVisible(True)
        self.wgProBox.show()
        super(MonitorTPM, self).__init__(profile, swpath)
        self.logger = SkalabLog(parent=self.wg.qt_log, logname=__name__, profile=self.profile)
        self.setCentralWidget(self.wg)
        self.loadEventsMonitor()
        # Set variable
        self.tpm_table_address = []       
        self.tpm_alarm_thresholds = {}
        self.tpm_interval = self.profile['Monitor']['tpm_query_interval']
        self.tile_custom_thresholds_file = self.profile['Tpm']['tpm_thresholds_file']
        self.counter_time = eval(self.profile['Tpm']['counter_time'])
        self.tpm_table_address = tpm_tables_address
        self.tlm_hdf_tpm_monitor = []
        self.tpm_initialized = [False] * 8
        self.tpm_table = []
        self.fixed_attr = ['temperatures','voltages','currents']
        self.counter_list = ['["timing"]["timestamp"]',\
                             '["io"]["ddr_interface"]["rd_cnt"]','["io"]["ddr_interface"]["wr_cnt"]','["io"]["ddr_interface"]["rd_dat_cnt"]']
        # create tpm_alarm_shadow and flags: alarm thresholds for tpm counters
        #this is the actual paramenter used by the program to execute the check value/threshold.
        #it is necessary since, when the clear button is pushed, the actual counters values are stored here. 
        # if a new thresholds table is loaded, this shodow paraemters is overwritten.
        self.first_measure = [True] * 8 
        self.countertime_flag = [False] * 8
        self.counter_previous_time = [time()] * 8
        # Populate table
        self.populate_table_profile()
        self.qbutton_tpm = populateSlots(self.wg.grid_tpm)
        self.text_editor = ""
        if 'Extras' in self.profile.keys():
            if 'text_editor' in self.profile['Extras'].keys():
                self.text_editor = self.profile['Extras']['text_editor']
        self.tpm_warning_factor = eval(self.profile['Warning Factor']['tpm_warning_parameter'])
        self.show()
        try:
            self.wg.qline_tpm_threshold.setText(self.tile_custom_thresholds_file)
            self.setTpmThreshold(self.tpm_warning_factor)

        except Exception as e:
            self.wg.qline_tpm_threshold.setText("tpm_monitoring_min_max.yaml")
            self.logger.warning(f"Tile custom threshold file not loaded: {e}")
            self.logger.warning(f"Default threshold file:{self.wg.qline_tpm_threshold.text()} loaded.")
            self.setTpmThreshold(self.tpm_warning_factor)

        self.tpm_table,self.voltage_table_bis = populateTpmTable(self.wg,self.tpm_table_address, self.MIN_MAX_MONITORING_POINTS)
        self.tpm_alarm_summary = self.wg.tpm_summary
        self.tpm_alarm_summary.setColumnCount(2)
        self.tpm_alarm_summary.setColumnWidth(0, 550)
        header = self.tpm_alarm_summary.horizontalHeader()
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.tpm_alarm_summary.setHorizontalHeaderLabels(['TPMs Alarms Summary','Value'])
        self.populateTpmLed(self.MIN_MAX_MONITORING_POINTS)
        self.tlm_hdf_tpm_monitor = self.setupTpmHdf5()
        # Start thread
        self.check_tpm_tm = Thread(name= "TPM telemetry", target=self.monitoringTpm, daemon=True)
        self._tpm_lock = Lock()
        self._tpm_lock_GUI = Lock()
        self.wait_check_tpm = Event()
        self.check_tpm_tm.start()

    def evaluateYamlFile(self,filename):
        """
        Evaluate the YAML file and initialize TPM monitoring points and alarm thresholds.

        Parameters:
        - filename (str): Path to the YAML file.

        Reads the YAML file, extracts TPM monitoring points, and initializes alarm thresholds.
        """
        with open(filename) as file:
            self.MIN_MAX_MONITORING_POINTS = (yaml.load(file, Loader=yaml.Loader)["tpm_monitoring_points"] or {})
        self.tpm_alarm_thresholds = copy.deepcopy(self.MIN_MAX_MONITORING_POINTS )    
        for a in self.fixed_attr:
            for key, value in self.MIN_MAX_MONITORING_POINTS[a].items():
                self.tpm_alarm_thresholds[a][key] = [value['min'], value['max']]

                
    def setTpmThreshold(self, warning_factor):
        """
        Set TPM thresholds based on the specified warning factor.

        Parameters:
        - warning_factor (float): Warning factor for adjusting thresholds.

        Evaluates the YAML file, adjusts the thresholds based on the warning factor, and updates the shadow parameters.
        """
        self.tpm_alarm_shadow = list()
        self.tpm_warning_shadow = list()
        self.evaluateYamlFile(self.wg.qline_tpm_threshold.text())
        self.tpm_warning_thresholds = copy.deepcopy(self.tpm_alarm_thresholds)
        self.tpm_alarm_shadow = [copy.deepcopy(self.tpm_alarm_thresholds) for i in range(8)]
        for i in self.fixed_attr:
            keys = list(self.tpm_alarm_thresholds[i].keys())
            for j in keys:
                try:
                    al_max = self.tpm_alarm_thresholds[i][j][1]
                    al_min = self.tpm_alarm_thresholds[i][j][0]
                    factor = (al_max - al_min) * (warning_factor)
                    self.tpm_warning_thresholds[i][j][0] = round(al_min + factor,2)
                    self.tpm_warning_thresholds[i][j][1] = round(al_max - factor,2)
                except:
                    pass
        self.tpm_warning_shadow = [copy.deepcopy(self.tpm_warning_thresholds) for i in range(8)]
        writeThresholds(self.wg.ala_text_2, self.wg.war_text_2, self.MIN_MAX_MONITORING_POINTS, self.tpm_warning_thresholds)


    def loadTpmThreshold(self):
        """
        Load TPM alarm thresholds from a YAML file.

        Opens a file dialog to select a YAML file containing TPM alarm thresholds.
        """
        fd = QtWidgets.QFileDialog()
        fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        filter = "YAML file(*.yaml *.yml)"
        options = fd.options()
        self.tpm_filename = fd.getOpenFileName(self, caption="Select a Tpm Alarm Thresholds file...",
                                              directory="./", options=options,filter=filter)[0]
        self.processTileThreshold(self.tpm_filename)
        

    def processTileThreshold(self,tpm_filename): 
        """
        Process TPM threshold file and update thresholds.

        Parameters:
        - tpm_filename (str): Path to the TPM threshold file.

        If the file path is not empty, it processes the TPM threshold file, updates the thresholds, and sets the GUI elements accordingly.
        """
        fi = QtCore.QFileInfo(tpm_filename)
        if not(tpm_filename == ''):
            with self._tpm_lock_GUI:
                self.first_measure = [True for i in range(8)]
                self.setTpmThreshold(self.tpm_warning_factor)
                self.wg.qline_tpm_threshold.setText(fi.fileName())
        return


    def populateTpmLed(self,attribute_names):
        """
        Populate TPM LED indicators in the GUI.

        Parameters:
        - attribute_names (list): List of attribute names.

        Creates LED indicators for TPM attributes in the GUI based on the provided attribute names.
        """
        self.qled_tpm = [None] * 8 
        for i in range(8):
            self.qled_tpm[i] = []
            for j in range(len(attribute_names)):
                self.qled_tpm[i].append(Led(self.wg.table_alarms))
                self.wg.led_layout.addWidget(self.qled_tpm[i][-1],j,i,QtCore.Qt.AlignCenter)


    def loadEventsMonitor(self):
        """
        Connect GUI elements to corresponding event handlers.

        Connects buttons in the GUI to their respective event handling functions.
        """
        self.wg.qbutton_tpm_edit.clicked.connect(lambda: editClone(self.wg.qline_tpm_threshold.text(), self.text_editor))
        self.wg.qbutton_tpm_threshold.clicked.connect(lambda: self.loadTpmThreshold())
        self.wg.qbutton_clear_tpm.clicked.connect(lambda: self.clearTpmValues())
    

    def clearTpmValues(self):
        """
        Clear TPM values in the GUI.

        Clears TPM values, LED indicators, and tables in the GUI for all TPM instances.
        """
        with (self._tpm_lock_GUI):
            self.tpm_alarm_summary.setRowCount(0)
            for i in range(8):
                self.first_measure[i] = True
                for led in self.qled_tpm[i]:
                    if self.tpm_on_off[i] and self.tpm_active[i]:
                        led.Colour = Led.Green
                    else:
                        led.Colour = Led.Grey
                    led.m_value = False
                for table in self.tpm_table[i]:
                    table.clearContents()
                self.voltage_table_bis[i].clearContents()
            try:
                for index in range(8):
                    self.tpm_active[index].tpm_10g_core[0].reset_errors()
                    self.tpm_active[index].tpm_10g_core[1].reset_errors()
            except:
                self.logger.warning("clearTpmValues failed")
                         

    def populateTileInstance(self):
        """
        Populate information about TPM instances in the GUI.

        Compares the assigned TPM IP addresses with the configured IPs in the station configuration and updates the GUI accordingly.
        """
        if (self.connected and self.tpm_assigned_tpm_ip_adds):
            # Comparing ip to assign slot number to ip: file .json and .yaml
            self.tpm_slot_ip = self.tpm_assigned_tpm_ip_adds
            self.tpm_ip_check= station.configuration['tiles']
            for j in self.tpm_ip_check:
                if j in self.tpm_slot_ip:
                    pass
                else:
                    self.logger.warning(f"ATTENTION: TMP IP: {j} in {self.config_file} is not detected by the Subrack.")


    def setShadowThresholds(self,index, data):
        """
        Set shadow thresholds for TPM alarms, timing, IO, and DSP attributes.

        Parameters:
        - index (int): Index of the TPM.
        - data (dict): Dictionary containing TPM attribute data.

        Sets the shadow thresholds for TPM alarms, timing, IO, and DSP attributes based on the provided data and index.
        """
        self.tpm_alarm_shadow[index]["alarms"] = data["alarms"]
        self.tpm_alarm_shadow[index]["timing"]["clock_managers"] = data["timing"]["clock_managers"]
        self.tpm_alarm_shadow[index]["io"]["jesd_interface"]["lane_error_count"] = data["io"]["jesd_interface"]["lane_error_count"]
        self.tpm_alarm_shadow[index]["io"]["jesd_interface"]["resync_count"] = data["io"]["jesd_interface"]["resync_count"]
        self.tpm_alarm_shadow[index]["io"]["f2f_interface"] = data["io"]["f2f_interface"]
        # self.tpm_alarm_shadow[index]["io"]["udp_interface"]["crc_error_count"] = data["io"]["udp_interface"]["crc_error_count"]
        # self.tpm_alarm_shadow[index]["io"]["udp_interface"]["linkup_loss_count"] = data["io"]["udp_interface"]["linkup_loss_count"]
        # self.tpm_alarm_shadow[index]["io"]["udp_interface"]["bip_error_count"] = data["io"]["udp_interface"]["bip_error_count"]
        # self.tpm_alarm_shadow[index]["io"]["udp_interface"]["decode_error_count"] = data["io"]["udp_interface"]["decode_error_count"]
        self.tpm_alarm_shadow[index]["io"]["ddr_interface"]["reset_counter"] = data["io"]["ddr_interface"]["reset_counter"]
        self.tpm_alarm_shadow[index]["dsp"]["station_beamf"]["ddr_parity_error_count"] = data["dsp"]["station_beamf"]["ddr_parity_error_count"]
        self.tpm_warning_shadow[index]["alarms"] = data["alarms"]
        self.tpm_warning_shadow[index]["timing"]["clock_managers"] = data["timing"]["clock_managers"]
        self.tpm_warning_shadow[index]["io"]["jesd_interface"]["lane_error_count"] = data["io"]["jesd_interface"]["lane_error_count"]
        self.tpm_warning_shadow[index]["io"]["jesd_interface"]["resync_count"] = data["io"]["jesd_interface"]["resync_count"]
        self.tpm_warning_shadow[index]["io"]["f2f_interface"] = data["io"]["f2f_interface"]
        # self.tpm_warning_shadow[index]["io"]["udp_interface"]["crc_error_count"] = data["io"]["udp_interface"]["crc_error_count"]
        # self.tpm_warning_shadow[index]["io"]["udp_interface"]["linkup_loss_count"] = data["io"]["udp_interface"]["linkup_loss_count"]
        # self.tpm_warning_shadow[index]["io"]["udp_interface"]["bip_error_count"] = data["io"]["udp_interface"]["bip_error_count"]
        # self.tpm_warning_shadow[index]["io"]["udp_interface"]["decode_error_count"] = data["io"]["udp_interface"]["decode_error_count"]
        self.tpm_warning_shadow[index]["io"]["ddr_interface"]["reset_counter"] = data["io"]["ddr_interface"]["reset_counter"]
        self.tpm_warning_shadow[index]["dsp"]["station_beamf"]["ddr_parity_error_count"] = data["dsp"]["station_beamf"]["ddr_parity_error_count"]
        self.setCounterThresholds(index, data, None)


    def setCounterThresholds(self,index, data, kwords):
        """
        Set thresholds for TPM counters.

        Parameters:
        - index (int): Index of the TPM.
        - data (dict): Dictionary containing TPM counter data.
        - kwords (str, optional): Counter keyword for selective threshold setting.

        Sets thresholds for TPM counters based on the provided data, index, and optional keyword.
        """
        if kwords == '["timing"]["timestamp"]' or not(kwords):
            self.tpm_alarm_shadow[index]["timing"]["timestamp"] = data["timing"]["timestamp"]
            self.tpm_warning_shadow[index]["timing"]["timestamp"] = data["timing"]["timestamp"]

        if kwords == '["io"]["ddr_interface"]["rd_cnt"]' or not(kwords):
            self.tpm_alarm_shadow[index]["io"]["ddr_interface"]["rd_cnt"] = data["io"]["ddr_interface"]["rd_cnt"]
            self.tpm_warning_shadow[index]["io"]["ddr_interface"]["rd_cnt"] = data["io"]["ddr_interface"]["rd_cnt"]

        if kwords == '["io"]["ddr_interface"]["wr_cnt"]' or not(kwords):
            self.tpm_alarm_shadow[index]["io"]["ddr_interface"]["wr_cnt"] = data["io"]["ddr_interface"]["wr_cnt"]
            self.tpm_warning_shadow[index]["io"]["ddr_interface"]["wr_cnt"] = data["io"]["ddr_interface"]["wr_cnt"]
        
        if kwords == '["io"]["ddr_interface"]["rd_dat_cnt"]' or not(kwords):
            self.tpm_alarm_shadow[index]["io"]["ddr_interface"]["rd_dat_cnt"] = data["io"]["ddr_interface"]["rd_dat_cnt"]
            self.tpm_warning_shadow[index]["io"]["ddr_interface"]["rd_dat_cnt"] = data["io"]["ddr_interface"]["rd_dat_cnt"]
        return
    

    def tpmStatusChanged(self):
        """
        Update TPM status and signal for further processing.

        Clears the wait flag, checks TPM status, and sets relevant variables.
        Enables the "Save Data" button if any TPM is initialized and signals for further processing.
        """
        self.wait_check_tpm.clear()
        for k in range(8):
            if not(self.tpm_on_off[k]) and self.tpm_active[k]:
                self.tpm_active[k] = None
        if any(self.tpm_initialized):
            self.wg.check_tpm_savedata.setEnabled(True)
            self.wait_check_tpm.set()


    def monitoringTpm(self):
        """
        Continuous monitoring of TPMs.

        Monitors TPM health status continuously and updates GUI components based on the status.
        Saves TPM data if the corresponding checkbox is checked.
        """
        while True:
            self.wait_check_tpm.wait()
            # Get tm from tpm
            for index in range(8): # loop to select tpm
                with self._tpm_lock:
                    if self.tpm_active[index]:
                        # check if two seconds have elapsed
                        if (time() - self.counter_previous_time[index]) >= self.counter_time:
                            self.countertime_flag[index] = True 
                            self.counter_previous_time[index] = time() # negligible time difference
                        else:
                            self.countertime_flag[index] = False 
                        try:
                            L = self.tpm_active[index].get_health_status()
                            if self.first_measure[index]: 
                                self.setShadowThresholds(index, L)
                                self.first_measure[index] = False
                                self.countertime_flag[index] = False 
                            if self.wg.check_tpm_savedata.isChecked(): self.saveTpmData(L,index)
                            if self.qbutton_tpm[index].styleSheet() == "background-color: rgb(255, 255, 0); color: rgb(0, 0, 0)":
                                self.qbutton_tpm[index].setStyleSheet(colors("black_on_green"))
                        except Exception as e:
                            self.logger.error(f"Failed to get TPM#{index+1}  Telemetry: {e}")
                            self.qbutton_tpm[index].setStyleSheet(colors("black_on_yellow"))
                            continue
                        with self._tpm_lock_GUI:
                            self.signal_update_tpm_attribute.emit(L,index)
            sleep(float(self.interval_monitor))    


    def unfoldTpmAttribute(self, tpm_dict, tpm_index):
        """
        Update TPM attribute values in the GUI tables.

        Unfolds and updates TPM attribute values in the GUI tables based on the provided TPM dictionary and index.

        Parameters:
        - tpm_dict (dict): Dictionary containing TPM attribute values.
        - tpm_index (int): Index indicating the TPM instance.

        Returns:
        None
        """
        with self._tpm_lock_GUI:
            for i in range(len(self.tpm_table[tpm_index])): #loop to select table
                led_id = self.selectLed(i)
                table = self.tpm_table[tpm_index][i]
                for key in list(self.tpm_table_address[i].values()): # loop to select the content of the table
                    if isinstance(key,list):
                        tpm_values = []
                        filtered_alarm =  []
                        filtered_warning = []
                        tpm_attr = []
                        for attribute in key:
                            v = eval("tpm_dict" + attribute)
                            va = eval("self.tpm_alarm_shadow[tpm_index]" + attribute)
                            vw = eval("self.tpm_warning_shadow[tpm_index]" + attribute)
                            tpm_values.extend(list(v.values())) if not(isinstance(v,bool)) else tpm_values.append(v)
                            ta = list(v.keys()) if not(isinstance(v,bool)) else v
                            tpm_attr.extend([f"{attribute} {x}" for x in ta] if not (isinstance(v,bool)) else [attribute])
                            filtered_alarm.extend(list(va.values())) if not(isinstance(va,bool)) else filtered_alarm.append(va)
                            filtered_warning.extend(list(vw.values())) if not(isinstance(vw,bool)) else filtered_warning.append(vw)
                    elif not(isinstance(eval("tpm_dict" + key),tuple)) and not(isinstance(eval("tpm_dict" + key),bool)):
                        tpm_values = list(eval('tpm_dict'+key).values())
                        ta = list(eval('tpm_dict'+key).keys())
                        tpm_attr = [f"{key} {x}" for x in ta]
                        filtered_alarm = list(eval('self.tpm_alarm_shadow[tpm_index]'+key).values())
                        filtered_warning = list(eval('self.tpm_warning_shadow[tpm_index]'+key).values())
                    else:
                        tpm_attr = [key]
                        tpm_values = [eval('tpm_dict'+key)] #for a tuple
                        filtered_alarm = [eval('self.tpm_alarm_shadow[tpm_index]'+key)]
                        filtered_warning = [eval('self.tpm_warning_shadow[tpm_index]'+key)]
                    correction = 0 #for voltage tables: It si splitted in 2 tables
                    self.handler_tables(table, tpm_index, tpm_attr, correction, led_id, tpm_values, key, filtered_alarm, filtered_warning, tpm_dict)


    def handler_tables(self, table, tpm_index, tpm_attr, correction, led_id, tpm_values, key, filtered_alarm, filtered_warning, tpm_dict):
        """
        Handle updating of values in the GUI table cells.

        Handles updating of values in the GUI table cells based on the provided parameters.

        Parameters:
        - table: The GUI table widget.
        - tpm_index (int): Index indicating the TPM instance.
        - tpm_attr (list): List of TPM attribute names.
        - correction (int): Correction value for voltage tables.
        - led_id: ID of the LED corresponding to the table.
        - tpm_values (list): List of TPM attribute values.
        - key: Key specifying the attribute address.
        - filtered_alarm (list): List of filtered alarm values.
        - filtered_warning (list): List of filtered warning values.
        - tpm_dict (dict): Dictionary containing TPM attribute values.

        Returns:
        None
        """
        for j in range(len(tpm_values)): #loop to write values in the proper table cell
            if key == '["voltages"]' and j == int(len(tpm_values)/2):
                table = self.voltage_table_bis[tpm_index]
                correction = int(len(tpm_values)/2)
            cell_index = j - correction
            value = tpm_values[cell_index + correction]
            table.setItem(cell_index,0, QtWidgets.QTableWidgetItem(str(value)))
            item = table.item(cell_index, 0)
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            if isinstance(filtered_alarm[cell_index],list):
                min_alarm = filtered_alarm[cell_index+ correction][0]
                min_warn = filtered_warning[cell_index+ correction][0]
                max_alarm = filtered_alarm[cell_index+ correction][1] 
                max_warn = filtered_warning[cell_index+ correction][1]
            else:
                max_alarm =filtered_alarm[cell_index + correction]
                min_alarm = max_alarm
                max_warn = filtered_warning[cell_index + correction]
                min_warn = max_warn
            if not(type(value) == str or value == None):
                if key in self.counter_list and self.countertime_flag[tpm_index]:
                    if value == max_alarm:
                        self.handlerAlarm(table, item, cell_index, value, tpm_index, tpm_attr, correction, led_id, min_alarm, max_alarm)
                        summary_flag = True
                    else:
                        self.setCounterThresholds(tpm_index,tpm_dict, key)
                        summary_flag = False
                elif not(min_alarm <= value <= max_alarm) and not(key in self.counter_list):
                    self.handlerAlarm(table, item, cell_index, value, tpm_index, tpm_attr, correction, led_id, min_alarm, max_alarm)
                    summary_flag = True
                elif not(min_warn <= value <= max_warn) and not(item.background().color().name() == '#ff0000') and not(key in self.counter_list):
                    self.handlerWarning(table, item, cell_index, value, tpm_index, tpm_attr, correction, led_id, min_alarm, max_alarm)
                    summary_flag = True
                else:
                    item.setForeground(QColor("black"))
                    item.setBackground(QColor("#ffffff"))
                    summary_flag = False
                self.tileSummaryTable(summary_flag,tpm_attr[cell_index+correction],tpm_index,f'[min:{min_alarm},max:{max_alarm}]',value)
    

    def handlerAlarm(self, table, item, cell_index, value, tpm_index, tpm_attr, correction, led_id, min_alarm, max_alarm):
        """
        Handle an alarm condition in the TPM.

        Handles an alarm condition in the TPM by updating the GUI table, item colors, and logging the alarm.

        Parameters:
        - table: The GUI table widget.
        - item: The GUI table item.
        - cell_index (int): Index indicating the cell in the table.
        - value: The value triggering the alarm.
        - tpm_index (int): Index indicating the TPM instance.
        - tpm_attr (list): List of TPM attribute names.
        - correction (int): Correction value for voltage tables.
        - led_id: ID of the LED corresponding to the table.
        - min_alarm: Minimum threshold for the alarm condition.
        - max_alarm: Maximum threshold for the alarm condition.

        Returns:
        None
        """
        item.setForeground(QColor("white"))
        item.setBackground(QColor("#ff0000")) # red
        table.setItem(cell_index,1, QtWidgets.QTableWidgetItem(str(value)))
        item = table.item(cell_index,1)
        item.setForeground(QColor("white"))
        item.setBackground(QColor("#ff0000")) # red
        stringa = f"ALARM in TPM{tpm_index+1} -- {tpm_attr[cell_index+correction]} parameter is out of range: value: {value} with threshold:[min:{min_alarm},max:{max_alarm}]"
        self.logger.error(stringa)
        # Change the color only if it not 1=red
        if not(self.qled_tpm[tpm_index][led_id].Colour==1):
            self.qled_tpm[tpm_index][led_id].Colour = Led.Red
            self.qled_tpm[tpm_index][led_id].value = True

    def handlerWarning(self, table, item, cell_index, value, tpm_index, tpm_attr, correction, led_id, min_alarm, max_alarm):
        """
        Handle a warning condition in the TPM.

        Handles a warning condition in the TPM by updating the GUI table, item colors, and logging the warning.

        Parameters:
        - table: The GUI table widget.
        - item: The GUI table item.
        - cell_index (int): Index indicating the cell in the table.
        - value: The value triggering the warning.
        - tpm_index (int): Index indicating the TPM instance.
        - tpm_attr (list): List of TPM attribute names.
        - correction (int): Correction value for voltage tables.
        - led_id: ID of the LED corresponding to the table.
        - min_alarm: Minimum threshold for the warning condition.
        - max_alarm: Maximum threshold for the warning condition.

        Returns:
        None
        """
        item.setForeground(QColor("white"))
        item.setBackground(QColor("#ff8000")) # orange
        table.setItem(cell_index,1, QtWidgets.QTableWidgetItem(str(value)))
        item = table.item(cell_index, 1)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        item.setForeground(QColor("white"))
        item.setBackground(QColor("#ff8000")) #orange
        stringa = f"WARNING in TPM{tpm_index+1} -- {tpm_attr[cell_index+correction]} parameter is near the out of range threshold: value: {value} with threshold:[min:{min_alarm},max:{max_alarm}]"
        self.logger.warning(stringa)
        # Change the color only if it is 4=Grey
        if self.qled_tpm[tpm_index][led_id].Colour==4: 
            self.qled_tpm[tpm_index][led_id].Colour=Led.Orange
            self.qled_tpm[tpm_index][led_id].value = True
                        
    def tileSummaryTable(self, flag, attr, tpm_id, s, value):
        """
        Update the TPM alarm summary table.

        Updates the TPM alarm summary table based on the provided parameters.

        Parameters:
        - flag (bool): Flag indicating the alarm condition.
        - attr: TPM attribute triggering the alarm or warning.
        - tpm_id (int): Index indicating the TPM instance.
        - s: Threshold information for the alarm or warning.
        - value: The value triggering the alarm or warning.

        Returns:
        None
        """
        stringa = f'tpm#{tpm_id+1}, {attr} {s}'
        exist = self.tpm_alarm_summary.findItems(stringa,QtCore.Qt.MatchFlag.MatchExactly)
        if flag and not(exist):
            self.tpm_alarm_summary.insertRow(0)
            self.tpm_alarm_summary.setItem(0,0, QtWidgets.QTableWidgetItem(f'{stringa}'))
            self.tpm_alarm_summary.setItem(0,1, QtWidgets.QTableWidgetItem(f'{value}'))
        elif exist:
            row = exist[0].row()
            if not flag:
                self.tpm_alarm_summary.removeRow(row)
            else:
                self.tpm_alarm_summary.setItem(row,1, QtWidgets.QTableWidgetItem(f'{value}'))
        else:
            return
    

    def selectLed(self,index):
        """
        Select the LED index based on the given input index.

        Parameters:
        - index (int): The input index.

        Returns:
        int: The selected LED index.
        """
        # with if for python<3.10
        if index < 4: #0,1,2,3
            return index
        elif index < 7: #4,5,6
            return 4 
        elif index < 12: #7,8,9,10,11
            return 5
        elif index > 31:
            return 7
        else:
            return 6 #12-31


    def setupTpmHdf5(self):
        """
        Set up HDF5 files for TPM monitoring.

        Returns:
        list: List of HDF5 file objects for TPM monitoring.
        """
        default_app_dir = str(Path.home()) + "/.skalab/monitoring/tpm_monitor/"
        if not(self.tlm_hdf_tpm_monitor):
            if not self.profile['Tpm']['tpm_data_path'] == "":
                fname = self.profile['Tpm']['tpm_data_path']
                fname = os.path.expanduser(fname)
                if  os.path.exists(fname) != True:
                    try:
                        os.makedirs(fname)
                    except:
                        self.logger.error(f"Failed creating TPMs monitor folder\n {fname}")
                        fname = default_app_dir
                for tpm_id in range(8):
                    temp = os.path.join(fname,datetime.datetime.strftime(datetime.datetime.utcnow(), "monitor_tpm"+ f"{tpm_id+1}"+"_%Y-%m-%d_%H%M%S.hdf5"))
                    print(f"Logging TPM {tpm_id+1} at: {temp}")
                    self.tlm_hdf_tpm_monitor.append(h5py.File(temp, 'a'))
                return self.tlm_hdf_tpm_monitor
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Please Select a valid path to save the Monitor data and save it into the current profile")
                msgBox.setWindowTitle("Error!")
                msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                msgBox.exec_()
                return None

    def saveTpmData(self, tpm_tlm, tpm_id):
        """
        Save TPM telemetry data to HDF5 file.

        Parameters:
        - tpm_tlm: TPM telemetry data.
        - tpm_id (int): TPM instance ID.

        Returns:
        None
        """
        currentDateAndTime = datetime.datetime.utcnow()
        currentTime = currentDateAndTime.strftime("%H:%M:%S:%f")
        if self.tlm_hdf_tpm_monitor[tpm_id]:
            filename = self.tlm_hdf_tpm_monitor[tpm_id]
            try:
                dt = h5py.special_dtype(vlen=str) 
                feature_names = np.array(str(tpm_tlm), dtype=dt) 
                filename.create_dataset(currentTime,data=feature_names)
            except:
                self.logger.error(f"WRITE SUBRACK TELEMETRY ERROR at {datetime}") 