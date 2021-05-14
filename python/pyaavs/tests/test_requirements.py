# Import DAQ and Access Layer libraries
# import pydaq.daq_receiver as daq
from pyaavs.tile import Tile


from datetime import datetime, timedelta
from sys import stdout
import numpy as np
import os.path
import logging
import socket
import random
import psutil
import math
import time


def get_eth_if_from_ip(ip):
    ip_address = socket.gethostbyname(ip)
    intf_dict = psutil.net_if_addrs()
    for intf in intf_dict.keys():
        if intf != 'lo':
            if intf_dict[intf][0][1] == ip_address:
                return intf
    return None


def get_eth_if_mtu(intf):
    intf_dict = psutil.net_if_stats()
    if intf in intf_dict.keys():
        mtu = intf_dict[intf][3]
        return int(mtu)
    return 0


def check_eth(station_config, data_type, mtu, logger=None):
    eth_if = ""
    if data_type == "csp":
        eth_if = get_eth_if_from_ip(station_config['network']['csp_ingest']['dst_ip'])
    elif data_type == "lmc":
        eth_if = get_eth_if_from_ip(station_config['network']['lmc']['lmc_ip'])
    elif data_type == "integrated":
        eth_if = get_eth_if_from_ip(station_config['network']['lmc']['integrated_data_ip'])
    if eth_if != station_config['eth_if']:
        if logger is not None:
            logger.error("Selected DAQ Ethernet Interface %s will not receive %s data packets, "
                         "they are routed to different IP address!" %
                         (station_config['eth_if'], data_type.upper()))
        return False
    if get_eth_if_mtu(eth_if) < mtu:
        if logger is not None:
            logger.error("Selected DAQ Ethernet Interface %s must have MTU larger than %i bytes!" %
                        (station_config['eth_if'], mtu))
        return False
    return True


def check_integrated_data_enabled(station, stage, logger):
    for fpga in ['fpga1', 'fpga2']:
        enabled = station["%s.lmc_integrated_gen.%s_enable" % (fpga, stage)]
        if any(enabled) != 1:
            if logger is not None:
                logger.error("Integrator stage %s is not enabled!" % stage)
            return False
    return True


def check_40g_test_enabled(station_config):
    if station_config['test_config']['gigabit_only']:
        return False
    else:
        return True