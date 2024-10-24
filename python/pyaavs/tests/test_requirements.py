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
                return intf.split(":")[0]  # remove virtual IF :x identifier
    return None


def get_eth_if_mtu(intf):
    intf_dict = psutil.net_if_stats()
    if intf in intf_dict.keys():
        mtu = intf_dict[intf][3]
        return int(mtu)
    return 0


def check_eth(station_config, data_type, mtu, logger=None):
    if data_type == "csp":
        eth_ip = station_config['network']['csp_ingest']['dst_ip']
    elif data_type == "lmc":
        eth_ip = station_config['network']['lmc']['lmc_ip']
    elif data_type == "integrated":
        eth_ip = station_config['network']['lmc']['integrated_data_ip']
    eth_if = get_eth_if_from_ip(eth_ip)
    if eth_if is None:
        logger.error(f"Unable to match {data_type} destination IP address {eth_ip} to an ethernet interface "
                      "on this machine. Check your configuration!")
        return False
    if eth_if != station_config['eth_if'][data_type]:
        if logger is not None:
            logger.error(f"Selected DAQ Ethernet Interface {station_config['eth_if'][data_type]} will not "
                         f"receive {data_type.upper()} data packets, they are routed to different IP address!")
        return False
    if get_eth_if_mtu(eth_if) < mtu:
        if logger is not None:
            logger.error(f"Selected DAQ Ethernet Interface {eth_if} must have MTU larger than {mtu} bytes!")
        return False
    return True


def check_integrated_data_enabled(station, stage, logger=None, tpm_id=None):
    for fpga in ['fpga1', 'fpga2']:
        enabled = station["%s.lmc_integrated_gen.%s_enable" % (fpga, stage)]
        if tpm_id is None:
            enabled_check = enabled
        elif 0 <= tpm_id <= len(station.tiles) - 1:
            enabled_check = [enabled[tpm_id]]
        else:
            if logger is not None:
                logger.error("TPM Id %i does not belong to station!" % tpm_id)
            return False

        if any(enabled_check) != 1:
            if logger is not None:
                logger.error("Integrator stage %s is not enabled!" % stage)
            return False

    return True


def check_40g_test_enabled(station_config):
    if station_config['test_config']['gigabit_only']:
        return False
    else:
        return True
