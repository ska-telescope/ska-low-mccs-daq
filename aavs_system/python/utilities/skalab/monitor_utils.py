import logging
import os
from pyaavs.station import configuration
from PyQt5 import QtWidgets
from PyQt5.QtCore import QSize, QByteArray, QRectF, pyqtProperty
from PyQt5.QtWidgets import QWidget, QStyleOption
from PyQt5.QtGui import QPainter
from colorsys import rgb_to_hls, hls_to_rgb
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QWidget


standard_subrack_attribute = {
                "tpm_present": [None]*8,
                "tpm_on_off": [None]*8
                }

tpm_tables_address = [
    {'temperature': '["temperatures"]'},\
    {'voltage': '["voltages"]'},\
    {'current': '["currents"]'},\
    {'alarm': '["alarms"]'},\
    {'adcpll': '["adcs"]["pll_status"]'},\
    {'adcsysref': '["adcs"]["sysref_timing_requirements"]'},\
    {'adccounter': '["adcs"]["sysref_counter"]'},\
    {'clock_fpga0': ['["timing"]["clocks"]["FPGA0"]', '["timing"]["clock_managers"]["FPGA0"]']},\
    {'clock_fpga1': ['["timing"]["clocks"]["FPGA1"]','["timing"]["clock_managers"]["FPGA1"]']},\
    {'time':'["timing"]["timestamp"]'},\
    {'pps': '["timing"]["pps"]'},\
    {'pll': '["timing"]["pll"]'},\
    {'jesd': ['["io"]["jesd_interface"]["link_status"]', '["io"]["jesd_interface"]["lane_status"]']},\
    {'jesdlane_fpga0_core0': '["io"]["jesd_interface"]["lane_error_count"]["FPGA0"]["Core0"]'},\
    {'jesdlane_fpga0_core1': '["io"]["jesd_interface"]["lane_error_count"]["FPGA0"]["Core1"]'},\
    {'jesdlane_fpga1_core0': '["io"]["jesd_interface"]["lane_error_count"]["FPGA1"]["Core0"]'},\
    {'jesdlane_fpga1_core1': '["io"]["jesd_interface"]["lane_error_count"]["FPGA1"]["Core1"]'},\
    {'jesdfpga0': '["io"]["jesd_interface"]["resync_count"]'},\
    {'jesdfpga1': '["io"]["jesd_interface"]["qpll_status"]'},\
    {'ddr': '["io"]["ddr_interface"]["initialisation"]'},\
    {'ddr1_reset': '["io"]["ddr_interface"]["reset_counter"]'},\
    {'ddr1_rd_cnt': '["io"]["ddr_interface"]["rd_cnt"]'},\
    {'ddr1_wr_cnt': '["io"]["ddr_interface"]["wr_cnt"]'},\
    {'ddr1_rd_dat_cnt': '["io"]["ddr_interface"]["rd_dat_cnt"]'},\
    {'f2f': '["io"]["f2f_interface"]'},\
    {'udp': ['["io"]["udp_interface"]["arp"]', '["io"]["udp_interface"]["status"]']},\
    {'crcerrorcount': '["io"]["udp_interface"]["crc_error_count"]'},\
    {'linkuplosscount': '["io"]["udp_interface"]["linkup_loss_count"]'},\
    {'biperrorcount_fpga0': '["io"]["udp_interface"]["bip_error_count"]["FPGA0"]'},\
    {'biperrorcount_fpga1': '["io"]["udp_interface"]["bip_error_count"]["FPGA1"]'},\
    {'decodeerrorcount_fpga0': '["io"]["udp_interface"]["bip_error_count"]["FPGA0"]'},\
    {'decodeerrorcount_fpga1': '["io"]["udp_interface"]["bip_error_count"]["FPGA1"]'},\
    {'dsp': '["dsp"]["tile_beamf"]'},\
    {'dsp_station': '["dsp"]["station_beamf"]["status"]'},\
    {'ddr_parity': '["dsp"]["station_beamf"]["ddr_parity_error_count"]'}]

def editClone(fname, text_editor):
    """
    Open the specified file using the given text editor.

    Parameters:
    - fname (str): The path to the file to be opened.
    - text_editor (str): The command or executable for the text editor.

    Returns:
    None
    """
    if not text_editor == "":
        if not fname == "":
            if os.path.exists(fname):
                os.system(text_editor + " " + fname + " &")
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("The selected file does not exist!")
                msgBox.setWindowTitle("Error!")
                msgBox.exec_()
    else:
        msgBox = QtWidgets.QMessageBox()
        txt = "\nA text editor is not defined in the current profile file.\n\n['Extras']\ntext_editor = <example: gedit>'\n\n"
        msgBox.setText(txt)
        msgBox.setWindowTitle("Warning!")
        msgBox.setIcon(QtWidgets.QMessageBox.Warning)
        msgBox.exec_()

# TODO USE this 2 methods when subrack attributes are defined
""" def getThreshold(wg,tlm,top_attr,warning_factor):
    default = wg.qline_subrack_threshold.text()
    if default != 'API_alarm.txt':
        try:
            with open(default, 'r') as file:
                a_lines = []
                for line in file:
                    line = line.strip()
                    line = eval(line)
                    a_lines.append(line)
            alarm = a_lines
            warning = copy.deepcopy(alarm)
            for i in range(len(top_attr)):
                keys = list(alarm[i][top_attr[i]].keys())
                for j in range(len(keys)):
                    alarm_values = list(alarm[i][top_attr[i]][keys[j]])
                    if alarm_values != [None,None]:
                        factor = (alarm_values[1]-alarm_values[0]) * (warning_factor)
                        warning_values = [round(alarm_values[0] + factor,2), round(alarm_values[1] - factor,2)]
                    else:
                        warning_values = [None,None]
                    warning[i][top_attr[i]][keys[j]] =  warning_values
        except:
            #log error
            [alarm,warning] = getDefaultThreshold(tlm,top_attr,warning_factor)
    else: 
        [alarm,warning] = getDefaultThreshold(tlm,top_attr,warning_factor)

    writeThresholds(wg.ala_text,wg.war_text, alarm, warning)
    return alarm, warning 

def getDefaultThreshold(tlm,top_attr,warning_factor):
    #log load default api values
    alarm = copy.deepcopy(tlm)
    warning = copy.deepcopy(tlm)
    alarm_values = {}
    warning_values = {}
    for i in range(len(top_attr)):
        keys = list(tlm[i][top_attr[i]].keys())
        for j in range(len(keys)):
            alarm_values = list(tlm[i][top_attr[i]][keys[j]]['exp_value'].values())
            alarm[i][top_attr[i]][keys[j]] =  alarm_values
            if alarm_values != [None,None]:
                factor = (alarm_values[1]-alarm_values[0]) * (warning_factor)
                warning_values = [round(alarm_values[0] + factor,2), round(alarm_values[1] - factor,2)]
            else:
                warning_values = [None,None]
            warning[i][top_attr[i]][keys[j]] =  warning_values
    file = open('API_alarm.txt','w+')
    for item in alarm:
        file.write(str(item) + "\n")
    file.close()
    return alarm, warning """

def writeThresholds(alarm_box, warning_box, alarm, *warning):
    """
    Write alarm and warning thresholds to the specified QTextEdit widgets.

    Parameters:
    - alarm_box (QtWidgets.QPlainTextEdit): The widget for displaying alarm thresholds.
    - warning_box (QtWidgets.QPlainTextEdit): The widget for displaying warning thresholds.
    - alarm (list or dict): The alarm thresholds to be displayed.
    - warning (tuple): Optional. Additional warning thresholds to be displayed.

    Returns:
    None
    """
    alarm_box.clear()
    warning_box.clear()
    if isinstance(alarm,list):
        for item in alarm:
            alarm_box.appendPlainText(str(item))
        if warning:
            for item in warning:
                warning_box.appendPlainText(str(item))
        else:
            warning_box.appendPlainText("Warning thresholds are not implementd yet.")
    else:
        for key, value in alarm.items():  
            alarm_box.appendPlainText('%s:%s\n' % (key, value))
        if warning:
            for key, value in warning[0].items():  
                warning_box.appendPlainText('%s:%s\n' % (key, value))
    return

class Led(QWidget):
    """
    Custom LED widget that can display different colors and shapes.

    Attributes:
    - Circle (int): Constant representing the circular shape.
    - Red (int): Constant representing the red color.
    - Green (int): Constant representing the green color.
    - Orange (int): Constant representing the orange color.
    - Grey (int): Constant representing the grey color.

    Methods:
    - __init__(self, parent=None, **kwargs): Constructor for the Led class.
    - Colour(self): Getter for the color property.
    - setColour(self, newColour): Setter for the color property.
    - value(self): Getter for the value property.
    - setValue(self, value): Setter for the value property.
    - sizeHint(self): Returns the recommended size for the widget.
    - adjust(self, r, g, b): Adjusts the color represented by RGB values.
    - paintEvent(self, event): Handles the paint event to draw the widget.

    Properties:
    - Colour (int): Property representing the color of the LED.
    - value (bool): Property representing the state of the LED (on/off).
    """
    
    Circle   = 1
    Red    = 1
    Green  = 2
    Orange = 3
    Grey   = 4

    shapes={
        Circle:"""
            <svg height="80.000000px" id="svg9493" width="80.000000px" xmlns="http://www.w3.org/2000/svg">
              <defs id="defs9495">
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient6650" x1="23.402565" x2="23.389874" xlink:href="#linearGradient6506" y1="44.066776" y2="42.883698"/>
                <linearGradient id="linearGradient6494">
                  <stop id="stop6496" offset="0.0000000" style="stop-color:%s;stop-opacity:1.0000000;"/>              
                  <stop id="stop6498" offset="1.0000000" style="stop-color:%s;stop-opacity:1.0000000;"/>
                </linearGradient>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient6648" x1="23.213980" x2="23.201290" xlink:href="#linearGradient6494" y1="42.754631" y2="43.892632"/>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient6646" x1="23.349695" x2="23.440580" xlink:href="#linearGradient5756" y1="42.767944" y2="43.710873"/>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient6644" x1="23.193102" x2="23.200001" xlink:href="#linearGradient5742" y1="42.429230" y2="44.000000"/>
                <linearGradient id="linearGradient6506">
                  <stop id="stop6508" offset="0.0000000" style="stop-color:#ffffff;stop-opacity:0.0000000;"/>
                  <stop id="stop6510" offset="1.0000000" style="stop-color:#ffffff;stop-opacity:0.87450981;"/>
                </linearGradient>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient7498" x1="23.402565" x2="23.389874" xlink:href="#linearGradient6506" y1="44.066776" y2="42.883698"/>
                <linearGradient id="linearGradient7464">
                  <stop id="stop7466" offset="0.0000000" style="stop-color:#00039a;stop-opacity:1.0000000;"/>
                  <stop id="stop7468" offset="1.0000000" style="stop-color:#afa5ff;stop-opacity:1.0000000;"/>
                </linearGradient>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient7496" x1="23.213980" x2="23.201290" xlink:href="#linearGradient7464" y1="42.754631" y2="43.892632"/>
                <linearGradient id="linearGradient5756">
                  <stop id="stop5758" offset="0.0000000" style="stop-color:#828282;stop-opacity:1.0000000;"/>
                  <stop id="stop5760" offset="1.0000000" style="stop-color:#929292;stop-opacity:0.35294119;"/>
                </linearGradient>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient9321" x1="22.935030" x2="23.662106" xlink:href="#linearGradient5756" y1="42.699776" y2="43.892632"/>
                <linearGradient id="linearGradient5742">
                  <stop id="stop5744" offset="0.0000000" style="stop-color:#adadad;stop-opacity:1.0000000;"/>
                  <stop id="stop5746" offset="1.0000000" style="stop-color:#f0f0f0;stop-opacity:1.0000000;"/>
                </linearGradient>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient7492" x1="23.193102" x2="23.200001" xlink:href="#linearGradient5742" y1="42.429230" y2="44.000000"/>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient9527" x1="23.193102" x2="23.200001" xlink:href="#linearGradient5742" y1="42.429230" y2="44.000000"/>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient9529" x1="22.935030" x2="23.662106" xlink:href="#linearGradient5756" y1="42.699776" y2="43.892632"/>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient9531" x1="23.213980" x2="23.201290" xlink:href="#linearGradient7464" y1="42.754631" y2="43.892632"/>
                <linearGradient gradientUnits="userSpaceOnUse" id="linearGradient9533" x1="23.402565" x2="23.389874" xlink:href="#linearGradient6506" y1="44.066776" y2="42.883698"/>
              </defs>
              <g id="layer1">
                <g id="g9447" style="overflow:visible" transform="matrix(31.25000,0.000000,0.000000,31.25000,-625.0232,-1325.000)">
                  <path d="M 24.000001,43.200001 C 24.000001,43.641601 23.641601,44.000001 23.200001,44.000001 C 22.758401,44.000001 22.400001,43.641601 22.400001,43.200001 C 22.400001,42.758401 22.758401,42.400001 23.200001,42.400001 C 23.641601,42.400001 24.000001,42.758401 24.000001,43.200001 z " id="path6596" style="fill:url(#linearGradient6644);fill-opacity:1.0000000;stroke:Fill;stroke-width:0.00000001;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4.0000000;stroke-opacity:0.0000000;overflow:visible" transform="translate(-2.399258,-1.000000e-6)"/>
                  <path d="M 23.906358,43.296204 C 23.906358,43.625433 23.639158,43.892633 23.309929,43.892633 C 22.980700,43.892633 22.713500,43.625433 22.713500,43.296204 C 22.713500,42.966975 22.980700,42.699774 23.309929,42.699774 C 23.639158,42.699774 23.906358,42.966975 23.906358,43.296204 z " id="path6598" style="fill:url(#linearGradient6646);fill-opacity:1.0000000;stroke:Fill;stroke-width:0.80000001;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4.0000000;stroke-opacity:0.0000000;overflow:visible" transform="matrix(1.082474,0.000000,0.000000,1.082474,-4.431649,-3.667015)"/>
                  <path d="M 23.906358,43.296204 C 23.906358,43.625433 23.639158,43.892633 23.309929,43.892633 C 22.980700,43.892633 22.713500,43.625433 22.713500,43.296204 C 22.713500,42.966975 22.980700,42.699774 23.309929,42.699774 C 23.639158,42.699774 23.906358,42.966975 23.906358,43.296204 z " id="path6600" style="fill:url(#linearGradient6648);fill-opacity:1.0000000;stroke:Fill;stroke-width:0.80000001;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4.0000000;stroke-opacity:0.0000000;overflow:visible" transform="matrix(0.969072,0.000000,0.000000,0.969072,-1.788256,1.242861)"/>
                  <path d="M 23.906358,43.296204 C 23.906358,43.625433 23.639158,43.892633 23.309929,43.892633 C 22.980700,43.892633 22.713500,43.625433 22.713500,43.296204 C 22.713500,42.966975 22.980700,42.699774 23.309929,42.699774 C 23.639158,42.699774 23.906358,42.966975 23.906358,43.296204 z " id="path6602" style="fill:url(#linearGradient6650);fill-opacity:1.0000000;stroke:Fill;stroke-width:0.80000001;visibility: hidden;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4.0000000;stroke-opacity:0.0000000;overflow:visible" transform="matrix(0.773196,0.000000,0.000000,0.597938,2.776856,17.11876)"/>
                </g>
              </g>
            </svg>
        """}
    
    colours={Red: (0xCF, 0x00, 0x00), 
            Green  : (0x4e, 0x9a, 0x06), 
            Orange : (0xe2, 0x76, 0x02), 
            Grey   : (0x7a, 0x7a, 0x7a)}

    def __init__(self, parent=None, **kwargs):
        """
        Constructor for the Led class.

        Parameters:
        - parent (QWidget): Parent widget.
        - **kwargs: Additional keyword arguments.
        """
        self.m_value=False
        self.m_Colour=Led.Grey
        self.m_shape=Led.Circle

        QWidget.__init__(self, parent, **kwargs)
        self.renderer=QSvgRenderer()

    def Colour(self): 
        """Getter for the color property."""
        return self.m_Colour
    
    def setColour(self, newColour):
        """
        Setter for the color property.

        Parameters:
        - newColour (int): New color value.
        """
        self.m_Colour=newColour
        self.update()    
    Colour=pyqtProperty(int, Colour, setColour)

    def value(self):
        """Getter for the value property."""
        return self.m_value
    
    def setValue(self, value):
        """
        Setter for the value property.

        Parameters:
        - value (bool): New value (True for on, False for off).
        """
        self.m_value=value
        self.update()    
    value=pyqtProperty(bool, value, setValue)

    def sizeHint(self): 
        """
        Returns the recommended size for the widget.

        Returns:
        QSize: Recommended size for the widget.
        """
        return QSize(48,48)

    def adjust(self, r, g, b):
        """
        Adjusts the color represented by RGB values.

        Parameters:
        - r (int): The red component of the RGB color (0-255).
        - g (int): The green component of the RGB color (0-255).
        - b (int): The blue component of the RGB color (0-255).

        Returns:
        tuple: A tuple representing the adjusted RGB values (r, g, b).
        """
        def normalise(x): return x/255.0
        def denormalise(x): return int(x*255.0)
        (h,l,s)=rgb_to_hls(normalise(r),normalise(g),normalise(b))        
        (nr,ng,nb)=hls_to_rgb(h,l*1.5,s)
        return (denormalise(nr),denormalise(ng),denormalise(nb))

    def paintEvent(self, event):
        """
        Handles the paint event to draw the widget.

        Parameters:
        - event (QPaintEvent): The paint event.

        Returns:
        None
        """
        option=QStyleOption()
        option.initFrom(self)

        h=option.rect.height()
        w=option.rect.width()
        size=min(w,h)
        x=abs(size-w)/2.0
        y=abs(size-h)/2.0
        bounds=QRectF(x,y,size,size)
        painter=QPainter(self);
        painter.setRenderHint(QPainter.Antialiasing, True)

        (dark_r,dark_g,dark_b)=self.colours[self.m_Colour]
        dark_str="rgb(%d,%d,%d)" % (dark_r,dark_g,dark_b)
        light_str="rgb(%d,%d,%d)" % self.adjust(dark_r,dark_g,dark_b)

        __xml=(self.shapes[self.m_shape]%(dark_str,dark_str)).encode('utf8')
        self.renderer.load(QByteArray(__xml))
        self.renderer.render(painter, bounds)