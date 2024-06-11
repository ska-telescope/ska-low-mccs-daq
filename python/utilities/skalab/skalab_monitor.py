"""

   The SKA in LAB MONITOR Project 

   Easy and Quick Access Monitor and Control the SKA-LFAA Devices in Lab based on aavs-system

   Supported Devices are:

      - TPM_1_2 and TPM_1_6
      - Subrack with WebServer API

"""

__copyright__ = "Copyright 2023, Osservatorio Astrofisico di Arcetri, INAF, Italy"
__author__ = "Simone Chiarucci"
__credits__ = ["Simone Chiarucci & Andrea MAttana"]
__license__ = "BSD3"
__version__ = "1.0"
__release__ = "2023-10-20"
__maintainer__ = "Simone Chiarucci"

import sys
import logging

from pyaavs import station
from PyQt5 import QtWidgets
from monitor_subrack import MonitorSubrack
from monitor_station_init import * 

if __name__ == "__main__":
    """
    Main script to launch the SKALAB MONITOR application.

    Parses command-line arguments to specify the log path, monitor profile, and auto-connect option.
    Initializes the monitor application, sets up the GUI window, and connects relevant signals.
    Exits the application when the GUI is closed.

    Usage:
    python script_name.py [-lp --logpath] [-p --profile] [--connect]

    Options:
    -lp, --logpath   : Monitor log folder path to load (default: "")
    -p, --profile    : Monitor profile to load (default: "Default")
    --connect        : Enable auto-connect (default: False)
    """
    import argparse
    from pathlib import Path

    default_profile = "Default"
    profile_filename = "monitor.ini"
    default_app_dir = str(Path.home()) + "/.skalab/"
    
    parser = argparse.ArgumentParser(prog = "skalab_monitor")
    parser.add_argument(
        "-lp",
        "--logpath", 
        action="store", 
        type=str, 
        nargs = '?',
        default="",
        dest = "logpath",
        help="Monitor log folder path to load",
        )
    parser.add_argument(
        "-p",
        "--profile", 
        action="store", 
        type=str, 
        nargs = '?',
        default="Default",
        dest = "profile",
        help="Monitor Profile to load",
        )
    parser.add_argument("--connect", action="store_true", dest="connect",
                      default=False, help="Enable auto connect [Default Disabled]")

    opt = parser.parse_args()

    fullpath = default_app_dir + opt.profile + "/" + profile_filename

    monitor_logger = logging.getLogger(__name__)
    app = QtWidgets.QApplication(sys.argv)
    print("\nStarting SKALAB MONITOR...\n")
    window = MonitorSubrack(uiFile="Gui/skalab_monitor.ui",
                                profile=opt.profile,swpath=default_app_dir)
    window.setFixedSize(1320,920)
    window.showFullScreen
    window.dst_port = station.configuration['network']['lmc']['lmc_port']
    window.lmc_ip = station.configuration['network']['lmc']['lmc_ip']
    window.cpld_port = station.configuration['network']['lmc']['tpm_cpld_port']
    window.signalTlm.connect(window.updateTpmStatus)
    window.signal_to_monitor.connect(window.readwriteSubrackAttribute)
    window.signal_to_monitor_for_tpm.connect(window.tpmStatusChanged)
    window.signal_update_tpm_attribute.connect(window.unfoldTpmAttribute)
    window.signal_station_init.connect(window.do_station_init)
    window.connect()
    sys.exit(app.exec_())