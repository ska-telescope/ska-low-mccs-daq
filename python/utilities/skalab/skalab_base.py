import json
import os
import configparser
import shutil
import time

from PyQt5 import QtCore, QtGui, QtWidgets, uic
from skalab_utils import getTextFromFile
from pathlib import Path
import sys

default_app_dir = str(Path.home()) + "/.skalab/"


class ConfWizard(QtWidgets.QMainWindow):
    def __init__(self, App="", Profile="", Path="", msg=""):
        super(ConfWizard).__init__()
        self.open = True

        self.wg = QtWidgets.QMainWindow()
        self.wg.resize(1200, 940)
        self.wg.setWindowTitle("SKALAB Configuration Wizard")

        pic_wizard = QtWidgets.QLabel(self.wg)
        pic_wizard.setGeometry(30, 20, 100, 100)
        pic_wizard.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/wizard.png"))

        label = QtWidgets.QLabel(self.wg)
        label.setGeometry(150, 35, 500, 50)
        label.setText("Configuration Wizard")
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        font.setPointSize(16)
        label.setFont(font)

        label = QtWidgets.QLabel(self.wg)
        label.setGeometry(150, 60, 500, 50)
        label.setText("Please check and solve any path conflicts")
        font = QtGui.QFont()
        font.setBold(False)
        font.setItalic(True)
        # font.setWeight(75)
        font.setPointSize(10)
        label.setFont(font)

        label = QtWidgets.QLabel(self.wg)
        label.setGeometry(560, 30, 200, 50)
        label.setText("SKALAB Module")
        font = QtGui.QFont()
        font.setBold(True)
        font.setPointSize(18)
        label.setFont(font)
        label.setStyleSheet("color: #2d6da8")
        label.setAlignment(QtCore.Qt.AlignCenter)

        label = QtWidgets.QLabel(self.wg)
        label.setGeometry(560, 55, 200, 50)
        label.setText(App)
        font = QtGui.QFont()
        font.setBold(True)
        font.setPointSize(16)
        font.setItalic(True)
        label.setFont(font)
        label.setStyleSheet("color: green")
        label.setAlignment(QtCore.Qt.AlignCenter)

        label = QtWidgets.QLabel(self.wg)
        label.setGeometry(880, 40, 200, 50)
        label.setText(msg)
        font = QtGui.QFont()
        font.setBold(True)
        font.setPointSize(27)
        font.setItalic(True)
        label.setFont(font)
        label.setStyleSheet("color: black")
        label.setAlignment(QtCore.Qt.AlignCenter)

        self.wgConf = QtWidgets.QWidget(self.wg)
        self.wgConf.setGeometry(QtCore.QRect(10, 120, 1080, 780))
        self.sbase = SkalabBase(App=App, Profile=Profile, Path=Path, parent=self.wgConf)
        self.qbuttonDone = QtWidgets.QPushButton(self.wg)
        self.qbuttonDone.setGeometry(QtCore.QRect(930, 140, 89, 31))
        self.qbuttonDone.setText("DONE")
        self.qbuttonDone.raise_()
        self.qbuttonDone.clicked.connect(lambda: self.validate())
        self.wg.show()

    def validate(self):
        self.wg.close()


class SkalabBase(QtWidgets.QMainWindow):
    def __init__(self, App="", Profile="", Path="", parent=None):
        super().__init__()
        self.connected = False
        self.profile = {}
        self.jprofile = {}
        self.newKeys = []
        self.errorKeys = []
        self.alarm = False
        self.wgProfile = uic.loadUi("Gui/skalab_profile.ui", parent)
        self.wgProfile.qlabel_errors.setVisible(False)
        self.wgProfile.qlabel_newkeys.setVisible(False)
        self.wgProfile.qbutton_load.clicked.connect(lambda: self.load())
        self.wgProfile.qbutton_saveas.clicked.connect(lambda: self.save_as_profile())
        self.wgProfile.qbutton_save.clicked.connect(lambda: self.save_profile())
        self.wgProfile.qbutton_delete.clicked.connect(
            lambda: self.delete_profile(self.wgProfile.qcombo_profile.currentText()))
        self.wgProfile.qbutton_browse.clicked.connect(lambda: self.browse())
        self.wgProfile.qbutton_clear.clicked.connect(lambda: self.clear())
        self.wgProfile.qbutton_apply.clicked.connect(lambda: self.apply())
        self.load_profile(App=App, Profile=Profile, Path=Path)
        self.wgProfile.qtable_conf.cellDoubleClicked.connect(self.editValue)

    def populate_help(self, uifile="Gui/skalab_subrack.ui"):
        with open(uifile) as f:
            data = f.readlines()
        helpkeys = [d[d.rfind('name="Help_'):].split('"')[1] for d in data if 'name="Help_' in d]
        for k in helpkeys:
            self.wg.findChild(QtWidgets.QTextEdit, k).setText(getTextFromFile(k.replace("_", "/")+".html"))

    def load(self):
        if not self.connected:
            self.load_profile(App=self.profile['Base']['app'],
                              Profile=self.wgProfile.qcombo_profile.currentText(),
                              Path=self.profile['Base']['path'])

        else:
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText("Please switch to OFFLINE first!")
            msgBox.setWindowTitle("Error!")
            msgBox.exec_()

    def reload(self):
        # If needed, this will be overridden by children for custom post load
        pass

    def readConfig(self, fname):
        profile = {}
        confparser = configparser.ConfigParser()
        confparser.optionxform = str
        confparser.read(fname)
        for s in confparser.sections():
            if not s in profile.keys():
                profile[s] = {}
            for k in confparser._sections[s]:
                val = confparser._sections[s][k]
                if '~' in val:
                    home = os.getenv("HOME")
                    val = val.replace('~', home)
                profile[s][k] = val
        return profile

    def readJson(self, fname):
        profile = {}
        with open(fname) as json_file:
            jdata = json.load(json_file)
        home = os.getenv("HOME")
        for s in jdata.keys():
            for k in jdata[s].keys():
                if jdata[s][k]['type'] == 'path':
                    if '~' in jdata[s][k]['value']:
                        val = jdata[s][k]['value']
                        jdata[s][k]['value'] = val.replace('~', home)
        return jdata

    def writeConfigFromJSON(self, pConfig):
        fname = pConfig['Base']['path']['value'] + pConfig['Base']['profile']['value'] + "/" + pConfig['Base']['app']['value'].lower() + ".ini"
        fname = os.path.expanduser(fname)
        conf = configparser.ConfigParser()
        conf.optionxform = str
        for s in pConfig.keys():
            # print(s, ": ", self.profile[s], type(self.profile[s]))
            if type(pConfig[s]) == dict:
                # print("Creating Dict", s)
                conf[s] = {}
                for k in pConfig[s]:
                #     # print("Adding ", k, self.profile[s][k])
                    conf[s][k] = str(pConfig[s][k]['value'])
            else:
                print("Malformed ConfigParser, found a non dict section!")
        with open(fname, 'w') as f:
            conf.write(f)

    def writeConfig(self, pConfig):
        fname = pConfig['Base']['path'] + pConfig['Base']['profile']
        fpath = Path(fname)
        fpath.mkdir(parents=True, exist_ok=True)
        fname += "/" + pConfig['Base']['app'].lower() + ".ini"
        conf = configparser.ConfigParser()
        conf.optionxform = str
        for s in pConfig.keys():
            # print(s, ": ", self.profile[s], type(self.profile[s]))
            if type(pConfig[s]) == dict:
                # print("Creating Dict", s)
                conf[s] = {}
                for k in pConfig[s]:
                #     # print("Adding ", k, self.profile[s][k])
                    conf[s][k] = str(pConfig[s][k])
            else:
                print("Malformed ConfigParser, found a non dict section!")
        with open(fname, 'w') as f:
            conf.write(f)

    def writeConfigToJSON(self, pConfig):
        fname = "Templates/" + pConfig['Base']['app'].lower() + ".json"
        conf = {}
        for s in pConfig.keys():
            if type(pConfig[s]) == dict:
                conf[s] = {}
                for k in pConfig[s]:
                    conf[s][k] = {'value': pConfig[s][k], 'type': 'string', 'desc': "n/a"}
        with open(fname, 'w') as outfile:
            outfile.write(json.dumps(conf, indent=4, sort_keys=True))

    def load_profile(self, App="", Profile="", Path=""):
        if not Profile == "":
            loadPath = Path + Profile + "/"
            fullPath = loadPath + App.lower() + ".ini"
            if os.path.exists(fullPath):
                print("Loading " + App + " Profile: " + Profile + " (" + fullPath + ")")
            else:
                print("\nThe " + Profile + " Profile for the App " + App +
                      " does not exist.\nGenerating a new one in " + fullPath)
                self.make_profile(App=App, Profile=Profile, Path=Path)

            self.wgProfile.qline_configuration_file.setText(fullPath)
            self.profile = self.readConfig(fullPath)
            self.jprofile = self.readJson("Templates/" + App.lower() + ".json")
            self.clear()
            self.validateProfile()
            for k in self.newKeys:
                if "," not in k:
                    self.profile[k] = {}
                else:
                    self.profile[k.split(",")[0]][k.split(",")[1]] = self.jprofile[k.split(",")[0]][k.split(",")[1]]['value']
            if not self.newKeys == []:
                self.wgProfile.qlabel_newkeys.setVisible(True)
            if not self.errorKeys == []:
                self.wgProfile.qlabel_errors.setVisible(True)
                #print("Trovate nuove chiavi\n", self.newKeys)
                # msgBox = QtWidgets.QMessageBox()
                # message = ("Found new sections/keys in JSON profile that are missing in the local profile file: <br>" +
                #            "<br>&nbsp;&nbsp;&nbsp;<b>" + self.profile['Base']['app'] + "/" +
                #            self.profile['Base']['profile'] + "</b>  <br>" +
                #            "<br>They will be automatically added with their default values.<br>" +
                #            "<br>Please check them (<span style='color: #000000; background-color: #99cc00;'>" +
                #            "GREEN</span>) and adjust with your needs.<br>")
                # msgBox.setText(message)
                # msgBox.setWindowTitle("WARNING: Found new Profile items")
                # msgBox.setIcon(QtWidgets.QMessageBox.Information)
                # details = ""
                # for k in self.newKeys:
                #     if not "," in k:
                #         details += "SECTION: " + k + "\n"
                #         self.profile[k] = {}
                #     else:
                #         details += "   - " + k.replace(",", ":  ") + "\n"
                #         self.profile[k.split(",")[0]][k.split(",")[1]] = self.jprofile[k.split(",")[0]][k.split(",")[1]]['value']
                # msgBox.setDetailedText(details)
                # msgBox.exec_()
            #print(self.newKeys)
            if (not self.errorKeys == []) or ():
                self.alarm = True
            self.populate_table_profile()
            self.updateProfileCombo(current=Profile)
            self.reload()

    def validateProfile(self):
        self.newKeys = []
        self.errorKeys = []
        for kj_section in self.jprofile.keys():
            if kj_section in self.profile.keys():
                for kj_attribute in self.jprofile[kj_section]:
                    if not kj_attribute in self.profile[kj_section]:
                        self.newKeys += [kj_section + "," + kj_attribute]
                    else:
                        if self.jprofile[kj_section][kj_attribute]['type'] == "int":
                            try:
                                foo = int(self.profile[kj_section][kj_attribute])
                            except:
                                self.errorKeys += [kj_section + "," + kj_attribute]
                        elif self.jprofile[kj_section][kj_attribute]['type'] == "float":
                            try:
                                foo = float(self.profile[kj_section][kj_attribute])
                            except:
                                self.errorKeys += [kj_section + "," + kj_attribute]
                        elif self.jprofile[kj_section][kj_attribute]['type'] == "string":
                            try:
                                foo = str(self.profile[kj_section][kj_attribute])
                            except:
                                self.errorKeys += [kj_section + "," + kj_attribute]
                        elif self.jprofile[kj_section][kj_attribute]['type'] == "path":
                            if not os.path.exists(self.profile[kj_section][kj_attribute]):
                                self.errorKeys += [kj_section + "," + kj_attribute]
                        elif self.jprofile[kj_section][kj_attribute]['type'] == "file":
                            if not os.path.isfile(self.profile[kj_section][kj_attribute]):
                                self.errorKeys += [kj_section + "," + kj_attribute]
            else:
                self.newKeys += [kj_section]
                for kj_attribute in self.jprofile[kj_section]:
                    self.newKeys += [kj_section + "," + kj_attribute]

    def delete_profile(self, profile_name):
        result = QtWidgets.QMessageBox.question(self,
                                                "Confirm Delete...",
                                                "Are you sure you want to delete the Profile '%s' for the App '%s'?" % (
                                                    profile_name, self.profile['Base']['app']),
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)

        if result == QtWidgets.QMessageBox.Yes:
            print("Removing", self.profile['Base']['path'] + profile_name + "/" + self.profile['Base']['app'])
            if os.path.exists(self.profile['Base']['path'] + profile_name + "/" + self.profile['Base']['app'].lower() + ".json"):
                # shutil.rmtree(self.profile['Base']['path'] + profile_name + "/" + self.profile['Base']['app'] + ".json")
                os.remove(self.profile['Base']['path'] + profile_name + "/" + self.profile['Base']['app'].lower() + ".json")
                self.updateProfileCombo(current="")
                self.load_profile(App=self.profile['Base']['app'],
                                  Profile=self.wgProfile.qcombo_profile.currentText(),
                                  Path=self.profile['Base']['path'])

    def make_profile(self, App="", Profile="", Path=""):
        """
            This method is called to generate a Profile File from scratch or to save changes
        """
        fname = Path + Profile + "/" + App.lower() + ".ini"
        if not os.path.exists(fname):
            defFile = "./Templates/" + App.lower() + ".json"
            if os.path.exists(defFile):
                self.jprofile = self.readJson(defFile)
                print("Copying the Template File", defFile)
                self.jprofile['Base']['profile']['value'] = Profile
                if not os.path.exists(Path[:-1]):
                    os.makedirs(Path[:-1])
                if not os.path.exists(Path + Profile):
                    os.makedirs(Path + Profile)
                self.writeConfigFromJSON(self.jprofile)
                self.profile = self.readConfig(fname)
                self.populate_table_profile()
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                msgBox.setText("The Template for the " +
                               App.upper() +
                               " Profile file is not available.\n" +
                               "Please, check it out from the repo.")
                msgBox.setWindowTitle("Error!")
                msgBox.exec_()
        else:
            profile = self.readTableProfile()
            profile['Base']['profile'] = Profile
            self.writeConfig(profile)

    def save_profile(self):
        self.make_profile(App=self.profile['Base']['app'],
                          Profile=self.profile['Base']['profile'],
                          Path=self.profile['Base']['path'])
        self.load_profile(App=self.profile['Base']['app'],
                          Profile=self.profile['Base']['profile'],
                          Path=self.profile['Base']['path'])

    def save_as_profile(self):
        text, ok = QtWidgets.QInputDialog.getText(self, 'Profiles', 'Enter a Profile name:')
        if ok:
            profile = self.readTableProfile()
            profile['Base']['profile'] = text
            # print(profile)
            self.writeConfig(profile)
            self.load_profile(App=self.profile['Base']['app'],
                              Profile=text,
                              Path=self.profile['Base']['path'])

    def populate_table_profile(self):
        self.wgProfile.qtable_conf.clearSpans()
        self.wgProfile.qtable_conf.setGeometry(QtCore.QRect(640, 20, 481, 821))
        self.wgProfile.qtable_conf.setObjectName("qtable_conf")
        self.wgProfile.qtable_conf.setColumnCount(1)
        self.wgProfile.qtable_conf.setWordWrap(True)

        total_rows = len(self.profile.keys())
        for i in self.profile.keys():
            total_rows = total_rows + len(self.profile[i]) + 1
        self.wgProfile.qtable_conf.setRowCount(total_rows)

        item = QtWidgets.QTableWidgetItem("Profile: " + self.profile['Base']['profile'])
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        item.setFlags(QtCore.Qt.ItemIsEnabled)
        self.wgProfile.qtable_conf.setHorizontalHeaderItem(0, item)

        item = QtWidgets.QTableWidgetItem(" ")
        item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        item.setFlags(QtCore.Qt.ItemIsEnabled)
        self.wgProfile.qtable_conf.setVerticalHeaderItem(0, item)

        q = 0
        for i in self.profile.keys():
            item = QtWidgets.QTableWidgetItem("[" + i + "]")
            item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            font = QtGui.QFont()
            font.setBold(True)
            font.setWeight(75)
            item.setFont(font)
            item.setForeground(QtGui.QBrush(QtGui.QColor(0, 0, 0)))
            if i in self.newKeys:
                item.setBackground(QtGui.QBrush(QtGui.QColor(0, 255, 0)))
            self.wgProfile.qtable_conf.setVerticalHeaderItem(q, item)
            item = QtWidgets.QTableWidgetItem(" ")
            item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.wgProfile.qtable_conf.setItem(q, 0, item)
            q = q + 1
            for k in self.profile[i]:
                item = QtWidgets.QTableWidgetItem(k)
                item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                item.setForeground(QtGui.QBrush(QtGui.QColor(0, 0, 0)))
                if (i+","+k) in self.newKeys:
                    item.setBackground(QtGui.QBrush(QtGui.QColor(0, 255, 0)))
                self.wgProfile.qtable_conf.setVerticalHeaderItem(q, item)
                item = QtWidgets.QTableWidgetItem(str(self.profile[i][k]))
                item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                item.setForeground(QtGui.QBrush(QtGui.QColor(0, 0, 0)))
                if (i+","+k) in self.errorKeys:
                    item.setBackground(QtGui.QBrush(QtGui.QColor(255, 0, 0)))
                self.wgProfile.qtable_conf.setItem(q, 0, item)
                q = q + 1
            item = QtWidgets.QTableWidgetItem(" ")
            item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.wgProfile.qtable_conf.setVerticalHeaderItem(q, item)
            item = QtWidgets.QTableWidgetItem(" ")
            item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.wgProfile.qtable_conf.setItem(q, 0, item)
            q = q + 1

        self.wgProfile.qtable_conf.horizontalHeader().setStretchLastSection(True)
        self.wgProfile.qtable_conf.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wgProfile.qtable_conf.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wgProfile.qtable_conf.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.wgProfile.qtable_conf.setGeometry(QtCore.QRect(30, 140, 741, min((20 + total_rows * 30), 700)))

    def editValue(self, row, col):
        # Base keys cannot be edited
        if row > 4:
            key = self.wgProfile.qtable_conf.verticalHeaderItem(row)
            if key is not None:
                if not key.text() == " " and not "[" in key.text():
                    self.wgProfile.qline_row.setText(str(row))
                    self.wgProfile.qline_col.setText(str(col))
                    self.wgProfile.qline_edit_key.setText(key.text())
                    for s in self.jprofile.keys():
                        #print(self.jprofile[s].keys())
                        if key.text() in self.jprofile[s].keys():
                            self.wgProfile.qlabel_type.setText(str(self.jprofile[s][key.text()]['type']))
                            self.wgProfile.qlabel_desc.setText(str(self.jprofile[s][key.text()]['desc']))
                            break
                    NewIndex = self.wgProfile.qtable_conf.currentIndex().siblingAtColumn(0)
                    self.wgProfile.qline_edit_value.setText(NewIndex.data())
                    item = self.wgProfile.qtable_conf.item(row, col)
                    if item:
                        self.wgProfile.qline_edit_newvalue.setText(item.text())
                        # print(row, col, item.text())

    def readTableProfile(self):
        profile = {}
        section = ''
        for r in range(self.wgProfile.qtable_conf.rowCount()):
            key = self.wgProfile.qtable_conf.verticalHeaderItem(r)
            if key is not None:
                if not key.text() == " ":
                    if "[" in key.text():
                        section = key.text()[1:-1]
                        profile[section] = {}
                    else:
                        profile[section][key.text()] = self.wgProfile.qtable_conf.item(r, 0).text()
        return profile

    def updateProfileCombo(self, current):
        profiles = []
        for d in os.listdir(self.profile['Base']['path']):
            if os.path.exists(self.profile['Base']['path'] + d + "/" + self.profile['Base']['app'].lower() + ".ini"):
                profiles += [d]
        if profiles:
            self.wgProfile.qcombo_profile.clear()
            for n, p in enumerate(profiles):
                self.wgProfile.qcombo_profile.addItem(p)
                if current == p:
                    self.wgProfile.qcombo_profile.setCurrentIndex(n)

    def browse(self):
        if 'file' in self.wgProfile.qlabel_type.text():
            fd = QtWidgets.QFileDialog()
            fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
            options = fd.options()
            base_path = self.wgProfile.qline_edit_value.text()
            base_path = base_path[:base_path.rfind("/")]
            result = fd.getOpenFileName(caption="Select a Station Config File...",
                                        directory=base_path,
                                        options=options)[0]
            self.wgProfile.qline_edit_newvalue.setText(result)
        if 'path' in self.wgProfile.qlabel_type.text():
            fd = QtWidgets.QFileDialog()
            fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
            fd.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
            options = fd.options()
            base_path = self.wgProfile.qline_edit_value.text()
            base_path = base_path[:base_path.rfind("/")]
            result = fd.getExistingDirectory(caption="Select a Station Config File...",
                                             directory=base_path,
                                             options=options)
            self.wgProfile.qline_edit_newvalue.setText(result)

    def clear(self):
        self.wgProfile.qline_edit_key.setText("")
        self.wgProfile.qline_edit_value.setText("")
        self.wgProfile.qline_edit_newvalue.setText("")
        self.wgProfile.qline_row.setText("")
        self.wgProfile.qline_col.setText("")

    def apply(self):
        # TODO: add here the check
        item = QtWidgets.QTableWidgetItem(self.wgProfile.qline_edit_newvalue.text())
        item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        item.setFlags(QtCore.Qt.ItemIsEnabled)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        self.wgProfile.qtable_conf.setItem(int(self.wgProfile.qline_row.text()),
                                           int(self.wgProfile.qline_col.text()),
                                           item)


if __name__ == "__main__":
    from optparse import OptionParser

    parser = OptionParser(usage="usage: %skalab_base [options]")
    parser.add_option("--app", action="store", dest="app",
                      type="str", default="Test", help="Application Name")
    parser.add_option("--profile", action="store", dest="profile",
                      type="str", default="Default", help="Profile Name")
    parser.add_option("--path", action="store", dest="path",
                      type="str", default=default_app_dir, help="Profile Path")
    (opt, args) = parser.parse_args(sys.argv[1:])

    app = QtWidgets.QApplication(sys.argv)
    wiz = ConfWizard(App=opt.app, Profile=opt.profile, Path=opt.path, msg="Step 1/1")

    wiz.wg.show()
    wiz.wg.raise_()
    sys.exit(app.exec_())
