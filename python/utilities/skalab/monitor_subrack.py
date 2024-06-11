import os.path
import gc
import copy
import h5py
import numpy as np
import logging
import yaml
import datetime
from time import sleep
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QColor
from hardware_client import WebHardwareClient
from monitor_tile import MonitorTPM
from monitor_station_init import *
from skalab_log import SkalabLog
from skalab_utils import colors,h5py
from threading import Thread, Event, Lock
from time import sleep
from pathlib import Path


def populateSubrackTable(frame, attributes, top):
    """
    Create Subrack table

    Parameters:
        frame: The frame to which the table belongs.
        attributes: List of attributes for the Subrack table.
        top: List of top-level entries for the Subrack table.

    Returns:
        Tuple containing the created table and sub-attributes.
    """
    qtable = []
    sub_attr = []
    size_a = len(attributes)
    #error if monitor.json has ",," in top level entry
    for j in range(size_a):
        qtable.append(getattr(frame, f"table{top[j]}"))
        sub_attr.append(list(list(attributes[j].values())[0].keys()))
        qtable[j].setRowCount(len(sub_attr[j]))
        qtable[j].setColumnCount(2)
        qtable[j].setVerticalHeaderLabels(sub_attr[j])  
        qtable[j].setHorizontalHeaderLabels(("Value", "Warn/Alrm")) 
    return qtable, sub_attr

class MonitorSubrack(MonitorTPM):
    """
    Main UI Window class

    Attributes:
        signalTlm: PyQt signal for telemetry.
        signal_to_monitor: PyQt signal for monitoring.
        signal_to_monitor_for_tpm: PyQt signal for TPM monitoring.
    """
    # Signal for Slots
    signalTlm = QtCore.pyqtSignal()
    signal_to_monitor = QtCore.pyqtSignal()
    signal_to_monitor_for_tpm = QtCore.pyqtSignal()

    def __init__(self, ip=None, port=None, uiFile="", profile="",swpath=""):
        """
        Initialise main window

        Parameters:
            ip: IP address.
            port: Port number.
            uiFile: UI file path.
            profile: Profile information.
            swpath: Software path.
        """

        super(MonitorSubrack, self).__init__(uiFile="Gui/skalab_monitor.ui", profile=profile, swpath=swpath)   
        self.interval_monitor = self.profile['Monitor']['tpm_query_interval']
        self.subrack_custom_thresholds_file = self.profile['Subrack']['subrack_thresholds_file']
        self.fans_mode = eval(self.profile['Subrack']['fans_mode'])
        self.fans_speed = eval(self.profile['Subrack']['fans_speed'])
        self.subrack_interval = self.profile['Monitor']['subrack_query_interval']
        self.subrack_warning_factor = eval(self.profile['Warning Factor']['subrack_warning_parameter'])
        self.tlm_keys = []
        self.tpm_status_info = {} 
        self.from_subrack = {}
        self.top_attr = list(self.profile['Subrack']['top_level_attributes'].split(","))

        self.last_telemetry = {"tpm_supply_fault":[None] *8,"tpm_present":[None] *8,"tpm_on_off":[None] *8}
        self.query_once = []
        self.query_deny = []
        self.connected = False
        self.reload_subrack(ip=ip, port=port)
        self.tlm_file = ""
        self.tlm_hdf = None
        self.subrack_alarm_summary = self.wg.subrack_summary
        self.subrack_alarm_summary.setColumnCount(2)
        self.subrack_alarm_summary.setColumnWidth(0, 550)
        header = self.subrack_alarm_summary.horizontalHeader()
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.subrack_alarm_summary.setHorizontalHeaderLabels(['Subrack Alarms Summary','Value'])
        self.wg.subrackbar.hide()
        self.wg.tpmbar.hide()
        self.subrack_led = [None,None]
        self.subrack_led[0] = Led(self.wg.overview_frame)
        self.wg.grid_led.addWidget(self.subrack_led[0])
        self.subrack_led[0].setObjectName("qled1_warn_alar")
        self.subrack_led[1] = Led(self.wg.overview_frame)
        self.wg.grid_led_2.addWidget(self.subrack_led[1])
        self.subrack_led[1].setObjectName("qled2_warn_alar")
        self.client = None
        self.data_charts = {}
        self.loadEventsSubrack()
        self.show()
        
        self.skipThreadPause = False
        #self.slot_thread = Thread(name="Slot", target= self.slot1)
        #self.temperature_thread = Thread(name="temp", target = self.temp1)   
        self.subrackTlm = Thread(name="Subrack Telemetry", target=self.readSubrackTlm, daemon=True)
        self.wait_check_subrack = Event()
        self._subrack_lock = Lock()
        self._subrack_lock_GUI = Lock()
        self.subrackTlm.start()


    def loadSubrackThreshold(self):
        """
        Load Subrack Threshold
        """
        fd = QtWidgets.QFileDialog()
        fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        filter = "YAML file(*.yaml *.yml)"
        options = fd.options()
        self.sub_filename = fd.getOpenFileName(self, caption="Select a Subrack Alarm Thresholds file...",
                                              directory="./", options=options,filter = filter)[0]  
        self.processSubrackThreshold(self.sub_filename)
        

    def processSubrackThreshold(self,sub_filename):
        """
        Process the Subrack Threshold.

        Parameters:
            sub_filename (str): Path to the Subrack Threshold file.

        Returns:
            None
        """ 
        try:
            fi = QtCore.QFileInfo(sub_filename)
            if not(sub_filename == ''):
                with open(sub_filename) as file:
                    MIN_MAX_MONITORING_POINTS = (yaml.load(file, Loader=yaml.Loader)["subrack_monitoring_points"] or {})
                with self._subrack_lock_GUI:
                    if self.connected:
                        # TODO self.subrack_warning_factor
                        self.alarm = self.getThreshold(MIN_MAX_MONITORING_POINTS,self.top_attr)#,self.subrack_warning_factor)
                        self.wg.qline_subrack_threshold.setText(fi.fileName())
                    else:
                        self.logger.warning("Connect to the Subrack to load the new threshold table.")  
        except Exception as e:
            self.logger.warning(f"Subrack custom threshold file not loaded: {e}")
        return


    # TODO this methods are temporary
    def getThreshold(self,tlm,top_attr):
        """
        Get the Subrack Threshold.

        Parameters:
            tlm (list): List of telemetry data.
            top_attr (list): List of top-level attributes.

        Returns:
            list: Subrack alarm.
        """
        #log load default api values
        alarm = copy.deepcopy(tlm)
        alarm_values = {}
        for i in range(len(top_attr)):
            keys = list(tlm[i][top_attr[i]].keys())
            for j in range(len(keys)):
                alarm_values = list(tlm[i][top_attr[i]][keys[j]]['exp_value'].values())
                alarm[i][top_attr[i]][keys[j]] =  alarm_values
        writeThresholds(self.wg.ala_text,self.wg.war_text, alarm)
        return alarm

    def loadEventsSubrack(self):
        """
        Load events for the Subrack.

        Returns:
            None
        """
        self.wg.qbutton_clear_subrack.clicked.connect(lambda: self.clearSubrackValues())
        self.wg.subrack_button.clicked.connect(lambda: self.connect())
        self.wg.qbutton_subrack_edit.clicked.connect(lambda: editClone(self.wg.qline_subrack_threshold.text(), self.text_editor))
        self.wg.qbutton_subrack_threshold.clicked.connect(lambda: self.loadSubrackThreshold())
        for n, t in enumerate(self.qbutton_tpm):
            t.clicked.connect(lambda state, g=n: self.cmdSwitchTpm(g))
        self.wg.qbutton_on_all.clicked.connect(lambda: self.cmdSwitchTpmsOn())
        self.wg.qbutton_off_all.clicked.connect(lambda: self.cmdSwitchTpmsOff())
        self.wg.qbutton_start_test.clicked.connect(self.startTestTime)
        self.wg.qbutton_stop_test.clicked.connect(self.stopTestTime)

    def startTestTime(self):
        time = str(datetime.datetime.strftime(datetime.datetime.utcnow(), "%Y-%m-%d_%H:%M:%S"))
        self.wg.qline_start_test.setText(time)
        self.logger.info(f"TEST STARTED at {time}")
    
    def stopTestTime(self):
        time = str(datetime.datetime.strftime(datetime.datetime.utcnow(), "%Y-%m-%d_%H:%M:%S"))
        self.wg.qline_stop_test.setText(time)
        self.logger.info(f"TEST STOPPED at {time}")


    def reload_subrack(self, ip=None, port=None):
        """
        Reload the Subrack.

        Parameters:
            ip (str): IP address.
            port (int): Port number.

        Returns:
            None
        """
        if ip is not None:
            self.ip = ip
        else:
            self.ip = str(self.profile['Subrack']['ip'])
        if port is not None:
            self.port = port
        else:
            self.port = int(self.profile['Subrack']['port'])
        self.wg.qline_ip.setText("%s (%d)" % (self.ip, self.port))
        if 'Query' in self.profile.keys():
            if 'once' in self.profile['Query'].keys():
                self.query_once = list(self.profile['Query']['once'].split(","))
            if 'deny' in self.profile['Query'].keys():
                self.query_deny = list(self.profile['Query']['deny'].split(","))

    
    def connect(self):
        """
        Connect to the Subrack.

        Returns:
            None
        """
        self.tlm_keys = []
        self.tpm_on_off = [False] * 8
        self.tpm_active = [None] * 8
        if not self.wg.qline_ip.text() == "":
            if not self.connected:
                self.wg.subrackbar.show()
                self.logger.info("Connecting to Subrack %s:%d..." % (self.ip, int(self.port)))
                self.client = WebHardwareClient(self.ip, self.port)
                self.wg.subrackbar.setValue(20)
                if self.client.connect():
                    self.logger.info("Successfully connected")
                    self.logger.info("Querying list of Subrack API attributes...")
                    # The following command is necessary in order to fill the subrack paraemeters table,\
                    # to set the thresholds values and to know the key paramenters exposed by the API.
                    self.subrack_dictionary = self.client.execute_command(command="get_health_dictionary")["retvalue"]
                    self.wg.subrackbar.setValue(30)
                    try:
                        del self.subrack_dictionary['iso_datetime']
                    except TypeError:
                        self.logger.error("get_health_dictionary has failed. Please check subrack log file.")
                        self.wg.subrackbar.hide()
                        self.wg.subrack_button.setStyleSheet("background-color: rgb(253, 218, 13);")
                        self.wg.subrack_button.setText("ERROR")
                        return
                    for i in range(len(self.top_attr)):
                        if self.top_attr[i] in self.subrack_dictionary.keys():
                            diz = {self.top_attr[i]: self.subrack_dictionary[self.top_attr[i]]}
                            del self.subrack_dictionary[self.top_attr[i]]
                        elif self.top_attr[i] != 'others':
                            res = {}
                            for key, value in self.subrack_dictionary.items():
                                if isinstance(value, dict):
                                    for subkey, subvalue in value.items():
                                        if isinstance(subvalue, dict) and self.top_attr[i] in subvalue:
                                            res[subkey] = {
                                                'unit': subvalue[self.top_attr[i]]['unit'],
                                                'exp_value': subvalue[self.top_attr[i]]['exp_value']
                                            } 
                                            #delete empty dictionary
                                            del self.subrack_dictionary[key][subkey][self.top_attr[i]]
                                    for jk in list(self.subrack_dictionary[key]):
                                        if len(self.subrack_dictionary[key][jk]) == 0: del self.subrack_dictionary[key][jk]
                            for k in list(self.subrack_dictionary.keys()):
                                if len(self.subrack_dictionary[k]) == 0:  del self.subrack_dictionary[k]
                            diz = {self.top_attr[i] : res} 
                        else:
                            res = {}
                            for value in self.subrack_dictionary.values():
                                if isinstance(value, dict):
                                    res.update(value)
                                else:
                                    diz.update({self.top_attr[i] : value})  
                            diz = {self.top_attr[i]:res}
                        self.tlm_keys.append(diz)
                    with open(r'subrack_monitoring_min_max.yaml', 'w+') as file:
                        file.write("subrack_monitoring_points:")
                        file.write("\n")
                        yaml.dump(self.tlm_keys, file, sort_keys=False)
                    self.logger.info("Populate monitoring table...")
                    [self.subrack_table, self.sub_attribute] = populateSubrackTable(self.wg,self.tlm_keys,self.top_attr)
                    self.wg.subrackbar.setValue(40)
                    for tlmk in self.query_once:
                        data = self.client.get_attribute(tlmk)
                        if data["status"] == "OK":
                            self.tpm_status_info[tlmk] = data["value"]
                        else:
                            self.tpm_status_info[tlmk] = data["info"]
                    if 'assigned_tpm_ip_adds' in self.tpm_status_info.keys():
                        self.tpm_assigned_tpm_ip_adds = self.tpm_status_info['assigned_tpm_ip_adds']
                    else:
                        self.tpm_assigned_tpm_ip_adds = self.client.get_attribute('assigned_tpm_ip_adds')
                    if 'api_version' in self.tpm_status_info.keys():
                        self.logger.info("Subrack API version: " + self.tpm_status_info['api_version'])
                    else:
                        self.logger.warning("The Subrack is running with a very old API version!")
                    self.wg.subrackbar.setValue(60)
                    self.connected = True
                    self.populateTileInstance()
                    self.tlm_hdf = self.setupSubrackHdf5()
                    # TODO: Uncomment the next line when subrack attributes are defined 
                    #[self.alarm, self.warning] = getThreshold(self.wg, self.tlm_keys,self.top_attr,self.subrack_warning_factor)
                    try:
                        fi = QtCore.QFileInfo(self.subrack_custom_thresholds_file)
                        if not(self.subrack_custom_thresholds_file == ''):
                            with open(self.subrack_custom_thresholds_file) as file:
                                MIN_MAX_MONITORING_POINTS = (yaml.load(file, Loader=yaml.Loader)["subrack_monitoring_points"] or {})
                            with self._subrack_lock_GUI:
                                if self.connected:
                                    # TODO self.subrack_warning_factor
                                    self.alarm = self.getThreshold(MIN_MAX_MONITORING_POINTS,self.top_attr)#,self.subrack_warning_factor)
                                    self.wg.qline_subrack_threshold.setText(fi.fileName())
                                else:
                                    self.logger.warning("Connect to the Subrack to load the new threshold table.")  
                    except Exception as e:
                        self.logger.warning(f"Subrack custom threshold file not loaded: {e}")
                        self.alarm = self.getThreshold(self.tlm_keys,self.top_attr) # temporaney line. See TODO above
                        self.logger.warning(f"Subrack default threshold loaded")
                        
                    self.wg.subrackbar.setValue(70)
                    for tlmk in standard_subrack_attribute: 
                        data = self.client.get_attribute(tlmk)
                        if data["status"] == "OK":
                            self.tpm_status_info[tlmk] = data["value"]
                        else:
                            self.tpm_status_info[tlmk] = data["info"]
                            self.logger.error(f"Error with self.client.get_attribute({tlmk})")
                    self.wg.subrackbar.setValue(80)
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(78, 154, 6);")
                    self.subrack_led[0].Colour = Led.Green
                    self.subrack_led[0].m_value = False
                    self.subrack_led[1].Colour = Led.Green
                    self.subrack_led[1].m_value = False
                    self.wg.subrack_button.setText("ONLINE")
                    [item.setEnabled(True) for item in self.qbutton_tpm]
                    with self._subrack_lock:
                        self.updateTpmStatus()
                    self.wg.subrackbar.setValue(100)
                    self.wg.qbutton_clear_subrack.setEnabled(True)
                    self.wg.qbutton_clear_tpm.setEnabled(True)
                    self.wg.qbutton_on_all.setEnabled(True)
                    self.wg.qbutton_off_all.setEnabled(True)
                    self.wg.qbutton_start_test.setEnabled(True)
                    self.wg.qbutton_stop_test.setEnabled(True)
                    self.wait_check_subrack.set()
                    self.wg.subrackbar.hide()
                else:
                    self.logger.error("Unable to connect to the Subrack server %s:%d" % (self.ip, int(self.port)))
                    self.wg.qline_ip.setText("ERROR!")
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(253, 218, 13);")
                    self.wg.subrack_button.setText("OFFLINE")
                    [item.setEnabled(False) for item in self.qbutton_tpm]
                    self.client = None
                    self.connected = False
                    self.wg.qbutton_station_init.setEnabled(False) 
                    self.wg.qbutton_station_connect.setEnabled(False)
                    self.wg.qbutton_start_test.setEnabled(False)
                    self.wg.qbutton_stop_test.setEnabled(False)
            else:
                self.logger.info("Disconnecting from Subrack %s:%d..." % (self.ip, int(self.port)))
                self.wait_check_tpm.clear()
                self.wait_check_subrack.clear()
                self._tpm_lock.acquire()
                self.connected = False
                self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(255, 255, 255);")
                self.wg.qbutton_station_init.setEnabled(False) 
                self.wg.qbutton_station_init1.setStyleSheet("background-color: rgb(255, 255, 255);")
                self.wg.qbutton_station_init1.setEnabled(False)
                self.wg.qbutton_station_connect.setStyleSheet("background-color: rgb(255, 255, 255);")
                self.wg.qbutton_station_connect.setEnabled(False) 
                self.wg.subrack_button.setStyleSheet("background-color: rgb(204, 0, 0);")
                self.wg.subrack_button.setText("OFFLINE")
                self.subrack_led[0].Colour = Led.Grey
                self.subrack_led[0].m_value = False
                self.subrack_led[1].Colour = Led.Grey
                self.subrack_led[1].m_value = False
                self.wg.qbutton_clear_subrack.setEnabled(False)
                self.wg.qbutton_clear_tpm.setEnabled(False)
                self.wg.qbutton_on_all.setEnabled(False)
                self.wg.qbutton_off_all.setEnabled(False)
                self.wg.qbutton_start_test.setEnabled(True)
                self.wg.qbutton_stop_test.setEnabled(True)
                [item.setEnabled(False) for item in self.qbutton_tpm]
                self._tpm_lock.release()
                self.client.disconnect()
                del self.client
                self.tpm_on_off = [False] * 8
                self.tpm_active = [None] * 8
                gc.collect()

        else:
            self.wg.qline_ip.setText("MISSING IP!")
            self.wg.qline_ip.setStyleSheet("background-color: rgb(104, 204, 104);")
            self.wait_check_tpm.clear()
            self.wait_check_subrack.clear()

    
    def cmdSwitchTpm(self, slot):
        """
        Command to switch a TPM on or off.

        Parameters:
            slot (int): TPM slot number.

        Returns:
            None
        """
        self.wg.tpmbar.show()
        self.wait_check_subrack.clear()
        self.skipThreadPause = True
        self.qbutton_tpm[slot].setEnabled(False)
        self.wg.tpmbar.setValue(10)
        # it seems that with ... and ... does not work
        self._subrack_lock.acquire()
        self._tpm_lock.acquire()
        if self.connected:
            if self.tpm_status_info["tpm_on_off"][slot]:
                self.wg.tpmbar.setValue(30)
                self.wg.qbutton_station_init.setEnabled(False)
                self.wg.qbutton_station_init1.setEnabled(False)
                self.client.execute_command(command="turn_off_tpm", parameters="%d" % (int(slot) + 1))
                self.logger.info("Turn OFF TPM-%02d" % (int(slot) + 1))
                self.wg.tpmbar.setValue(40)
            else:
                self.wg.tpmbar.setValue(30)
                self.wg.qbutton_station_init.setEnabled(False)
                self.wg.qbutton_station_init1.setEnabled(False)
                self.client.execute_command(command="turn_on_tpm", parameters="%d" % (int(slot) + 1))
                self.logger.info("Turn ON TPM-%02d" % (int(slot) + 1)) 
                self.wg.tpmbar.setValue(40)
            sleep(2) # Sleep required to wait for the turn_off/on_tpm command to complete
            self.wg.tpmbar.setValue(70)
            sleep(2) # Sleep required to wait for the turn_off/on_tpm command to complete
            self.wg.tpmbar.setValue(90)
            self.wg.tpmbar.setValue(100)
            self.qbutton_tpm[slot].setEnabled(True)
            self._subrack_lock.release()
            self._tpm_lock.release()
        self.wait_check_subrack.set()
        self.wg.tpmbar.hide()

    def cmdSwitchTpmsOn(self):
        """
        Command to switch all TPMs on.

        Returns:
            None
        """
        delay = 5
        self.wg.tpmbar.show()
        self.wait_check_subrack.clear()
        self.skipThreadPause = True
        self.wg.qbutton_on_all.setEnabled(False)
        self.wg.tpmbar.setValue(10)
        # it seems that with ... and ... does not work
        self._subrack_lock.acquire()
        self._tpm_lock.acquire()
        if self.connected:
            for i in range(4):
                f_m = self.fans_mode[i]
                f_s = self.fans_speed[i]
                if f_s != 'None' and f_m == 'MANUAL':
                    self.client.execute_command(command="set_fan_mode", parameters = f"{i+1},0")
                    sleep(0.5)
                    self.client.execute_command(command="set_subrack_fan_speed", parameters = f"{i+1},{f_s}")
                    self.logger.info(f"FAN#{i+1} is set in MANUAL mode with speed {f_s}%.")
                    print(f"FAN#{i+1} is set in MANUAL mode with speed {f_s}%.")
                    sleep(0.5)
                else:
                    self.client.execute_command(command="set_fan_mode", parameters = f"{i+1},1")
                    self.logger.info(f"FAN#{i+1} is set in AUTO mode.")
                    print(f"FAN#{i+1} is set in AUTO mode.")
                    sleep(0.5)

            self.client.execute_command(command="turn_on_tpms")
            self.logger.info("Turn On ALL TPMs")
            self.wg.tpmbar.setValue(30)
            data = self.client.get_attribute("tpm_on_off")
            self.wg.tpmbar.setValue(50)
            while not data["status"] == "OK":
                self.logger.info("Waiting for operation complete: " + data["info"])
                sleep(0.5)
                delay =+ delay
                self.wg.tpmbar.setValue(delay + 50)
                data = self.client.get_attribute("tpm_on_off")
            sleep(0.5)
            self.updateTpmStatus()
            self.wg.tpmbar.setValue(100)
            self.wg.qbutton_on_all.setEnabled(True)
            self._subrack_lock.release()
            self._tpm_lock.release()
        self.wait_check_subrack.set()
        self.wg.tpmbar.hide()

    def cmdSwitchTpmsOff(self):
        """
        Command to switch all TPMs off.

        Returns:
            None
        """
        delay = 5
        self.wg.tpmbar.show()
        self.wait_check_subrack.clear()
        self.skipThreadPause = True
        self.wg.qbutton_off_all.setEnabled(False)
        self.wg.tpmbar.setValue(10)
        # it seems that with ... and ... does not work
        self._subrack_lock.acquire()
        self._tpm_lock.acquire()
        if self.connected:
            self.client.execute_command(command="turn_off_tpms")
            self.logger.info("Turn Off ALL TPMs")
            self.wg.tpmbar.setValue(30)
            data = self.client.get_attribute("tpm_on_off")
            self.wg.tpmbar.setValue(50)
            while not data["status"] == "OK":
                self.logger.info("Waiting for operation complete: " + data["info"])
                sleep(0.5)
                delay =+ delay
                self.wg.tpmbar.setValue(delay + 50)
                data = self.client.get_attribute("tpm_on_off")
            sleep(0.5)
            self.updateTpmStatus()
            self.wg.tpmbar.setValue(100)
            self.wg.qbutton_off_all.setEnabled(True)
            self._subrack_lock.release()
            self._tpm_lock.release()
            for i in range(4):
                self.client.execute_command(command="set_fan_mode", parameters = f"{i+1},1")
                self.logger.info(f"FAN#{i+1} is set in AUTO mode.")
                print(f"FAN#{i+1} is set in AUTO mode.")
                sleep(0.5)
        self.wait_check_subrack.set()
        self.wg.tpmbar.hide()
        self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(204, 0, 0);")
        self.wg.qbutton_station_init1.setStyleSheet("background-color: rgb(204, 0, 0);")
        self.wg.qbutton_station_connect.setStyleSheet("background-color: rgb(204, 0, 0);")


    def getTelemetry(self):
        """
        Get telemetry data from the Subrack.

        Returns:
            None
        """
        check_connection = False
        with self._subrack_lock:
            while True:
                data = self.client.execute_command(command="get_health_status")
                if data["status"] == "OK":
                    self.from_subrack =  data['retvalue']
                    self.wg.qline_time_now.setText(str(datetime.datetime.strftime(datetime.datetime.utcnow(), "%Y-%m-%d_%H:%M:%S")))
                    self.tpm_status_info['tpm_present'] = list(self.from_subrack['slots']['presence'].values())
                    self.tpm_status_info['tpm_on_off'] = list(self.from_subrack['slots']['on'].values()) 
                    if self.wg.check_subrack_savedata.isChecked(): self.saveSubrackData(self.from_subrack)
                    if not(self.wg.qbutton_station_init.isEnabled()): self.wg.qbutton_station_init.setEnabled(True)
                    if not(self.wg.qbutton_station_init1.isEnabled()):self.wg.qbutton_station_init1.setEnabled(True)
                    if not(self.wg.qbutton_station_connect.isEnabled()):self.wg.qbutton_station_connect.setEnabled(True)
                    if check_connection:
                        self.logger.info(f"Subrack REACHABLE!")
                        self.wg.qline_ip.setText("%s (%d)" % (self.ip, self.port))
                        self.wg.subrack_button.setStyleSheet("background-color: rgb(78, 154, 6);")
                    break
                else:
                    self.logger.error(f"Subrack NOT REACHABLE! DATA ARE NOT UPDATED. Next tempt in 2 seconds...")
                    self.wg.qline_ip.setText("Subrack NOT REACHABLE!")
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(253, 218, 13);")
                    check_connection = True
                    sleep(2.0)

            
    def readSubrackTlm(self):
        """
        Continuously read telemetry data from the Subrack.

        Returns:
            None
        """
        while True:
            self.wait_check_subrack.wait()
            if self.connected:
                self.getTelemetry()
                self.signalTlm.emit()
            with self._subrack_lock_GUI:            
                self.signal_to_monitor.emit()
            cycle = 0.0
            while cycle < (float(self.subrack_interval)) and not self.skipThreadPause:
                sleep(0.1)
                cycle = cycle + 0.1
            self.skipThreadPause = False

    
    def readwriteSubrackAttribute(self):
        """
        Read and write attributes of the Subrack.

        Returns:
            None
        """
        diz = copy.deepcopy(self.from_subrack)
        if diz == '':
            self.logger.error(f"Warning: get_health_status return an empty dictionary. Try again at the next polling cycle")
            return
        with self._subrack_lock_GUI:
            for index_table in range(len(self.top_attr)):
                table = self.subrack_table[index_table]
                top_attr_now = self.top_attr[index_table]
                led_index = 1 if 'SLOT' in top_attr_now else 0
                if top_attr_now in diz.keys():
                    if (list(diz[top_attr_now]) == self.sub_attribute[index_table]):
                        attribute_data = diz[top_attr_now]
                        filtered_alarm =  self.alarm[index_table][top_attr_now]
                        #filtered_warning = self.warning[index_table][top_attr]
                        diz.pop(self.top_attr[index_table])
                    else:
                        break
                elif top_attr_now != 'others':
                    res = {}
                    for key, value in diz.items():
                        if isinstance(value, dict):
                            for subkey, subvalue in value.items():
                                if isinstance(subvalue, dict) and top_attr_now in subvalue:
                                    res[subkey] = subvalue[top_attr_now]
                                    diz[key][subkey].pop(self.top_attr[index_table])
                            for jk in list(diz[key]):
                                if not bool(diz[key][jk]): del diz[key][jk]
                    for k in list(diz.keys()):
                        if len(diz[k]) == 0:  del diz[k]
                    attribute_data = res
                    filtered_alarm =  self.alarm[index_table][top_attr_now]
                    #filtered_warning = self.warning[index_table][top_attr_now]
                else:
                    res = {}
                    temp = []
                    for key, value in diz.items():
                        if isinstance(value, dict):
                            res.update(value)
                        temp.append(key)
                    [diz.pop(t) for t in temp]
                    attribute_data = res
                    filtered_alarm =  self.alarm[index_table][top_attr_now]
                    #filtered_warning = self.warning[index_table][top_attr_now]
                        
                attrs = list(attribute_data.keys())
                values = list(attribute_data.values())
                for i in range(len(attribute_data)):
                    value = values[i]
                    attr = attrs[i]
                    table.setItem(i,0, QtWidgets.QTableWidgetItem(str(value)))
                    item = table.item(i, 0)
                    item.setTextAlignment(QtCore.Qt.AlignCenter)
                    if not(type(value)==str or value==None or filtered_alarm[attr][0]==None):
                        if not(filtered_alarm[attr][0] <= value <= filtered_alarm[attr][1]): 
                            item.setForeground(QColor("white"))
                            item.setBackground(QColor("#ff0000")) # red
                            table.setItem(i,1, QtWidgets.QTableWidgetItem(str(value)))
                            item = table.item(i, 1)
                            item.setTextAlignment(QtCore.Qt.AlignCenter)
                            item.setForeground(QColor("white"))
                            item.setBackground(QColor("#ff0000")) # red
                            summary_flag = True
                            self.logger.error(f"ALARM in Subrack{attr} parameter is out of range: value: {value} with threshold:[min:{filtered_alarm[attr][0]},max:{filtered_alarm[attr][1]}]")
                            # Change the color only if it not 1=red
                            if not(self.subrack_led[led_index].Colour==1):
                                self.subrack_led[led_index].Colour = Led.Red
                                self.subrack_led[led_index].value = True
                        else:
                            item.setForeground(QColor("black"))
                            item.setBackground(QColor("#ffffff")) # white
                            summary_flag = False
                    self.subrackSummaryTable(summary_flag,f'{top_attr_now}-{attr}',f'[min:{filtered_alarm[attr][0]},max:{filtered_alarm[attr][1]}]',value)
                    # TODO: Uncomment when subrack attributes are definitive.
                    """                     
                    elif not(filtered_warning[attr][0] < value < filtered_warning[attr][1]) and not(item.background().color().name() == '#ff0000'):
                    table.setItem(i,1, QtWidgets.QTableWidgetItem(str(value)))
                    item = table.item(i, 1)
                    item.setTextAlignment(QtCore.Qt.AlignCenter)
                    item.setForeground(QColor("white"))
                    item.setBackground(QColor("#ff8000")) #orange
                    self.logger.warning(f"WARNING in Subrack{attr} parameter is near the out of range threshold: value: {value}\
                                            with threshold:[min:{filtered_alarm[attr][0]},max:{filtered_alarm[attr][1]}]"
                    # Change the color only if it is 4=Grey
                    if self.subrack_led.Colour==4: 
                            self.subrack_led.Colour=Led.Orange
                            self.subrack_led.value = True
                    """
                    

    def subrackSummaryTable(self, flag, attr, s, value):
        """
        Update the Subrack Summary Table based on the flag, attribute, status, and value.

        Args:
            flag (bool): Flag indicating whether the update is for an alarm.
            attr (str): Attribute name.
            s (str): Status information.
            value: Attribute value.

        Returns:
            None
        """
        stringa = f'{attr} {s}'
        exist = self.subrack_alarm_summary.findItems(stringa,QtCore.Qt.MatchFlag.MatchExactly)
        if flag and not(exist):
            self.subrack_alarm_summary.insertRow(0)
            #self.subrack_alarm_summary.setVerticalHeaderItem(0,QtWidgets.QTableWidgetItem("subrack"))
            self.subrack_alarm_summary.setItem(0,0, QtWidgets.QTableWidgetItem(f'{stringa}'))
            self.subrack_alarm_summary.setItem(0,1, QtWidgets.QTableWidgetItem(f'{value}'))
        elif exist:
            row = exist[0].row()
            if not flag:
                self.subrack_alarm_summary.removeRow(row)
            else:
                self.subrack_alarm_summary.setItem(row,1, QtWidgets.QTableWidgetItem(f'{value}'))
        else:
            return

    def updateTpmStatus(self):
        """
        Update TPM status on QButtons based on telemetry information.

        Returns:
            None
        """
        # TPM status on QButtons
        try:
            for n in range(8):
                if "tpm_present" in self.tpm_status_info.keys():
                    if self.tpm_status_info["tpm_present"][n]:
                        if "tpm_on_off" in self.tpm_status_info.keys():
                            if self.tpm_status_info["tpm_on_off"][n]:
                                self.qbutton_tpm[n].setStyleSheet(colors("black_on_green"))
                                self.tpm_on_off[n] = True
                            else:
                                self.qbutton_tpm[n].setStyleSheet(colors("black_on_red"))
                                self.tpm_on_off[n] = False
                    else:
                        self.qbutton_tpm[n].setStyleSheet(colors("black_on_grey"))
                        self.tpm_on_off[n] = False
            if (self.tpm_status_info["tpm_present"]!= self.last_telemetry["tpm_present"]) | (self.tpm_status_info["tpm_on_off"]!= self.last_telemetry["tpm_on_off"]):
                self.signal_to_monitor_for_tpm.emit()
                self.last_telemetry["tpm_present"] = self.tpm_status_info["tpm_present"]
                self.last_telemetry["tpm_on_off"] = self.tpm_status_info["tpm_on_off"]
        except:
            self.logger.info(f"Tpms status not updated: Subrack data are not ready yet")
           

    def clearSubrackValues(self):
        """
        Clear Subrack values in the GUI.

        Returns:
            None
        """
        with (self._subrack_lock_GUI):
            self.subrack_alarm_summary.setRowCount(0)
            self.subrack_led[0].Colour = Led.Green
            self.subrack_led[0].m_value = False
            self.subrack_led[1].Colour = Led.Green
            self.subrack_led[1].m_value = False
            for table in self.subrack_table:
                table.clearContents()

    
    def setupSubrackHdf5(self):
        """
        Save Subrack telemetry data to the HDF5 file.

        Args:
            subrack_tlm (dict): Subrack telemetry data.

        Returns:
            None
        """
        default_app_dir = str(Path.home()) + "/.skalab/monitoring/subrack_monitor/"
        if not(self.tlm_hdf):
            if not self.profile['Subrack']['subrack_data_path'] == "":
                fname = self.profile['Subrack']['subrack_data_path']
                fname = os.path.expanduser(fname)
                if os.path.exists(fname) != True:
                    try:
                        os.makedirs(fname)
                    except:
                        self.logger.error(f"Failed creating subrack monitor folder\n {fname}")
                        fname = default_app_dir
                fname = os.path.join(fname,datetime.datetime.strftime(datetime.datetime.utcnow(), "monitor_subrack_%Y-%m-%d_%H%M%S.hdf5"))
                print(f"Logging SUBRACK at: {fname}")
                self.tlm_hdf = h5py.File(fname, 'a')
                return self.tlm_hdf
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Please Select a valid path to save the Monitor data and save it into the current profile")
                msgBox.setWindowTitle("Error!")
                msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                msgBox.exec_()
                return None

    
    def saveSubrackData(self, subrack_tlm):
        """
        Override the close event to prompt confirmation and handle necessary cleanup.

        Args:
            event (QtWidgets.QCloseEvent): Close event.

        Returns:
            None
        """
        datetime = subrack_tlm['iso_datetime']
        del subrack_tlm['iso_datetime']
        if self.tlm_hdf:
            try:
                dt = h5py.special_dtype(vlen=str) 
                feature_names = np.array(str(subrack_tlm), dtype=dt) 
                self.tlm_hdf.create_dataset(datetime, data=feature_names)

            except:
                self.logger.error(f"WRITE SUBRACK TELEMETRY ERROR at {datetime}")            

    
    def closeEvent(self, event):
        """
        Handle the close event of the application.

        Args:
            event: Close event object.

        Returns:
            None
        """
        result = QtWidgets.QMessageBox.question(self,
                                                "Confirm Exit...",
                                                "Are you sure you want to exit ?",
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        event.ignore()
        if result == QtWidgets.QMessageBox.Yes:
            event.accept()
            self._subrack_lock.acquire()
            self._tpm_lock.acquire()
            self.logger.info("Stopping Threads")
            if type(self.tlm_hdf) is not None:
                try:
                    self.tlm_hdf.close()
                    self.tlm_hdf_tpm_monitor.close()
                except:
                    pass
        self.logger.info("Stopping Threads")
        self.logger.stopLog()    
        sleep(1) 