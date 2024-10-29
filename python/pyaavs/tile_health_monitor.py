# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
#
# Distributed under the terms of the GPL license.
# See LICENSE.txt for more info.
"""
Hardware functions for monitoring of TPM hardware health status.

This depends heavily on the
pyfabil low level software and specific hardware module plugins.
"""

import time
from pyfabil.base.definitions import LibraryError, BoardError
from copy import copy
from copy import deepcopy
from functools import reduce
import operator
from functools import partial
from pyaavs.tpm_1_6_monitoring_point_lookup import load_tpm_1_6_lookup
from pyaavs.tpm_1_2_monitoring_point_lookup import load_tpm_1_2_lookup


def health_monitoring_compatible(func):
    """
    Decorator method to check if provided firmware supports TPM health monitoring.
    Achieved by attempting to access a register which was added for TPM health monitoring.
    Bitstreams generated prior to ~03/2023 will not support TPM health monitoring.
    """
    def inner_func(self, *args, **kwargs):
        try:
            self['fpga1.pps_manager.pps_errors']
        except Exception as e:  # noqa: F841
            raise LibraryError(f"TPM Health Monitoring not supported by FPGA firmware!")
        return func(self, *args, **kwargs)
    return inner_func


class TileHealthMonitor():
    """
    Tile Health Monitor Mixin Class, must be inherited by Tile Class
    """

    def init_health_monitoring(self):
        """
        Method to load monitoring point lookup dict into attribute.

        TPM monitoring point format and lookup loaded from:
        tpm_1_2_monitoring_point_lookup.py
        tpm_1_6_monitoring_point_lookup.py
        """
        self.monitoring_point_lookup_dict = load_tpm_1_2_lookup(self) if  self.tpm_version() == "tpm_v1_2" else load_tpm_1_6_lookup(self)
        return

    def enable_health_monitoring(self):
        communication_status = self.check_communication()
        if not all(communication_status.values()):
            raise BoardError(f"Board communication error, unable to enable health monitoring. Check communication status and try again.")
        # For use with get_health_status and clear_health_status
        # Enable anything that requires an enable
        self.enable_clock_monitoring()
        return

    def all_monitoring_points(self):
        """
        Returns a list of all monitoring points by finding all leaf nodes
        in the lookup dict that have a corresponding method field.

        The monitoring points returned are strings produced from '.' delimited 
        keys. For example:
        'voltages.5V0'
        'io.udp_interface.crc_error_count.FPGA0'

        More info at https://confluence.skatelescope.org/x/nDhED

        :return: list of monitoring points
        :rtype: list of strings
        """
        def find_leaf_dict_recursive(health_dict, key_list=[], output_list=[]):
            for name, value in health_dict.items():
                key_list.append(name)
                if not isinstance(value, dict):
                    output_list.append('.'.join(key_list))
                    key_list.pop()
                else:
                    find_leaf_dict_recursive(value, key_list, output_list)
            if key_list:
                key_list.pop()
            return output_list
            
        # Find leaves of nested dict
        dict_leaf_list = find_leaf_dict_recursive(self.monitoring_point_lookup_dict)
        # Keep only points ending in .method, then remove the .method
        monitoring_point_list = []
        for point in dict_leaf_list:
            if point.endswith('.method'):
                monitoring_point_list.append(point[:-7])
        return monitoring_point_list

    def all_monitoring_categories(self):
        """
        Returns a list of all monitoring point 'categories'.
        Here categories is a super-set of monitoring points and is 
        the full list of accepted strings to set_monitoring_point_attr. 
        For example, these monitoring points:
        voltages.5V0
        io.udp_interface.crc_error_count.FPGA0

        would have these associated categories:
        'voltages'
        'voltages.5V0'
        'io'
        'io.udp_interface'
        'io.udp_interface.crc_error_count'
        'io.udp_interface.crc_error_count.FPGA0'

        More info at https://confluence.skatelescope.org/x/nDhED

        :return: list of categories
        :rtype: list of strings
        """
        all_monitoring_points = self.all_monitoring_points()
        categories = set()
        for monitroing_point in all_monitoring_points:
            parts = monitroing_point.split('.')
            for i in range(len(parts)):
                categories.add('.'.join(parts[:i+1]))
        categories_list = list(categories)
        categories_list.sort()
        return categories_list

    def set_monitoring_point_attr(self, path, override=True, **kwargs):
        """
        Specify attributes for a monitoring point or subset of monitoring points. 
        Specified by path, a string name produced from '.' delimited keys of the lookup dict.
        All available options returned from all_monitoring_categories().

        See https://confluence.skatelescope.org/x/nDhED for example usage.

        :param path: Monitoring point path (i.e any of:'io.udp_interface.crc_error_count', 'io.udp_interface', 'timing', 'io')
        :type path: str

        :param override: Overrides the specified attribute if true, if False appends
        :type override: bool

        :param **kwargs: key word args (i.e rate='fast' or rate=8, group='my_group' or group=['my_group1', 'my_group2'])
        :type kwargs: values can be int,str,bool,float etc. or list of these. Tuples not supported
        """
        if path not in self.all_monitoring_categories():
            raise LibraryError(f"No monitoring point paths matching: {path}\nUse:\nall_monitoring_points()\nall_monitoring_categories()\nto see available options.")
        for monitoring_point in self.all_monitoring_points():
              if monitoring_point.startswith(path):
                lookup = monitoring_point.split('.')
                lookup_entry = self._parse_dict_by_path(self.monitoring_point_lookup_dict, lookup)
                for key, value in kwargs.items():
                    if not isinstance(value, list):
                        value = [value]
                    if override or key not in lookup_entry:
                        self.logger.info(f"Setting {key} for {monitoring_point} to {', '.join(value)}.")
                        lookup_entry[key] = copy(value)
                    else:
                        self.logger.info(f"Appending {key} for {monitoring_point} with {', '.join(value)}.")
                        lookup_entry[key].extend(value)
                        lookup_entry[key] = copy(list(set(lookup_entry[key])))  # remove duplicates from list by converting to set and back
                        self.logger.info(f"{key} for {monitoring_point} now {lookup_entry[key]}.")
        return

    def _parse_dict_by_path(self, dictionary, path_list):
        """
        General purpose method to parse a nested dictory by a list of keys.

        Example:
        test_dict = {'parent': {'child1': 10, 'child2':12}, 'parent2': {'child3': 14}}
        self._parse_dict_by_path(test_dict, ['parent', 'child2']) would return 12
        self._parse_dict_by_path(test_dict, ['parent2', 'child3']) would return 14
        self._parse_dict_by_path(test_dict, ['parent']) would return {'child1': 10, 'child2':12}

        :param dictionary: Input nested dictionary
        :type dictionary: dict

        :param path_list: List of dictionary keys, from top to bottom
        :type path_list: list

        :return: value
        """
        return reduce(operator.getitem, path_list, dictionary)

    def _create_nested_dict(self, key_list, value, nested_dict={}):
        """
        General purpose method to append to a nested dictionary based on a provided
        list of keys and a value.
        If nested_dict is not specified a new dictionary is created. Subsequent calls
        with the same nested_dict provided will append.
        Used to recreate a nested dictionary hierarchy from scratch.

        NOTE: nested_dict is not copied so due to Python dictionaries being mutable,
        the returned nested_dict is optional, required for creation of new dictionaries.

        :param key_list: List of dictionary keys, from top to bottom
        :type key_list: list

        :param value: Value to be stored at path specified by key_list
        :type value: anything

        :param nested_dict: Input nested dictionary
        :type nested_dict: dict

        :return: nested_dict
        :rtype: dict
        """
        current_dict = nested_dict
        for key in key_list[:-1]:
            if key not in current_dict:
                current_dict[key] = {}
            current_dict = current_dict[key]
        current_dict[key_list[-1]] = value
        return nested_dict

    def _kwargs_handler(self, kwargs):
        """
        For use with get_health_status method.
        Filter all monitoring points to a subset based on monitoring 
        point attr match to kwargs in monitoring point lookup dict.

        NOTE: when multiple args specified, all must match

        :param kwargs: dictionary of kwargs
        :type kwargs: dict

        :return: monitoring point list
        :rtype: list
        """
        if not kwargs:
            return self.all_monitoring_points()
        # get list of monitoring points to be polled based on kwargs
        mon_point_list = []
        for monitoring_point in self.all_monitoring_points():
            lookup = monitoring_point.split('.')
            lookup_entry = self._parse_dict_by_path(self.monitoring_point_lookup_dict, lookup)
            keep = 0
            for key, val in kwargs.items():
                if val in lookup_entry.get(key, []):
                    keep +=1
            if keep == len(kwargs):
                mon_point_list.append(monitoring_point)
        return mon_point_list

    def get_health_status(self, **kwargs):
        """
        Returns the current value of TPM monitoring points with the 
        specified attributes as set in the method set_monitoring_point_attr.
        If no arguments given, current value of all monitoring points is returned.

        For example:
        If configured with:
        tile.set_monitoring_point_attr('io.udp_interface', my_category='yes', my_other_category=87)

        Subsequent calls to:
        tile.get_health_status(my_category='yes', my_other_category=87)

        would return only the health status for:
        io.udp_interface.arp
        io.udp_interface.status
        io.udp_interface.crc_error_count.FPGA0
        io.udp_interface.crc_error_count.FPGA1
        io.udp_interface.bip_error_count.FPGA0
        io.udp_interface.bip_error_count.FPGA1
        io.udp_interface.decode_error_count.FPGA0
        io.udp_interface.decode_error_count.FPGA1
        io.udp_interface.linkup_loss_count.FPGA0
        io.udp_interface.linkup_loss_count.FPGA1

        A group attribute is provided by default, see tpm_1_X_monitoring_point_lookup.
        This can be used like the below example:
        tile.get_health_status(group='temperatures')
        tile.get_health_status(group='udp_interface')
        tile.get_health_status(group='io')

        Full documentation on usage available at https://confluence.skatelescope.org/x/nDhED
        """
        fpga_communication = True
        communication_status = self.check_communication()
        if not communication_status["CPLD"]:
            raise BoardError(f"Board communication error, unable to get health status. Check communication status and try again.")
        if not (communication_status["FPGA0"] and communication_status["FPGA1"]):
            fpga_communication = False
            self.logger.warning(f"Not able to communicate with one of more FPGAs. Reduced health status will be returned.")
        health_status = {}
        mon_point_list = self._kwargs_handler(kwargs)
        clear_method_list = []
        for monitoring_point in mon_point_list:
            lookup = monitoring_point.split('.')
            lookup_entry = self._parse_dict_by_path(self.monitoring_point_lookup_dict, lookup)
            # call method stored in lookup entry
            if fpga_communication or lookup_entry.get("CPLD-only"):
                value = lookup_entry["method"]()
                # Resolve nested values with only one value i.e
                # get_voltage("voltage_name") returns {"voltage_name": voltage}
                # get_clock_manager_status(fpga_id, name) returns {"FPGAid": {"name": status}}
                while True:
                    if not isinstance(value, dict):
                        break
                    if len(value) != 1:
                        break
                    value = list(value.values())[0]
                # Create dictionary of monitoring points in same format as lookup
                health_status = self._create_nested_dict(lookup, value, health_status)

                # Clear select health_status point if defined.
                if "clear_method" in lookup_entry:
                    clear_method_list.append(lookup_entry["clear_method"])

        for clear_method in clear_method_list:
            try:
                clear_method()
            except Exception as e:
                self.logger.error(f"Unable to clear monitoring_point {monitoring_point} "
                                  "Exception : {e}")

        return health_status
    
    def clear_health_status(self, group=None):
        communication_status = self.check_communication()
        if communication_status['CPLD']:
            if group is None or group  == "pll":
                self.clear_ad9528_pll_status()
        if communication_status["FPGA0"] and communication_status["FPGA1"]:
            if group is None:
                self.clear_clock_status(fpga_id=None, clock_name=None)
                self.clear_clock_manager_status(fpga_id=None, name=None)
                self.clear_pps_status(fpga_id=None)
                self.clear_jesd_error_counters(fpga_id=None)
                self.clear_ddr_reset_counter(fpga_id=None)
                self.clear_f2f_pll_lock_loss_counter(core_id=None)
                self.clear_udp_status(fpga_id=None)
                self.clear_tile_beamformer_status(fpga_id=None)
                self.clear_station_beamformer_status(fpga_id=None)
                self.clear_data_router_status(fpga_id=None)
            elif group == "clocks":
                self.clear_clock_status(fpga_id=None, clock_name=None)
            elif group == "clock_managers":
                self.clear_clock_manager_status(fpga_id=None, name=None)
            elif group == "pps":
                    self.clear_pps_status(fpga_id=None)
            elif group == "jesd_interface":
                self.clear_jesd_error_counters(fpga_id=None)
            elif group == "ddr_interface":
                self.clear_ddr_reset_counter(fpga_id=None)
            elif group == "f2f_interface":
                self.clear_f2f_pll_lock_loss_counter(core_id=None)
            elif group == "udp_interface":
                self.clear_udp_status(fpga_id=None)
            elif group == "tile_beamf":
                self.clear_tile_beamformer_status(fpga_id=None)
            elif group == "station_beamf": 
                self.clear_station_beamformer_status(fpga_id=None)
            elif group == "data_router":
                self.clear_data_router_status(fpga_id=None)

    def fpga_gen(self, fpga_id):
        return range(len(self.tpm.tpm_test_firmware)) if fpga_id is None else [fpga_id]

    def get_fpga_temperature(self, fpga_id=None):
        """
        Get FPGA temperature.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: FPGA temperature
        :rtype: dict
        """
        temperature_dict = {}
        for fpga in self.fpga_gen(fpga_id):
            if self.is_programmed():
                temperature_dict[f'FPGA{fpga}'] = round(self.tpm.tpm_sysmon[fpga].get_fpga_temperature(), 2)
            else:
                temperature_dict[f'FPGA{fpga}'] = 0
        return temperature_dict

    def check_global_status_alarms(self):
        """
        Wrapper for tpm get_global_status_alarms method
        Returns none if tpm version is 1.2

        :return: alarm status dict
        :rtype: dict
        """
        return None if self.tpm_version() == "tpm_v1_2" else self.tpm.get_global_status_alarms()
        
    def get_available_voltages(self, fpga_id=None):
        """
        Get list of available voltage measurements for TPM.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: TPM voltage names
        :rtype: list
        """
        available_voltages = []
        # LASC Plugin TPM 1.2
        if self.tpm_version() == "tpm_v1_2":
            available_voltages.extend(self.tpm.tpm_lasc[0].get_available_voltages())
        # MCU Plugin TPM 1.6
        else:
            available_voltages.extend(self.tpm.tpm_monitor[0].get_available_voltages())
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            available_voltages.extend(self.tpm.tpm_sysmon[fpga].get_available_voltages())
        return available_voltages


    def get_tpm_temperature_thresholds(self):
        """
        Return a dictionary of temperature thresholds.

        return structure looks like:
        >> {
            "board_warning_threshold": (min, max),
            "board_alarm_threshold"  : (min, max),
            "fpga1_warning_threshold": (min, max),
            "fpga1_alarm_threshold": (min, max),
            "fpga2_warning_threshold": (min, max),
            "fpga2_alarm_threshold": (min, max),
        }

        :return: A dictionary containing the temperature thresholds.
        :rtype: dict
        """
        return {
            "board_warning_threshold": self.tpm.tpm_monitor[0].get_board_warn_temp_thresholds(),
            "board_alarm_threshold"  : self.tpm.tpm_monitor[0].get_board_alm_temp_thresholds(),
            "fpga1_warning_threshold": self.tpm.tpm_monitor[0].get_fpga_warn_temp_thresholds(fpga_id=0),
            "fpga1_alarm_threshold": self.tpm.tpm_monitor[0].get_fpga_alm_temp_thresholds(fpga_id=0),
            "fpga2_warning_threshold": self.tpm.tpm_monitor[0].get_fpga_warn_temp_thresholds(fpga_id=1),
            "fpga2_alarm_threshold": self.tpm.tpm_monitor[0].get_fpga_alm_temp_thresholds(fpga_id=1),
        }
    
    def set_tpm_temperature_thresholds(
        self,
        board_alarm_threshold=None,
        fpga1_alarm_threshold=None,
        fpga2_alarm_threshold=None,
    ) -> None:
        """
        Set the temperature thresholds.

        NOTE: Warning this method can configure the shutdown temperature of 
        components and must be used with care. This method is capped to a minimum 
        of 20 and maximum of 50 (unit: Degree Celsius). And is ONLY supported in tpm1_6.

        :param board_alarm_threshold: A tuple containing the minimum and 
            maximum alarm thresholds for the board (unit: Degree Celsius)
        :param fpga1_alarm_threshold: A tuple containing the minimum and 
            maximum alarm thresholds for the fpga1 (unit: Degree Celsius)
        :param fpga2_alarm_threshold: A tuple containing the minimum and 
            maximum alarm thresholds for the fpga2 (unit: Degree Celsius)

        :raises ValueError: If attempting to set a value outside the specified
            limit 20-50.
        """
        if self.tpm_version() != "tpm_v1_6":
            self.logger.info("this method only supports tpm_v1_6.")
            return

        def _is_in_range_20_50(value):
            """
            Return True if value is larger than 20 and less than 50.
            
            :param value: value under test
            """
            min_settable = 20
            max_settable = 50
            if min_settable <= value <= max_settable:
                return True
            return False

        # Check all values are in range
        if board_alarm_threshold is not None:
            if not (_is_in_range_20_50(board_alarm_threshold[0]) and _is_in_range_20_50(board_alarm_threshold[1])):
                raise ValueError(f"{board_alarm_threshold=} not in capped range 20-50. Doing nothing")
        if fpga1_alarm_threshold is not None:
            if not (_is_in_range_20_50(fpga1_alarm_threshold[0]) and _is_in_range_20_50(fpga1_alarm_threshold[1])):
                raise ValueError(f"{fpga1_alarm_threshold=} not in capped range 20-50. Doing nothing")
        if fpga2_alarm_threshold is not None:
            if not (_is_in_range_20_50(fpga2_alarm_threshold[0]) and _is_in_range_20_50(fpga2_alarm_threshold[1])):
                raise ValueError(f"{fpga2_alarm_threshold=} not in capped range 20-50. Doing nothing")
        
        if board_alarm_threshold is not None:
            self.tpm.tpm_monitor[0].set_board_alm_temp_thresholds(board_alarm_threshold[0], board_alarm_threshold[1])
        if fpga1_alarm_threshold is not None:
            self.tpm.tpm_monitor[0].set_fpgas_alm_temp_thresholds(fpga1_alarm_threshold[0], fpga1_alarm_threshold[1], fpga_id=0)
        if fpga2_alarm_threshold is not None:
            self.tpm.tpm_monitor[0].set_fpgas_alm_temp_thresholds(fpga2_alarm_threshold[0], fpga2_alarm_threshold[1], fpga_id=1)


    def get_voltage(self, fpga_id=None, voltage_name=None):
        """
        Get voltage measurements for TPM.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param voltage_name: Specify name of voltage, None for all voltages
        :type voltage_name: string

        :return: TPM voltages
        :rtype: dict
        """
        voltage_dict = {}
        # LASC Plugin TPM 1.2
        if self.tpm_version() == "tpm_v1_2":
            voltage_dict.update(self.tpm.tpm_lasc[0].get_voltage(voltage_name))
        # MCU Plugin TPM 1.6
        else:
            voltage_dict.update(self.tpm.tpm_monitor[0].get_voltage(voltage_name))
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            voltage_dict.update(self.tpm.tpm_sysmon[fpga].get_voltage(voltage_name))
        # if name specified and results are empty
        if voltage_name is not None and not voltage_dict:
            raise LibraryError(f"No voltage named '{voltage_name}' \n Options are {', '.join(self.get_available_voltages(fpga_id))} (case sensitive)")
        return voltage_dict

    def get_available_currents(self, fpga_id=None):
        """
        Get list of available current measurements for TPM.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: TPM current names
        :rtype: list
        """
        available_currents = []
        # LASC Plugin TPM 1.2
        if self.tpm_version() == "tpm_v1_2":
            available_currents.extend(self.tpm.tpm_lasc[0].get_available_currents())
        # MCU Plugin TPM 1.6
        else:
            available_currents.extend(self.tpm.tpm_monitor[0].get_available_currents())
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            available_currents.extend(self.tpm.tpm_sysmon[fpga].get_available_currents())
        return available_currents

    def get_current(self, fpga_id=None, current_name=None):
        """
        Get current measurements for TPM.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param current_name: Specify name of current, None for all currents
        :type current_name: string

        :return: TPM currents
        :rtype: dict
        """
        current_dict = {}
        # LASC Plugin TPM 1.2
        if self.tpm_version() == "tpm_v1_2":
            current_dict.update(self.tpm.tpm_lasc[0].get_current(current_name))
        # MCU Plugin TPM 1.6
        else:
            current_dict.update(self.tpm.tpm_monitor[0].get_current(current_name))
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            current_dict.update(self.tpm.tpm_sysmon[fpga].get_current(current_name))
        # if name specified and results are empty
        if current_name is not None and not current_dict:
            raise LibraryError(f"No current named '{current_name}' \n Options are {', '.join(self.get_available_currents(fpga_id))} (case sensitive)")
        return current_dict

    def check_adc_pll_status(self, adc_id=None):
        """
        Status of ADC PLL.

        This method returns a tuple, True if the lock of
        the PLL is up and True if no loss of PLL 
        lock has been observed respectively.

        NOTE: AD9680 used in TPM 1.2 does not support loss of lock
        bit, only current lock status. Will return None.

        A dictionary is returned with an entry for each ADC.

        :return: (True, True) if lock is up and no loss of lock
        :rtype dict of tuple
        """
        adcs = range(16) if adc_id is None else [adc_id]
        status_dict = {}
        for adc in adcs:
            reg = self[f'adc{adc}', 0x056F]
            lock_is_up = reg & 0x80 > 0
            no_loss_of_lock = None if self.tpm_version() == "tpm_v1_2" else reg & 0x8 == 0
            status_dict[f'ADC{adc}'] = (lock_is_up, no_loss_of_lock)
        return status_dict
    
    def check_adc_sysref_setup_and_hold(self, adc_id=None, show_info=True):
        """
        Status of the ADC status and hold monitor.
        Returns True if no setup or hold error for a given ADC.
        Returns a dictionary of bool, one for each ADC.

        If show info enabled then desciptions from AD9695/AD9680 
        documentation are also displayed to explain the value of 
        the setup and hold monitor.

        :param adc_id: Specify which ADC, 0-15, None for all ADCs
        :type adc_id: integer

        :param show_info: displays info messages about current setup/hold
        :type show_info: bool

        :return: True if timing requirements OK
        :rtype dict of bool
        """
        case_dict = { 
            'case1': {'hold': [0x0], 'setup': [0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7], 'status': False, 'msg': "Possible setup error.The smaller this number, the smaller the setup margin."},
            'case2': {'hold': [0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8], 'setup': [0x8], 'status': True, 'msg': "No setup or hold error (best hold margin)."},
            'case3': {'hold': [0x8], 'setup': [0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF], 'status': True, 'msg': "No setup or hold error (best setup and hold margin)."},
            'case4': {'hold': [0x8], 'setup': [0x0], 'status': True, 'msg': "No setup or hold error (best setup margin)."},
            'case5': {'hold': [0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF], 'setup': [0x0], 'status': False, 'msg': "Possible hold error. The larger this number the smaller the hold margin."},
            'case6': {'hold': [0x0], 'setup': [0x0], 'status': False, 'msg': "Possible setup or hold error."}
        }
        adcs = range(16) if adc_id is None else [adc_id]
        status_dict = {}
        for adc in adcs:
            reg = self[f'adc{adc}', 0x0128]
            hold = (reg & 0xF0) >> 4
            setup = reg & 0x0F
            for case in case_dict.values():
                if hold in case['hold'] and setup in case['setup']:
                    if show_info:
                        self.logger.info(f"ADC{adc} {case['msg']} Setup: {hex(setup)}, Hold {hex(hold)}.")
                    status_dict[f'ADC{adc}'] = case['status']
                    break
            else:
                if show_info:
                    self.logger.error(f"ADC{adc} Invalid Setup and Hold values. Setup: {hex(setup)}, Hold {hex(hold)}.")
                status_dict[f'ADC{adc}'] = False
        return status_dict

    def check_adc_sysref_counter(self, adc_id=None, show_info=True):
        """
        Checks ADC sysref counter is incrementing.
        Sysref counter increments for each sysref event and
        overflows at 255 ~ every 3.28ms.

        Returns True if counter is incrementing for a given ADC.
        Returns a dictionary of bool, one for each ADC.

        Will retry for 1 second until two readings can be taken in 
        under 3ms to guarantee no overflow.

        For debugging, if show info is enabled then each counter 
        reading will be displayed along with the elapsed time.

        :param adc_id: Specify which ADC, 0-15, None for all ADCs
        :type adc_id: integer

        :param show_info: displays info messages
        :type show_info: bool

        :return: True if sysref counter incrementing
        :rtype dict of bool
        """
        adcs = range(16) if adc_id is None else [adc_id]
        status_dict = {}
        for adc in adcs:
            timeout = time.time() + 1 # 1 second timeout
            while True:
                start_time = time.perf_counter()
                read1 = self[f'adc{adc}', 0x012A]
                read2 = self[f'adc{adc}', 0x012A]
                end_time = time.perf_counter()
                if show_info:
                    self.logger.info(f"read1: {read1}")
                    self.logger.info(f"read2: {read2}")
                    self.logger.info(f"{(end_time - start_time) * 1000} ms")
                if end_time - start_time < 0.003:
                    break
                if time.time() > timeout:
                    raise BoardError(f"Timed out trying to read ADC{adc} SYSREF counter - 0x012A twice in under 3 ms.")
            status_dict[f'ADC{adc}'] = read1 != read2
        return status_dict
    
    def check_ad9528_pll_status(self):
        """
        Status of TPM AD9528 PLL chip

        This method returns lock status True if both PLLs
        in the AD9528 are locked. The lock loss counter 
        increments for a loss of lock event on either PLL.

        :return: current lock status and lock loss counter value
        :rtype tuple
        """
        pll_status = self.tpm.tpm_pll[0].get_pll_status()
        loss_of_lock = self.tpm.tpm_pll[0].get_pll_loss_of_lock()
        # The above calls will return None if CPLD firmware does 
        # not support PLL status
        if pll_status is None:
            # if unsuccessful try alternative i2c method
            # should only be needed for TPM 1.2 on old CPLD firmware
            pll_status = self['pll', 0x508]
        lock = pll_status & 0x3 == 0x3
        return lock, loss_of_lock

    def clear_ad9528_pll_status(self):
        """
        Resets the value in the AD9528 PLL lock loss counter to 0.
        """
        self.tpm.tpm_pll[0].reset_pll_loss_of_lock()
        return

    def get_available_clocks_to_monitor(self):
        """
        :return: list of clock names available to be monitored
        :rtype list of string
        """
        if self.is_programmed():
            return self.tpm.tpm_clock_monitor[0].get_available_clocks_to_monitor()

    def enable_clock_monitoring(self, fpga_id=None, clock_name=None):
        """
        Enable clock monitoring of named TPM clocks
        Options 'jesd', 'ddr', 'udp'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only enable monitoring on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param clock_name: Specify name of clock or None for all clocks
        :type clock_name: string
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                    self.tpm.tpm_clock_monitor[fpga].enable_clock_monitoring(clock_name)
        return

    def disable_clock_monitoring(self, fpga_id=None, clock_name=None):
        """
        Disable clock monitoring of named TPM clocks
        Options 'jesd', 'ddr', 'udp'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only disable monitoring on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param clock_name: Specify name of clock or None for all clocks
        :type clock_name: string
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tpm.tpm_clock_monitor[fpga].disable_clock_monitoring(clock_name)
        return
    
    def check_clock_status(self, fpga_id=None, clock_name=None):
        """
        Check status of named TPM clocks
        Options 'jesd', 'ddr', 'udp'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only check status on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param clock_name: Specify name of clock or None for all clocks
        :type clock_name: string

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.is_programmed():
            result = {}
            for fpga in self.fpga_gen(fpga_id):
                result[f'FPGA{fpga}'] = self.tpm.tpm_clock_monitor[fpga].check_clock_status(clock_name)
            return result
        return
    
    def clear_clock_status(self, fpga_id=None, clock_name=None):
        """
        Clear status of named TPM clocks
        Used to Clear error flags in FPGA Firmware
        Options 'jesd', 'ddr', 'udp'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only clear status on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param clock_name: Specify name of clock or None for all clocks
        :type clock_name: string
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tpm.tpm_clock_monitor[fpga].clear_clock_status(clock_name)
        return    

    def check_clock_manager_status(self, fpga_id=None, name=None):
        """
        Check status of named TPM clock manager cores (MMCM Core).
        Reports the status of each MMCM lock and its lock loss counter.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param name: Specify name of clock manager (non case sensitive)
        :type name: string

        :return: Status and Counter values
        :rtype dict
        """
        status = {}
        for fpga in self.fpga_gen(fpga_id):
            status[f'FPGA{fpga}'] = self.tpm.tpm_clock_monitor[fpga].check_clock_manager_status(name)
        return status
    
    def clear_clock_manager_status(self, fpga_id=None, name=None):
        """
        Clear status of named TPM clock manager cores (MMCM Core).
        Used to reset MMCM lock loss counters.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param name: Specify name of clock manager (non case sensitive)
        :type name: string
        """
        for fpga in self.fpga_gen(fpga_id):
            self.tpm.tpm_clock_monitor[fpga].clear_clock_manager_status(name)
        return    

    def get_available_clock_managers(self):
        return self.tpm.tpm_clock_monitor[0].available_clock_managers

    def check_pps_status(self, fpga_id=None):
        """
        Check PPS is detected and PPS period is as expected.
        Firmware counts number of cycles between PPS and sets an error flag
        if the value does not match the pps_exp_tc register.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: true if all OK
        :rtype: bool
        """
        status = []
        for fpga in self.fpga_gen(fpga_id):
            status.append(self.tpm.tpm_test_firmware[fpga].check_pps_status())
        return all(status)
        
    def clear_pps_status(self, fpga_id=None):
        """
        Clear PPS error flags.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        status = []
        for fpga in self.fpga_gen(fpga_id):
            self.tpm.tpm_test_firmware[fpga].clear_pps_status()
        return

    def check_jesd_link_status(self, fpga_id=None, core_id=None):
        """
        Check if JESD204 lanes are synchronized.
        Checks the FPGA sync status register.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param core_id: Specify which JESD Core, 0,1, or None for both cores
        :type core_id: integer

        :return: true if all OK
        :rtype: bool
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga) if core_id is None else [core_id]
        result = []
        for fpga in self.fpga_gen(fpga_id):
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                result.append(self.tpm.tpm_jesd[idx].check_sync_status())
        return all(result)

    def clear_jesd_error_counters(self, fpga_id=None):
        """
        Reset JESD error counters.
         - JESD Error Counter
         - JESD Resync Counter (shared between JESD cores)
         - JESD QPLL Lock Loss Counter (shared between JESD cores)

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga)
        for fpga in self.fpga_gen(fpga_id):
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                self.tpm.tpm_jesd[idx].clear_error_counters()
        return

    def check_jesd_lane_error_counter(self, fpga_id=None, core_id=None):
        """
        Check JESD204 lanes errors.
        Checks the FPGA link error counter register.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param core_id: Specify which JESD Core, 0,1, or None for both cores
        :type core_id: integer

        :return: true if all OK
        :rtype: bool
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga) if core_id is None else [core_id]
        counter_dict = {}
        for fpga in self.fpga_gen(fpga_id):
            counter_dict[f'FPGA{fpga}'] = {}
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                counter_dict[f'FPGA{fpga}'][f'Core{core}'] = self.tpm.tpm_jesd[idx].check_link_error_counter()
        return counter_dict

    def check_jesd_lane_status(self, fpga_id=None, core_id=None):
        """
        Check JESD204 lanes errors.
        Checks the FPGA link error counter register.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param core_id: Specify which JESD Core, 0,1, or None for both cores
        :type core_id: integer

        :return: true if all error counters are 0
        :rtype: bool
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga) if core_id is None else [core_id]
        errors = []
        for fpga in self.fpga_gen(fpga_id):
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                count_dict = self.tpm.tpm_jesd[idx].check_link_error_counter()
                errors.extend(list(count_dict.values()))
        return not any(errors) # Return True if all error counters are 0

    def check_jesd_resync_counter(self, fpga_id=None, show_result=True):
        """
        Check JESD204 for resync events.
        Checks the FPGA resync counter register (shared between JESD cores).

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: counter values
        :rtype: dict
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            idx = fpga * jesd_cores_per_fpga
            counts[f'FPGA{fpga}'] = self.tpm.tpm_jesd[idx].check_resync_counter(show_result)
        return counts # Return dict of counter values

    def check_jesd_qpll_status(self, fpga_id=None, show_result=True):
        """
        Check JESD204 current status and for loss of QPLL lock events.
        Checks the FPGA qpll lock and qpll lock loss counter registers (shared between JESD cores).

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: current status and counter value tuple
        :rtype: dict
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        status = {}
        for fpga in self.fpga_gen(fpga_id):
            idx = fpga * jesd_cores_per_fpga
            lock_status = self.tpm.tpm_jesd[idx].check_qpll_lock_status()
            lock_loss_cnt = self.tpm.tpm_jesd[idx].check_qpll_lock_loss_counter(show_result)
            status[f'FPGA{fpga}'] = (lock_status, lock_loss_cnt)
        return status # Return dict of tuple (current status and counter values)

    def check_ddr_initialisation(self, fpga_id=None):
        """
        Check whether DDR has initialised.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: true if all OK
        :rtype: bool
        """
        result = []
        for fpga in self.fpga_gen(fpga_id):
            result.append(self.tpm.tpm_test_firmware[fpga].check_ddr_initialisation())
        return all(result)
    
    def check_ddr_reset_counter(self, fpga_id=None, show_result=True):
        """
        Check status of DDR user reset counter - increments each falling edge 
        of the DDR generated user logic reset.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: counter values
        :rtype: dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.tpm_test_firmware[fpga].check_ddr_user_reset_counter(show_result)
        return counts # Return dict of counter values
    
    def clear_ddr_reset_counter(self, fpga_id=None):
        """
        Reset value of DDR user reset counter.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        for fpga in self.fpga_gen(fpga_id):
            self.tpm.tpm_test_firmware[fpga].clear_ddr_user_reset_counter()
        return

    def check_ddr_parity_error_counter(self, fpga_id=None):
        """
        Check status of DDR parity error counter - used only with station beamformer

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: counter values
        :rtype: dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.station_beamf[fpga].check_ddr_parity_error_counter()
        return counts
    

    def check_f2f_pll_status(self, core_id=None, show_result=True):
        """
        Check current F2F PLL lock status and for loss of lock events.

        :param core_id: Specify which F2F Core, 0,1, or None for both cores
        :type core_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: current status and counter values
        :rtype: dict
        """
        # TPM 1.2 has 2 cores per FPGA while TPM 1.6 has 1
        # The below code is temporary until nof tpm_f2f instances is corrected and
        # nof_f2f_cores can be replaced with len(self.tpm.tpm_f2f)
        nof_f2f_cores = 2 if self.tpm_version() == "tpm_v1_2" else 1
        cores = range(nof_f2f_cores) if core_id is None else [core_id]
        counts = {}
        for core in cores:
            counts[f'Core{core}'] = self.tpm.tpm_f2f[core].check_pll_lock_status(show_result)
        return counts # Return dict of counter values

    def check_f2f_soft_errors(self):
        """
        Check F2F for soft errors.
        Asserted for a single user_clk period.

        :return: soft_err register value
        :rtype: integer
        """
        return None if self.tpm_version() == "tpm_v1_2" else self.tpm.tpm_f2f[0].get_soft_err()
    
    def check_f2f_hard_errors(self):
        """
        Check F2F for hard errors.
        Asserted until the core resets.

        :return: hard_err register value
        :rtype: integer
        """
        return None if self.tpm_version() == "tpm_v1_2" else self.tpm.tpm_f2f[0].get_hard_err()

    def clear_f2f_pll_lock_loss_counter(self, core_id=None):
        """
        Reset value of F2F PLL lock loss counter.

        :param core_id: Specify which F2F Core, 0,1, or None for both cores
        :type core_id: integer
        """
        # TPM 1.2 has 2 cores per FPGA while TPM 1.6 has 1
        # The below code is temporary until nof tpm_f2f instances is corrected and
        # nof_f2f_cores can be replaced with len(self.tpm.tpm_f2f)
        nof_f2f_cores = 2 if self.tpm_version() == "tpm_v1_2" else 1
        cores = range(nof_f2f_cores) if core_id is None else [core_id]
        for core in cores:
            self.tpm.tpm_f2f[core].clear_pll_lock_loss_counter()
        return
    
    def check_data_router_status(self, fpga_id=None):
        """
        Check data router error flags.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        
        :return: register values
        :rtype: dict
        """

        output_dict = {'status': {}, 'discarded_packets': {}}

        for fpga in self.fpga_gen(fpga_id):
            output_dict['status'][f'FPGA{fpga}'] = self.tpm.tpm_test_firmware[fpga].check_data_router_status()
            output_dict['discarded_packets'][f'FPGA{fpga}'] = self.tpm.tpm_test_firmware[fpga].check_data_router_discarded_packets()

        return output_dict

    def clear_data_router_status(self, fpga_id=None):
        """
        Reset data router error flags.
        
        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        for fpga in self.fpga_gen(fpga_id):
           self.tpm.tpm_test_firmware[fpga].clear_data_router_status()
        return
        
    def check_udp_arp_table_status(self, fpga_id=None, show_result=True):
        """
        Check UDP ARP Table has been populated correctly. This is a non-
        destructive version of the method check_arp_table.

        :param show_result: prints ARP table contents on logger
        :type show_result: bool

        :return: true if each FPGA has at least one entry valid and resolved.
        :rtype: bool
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga
        silent_mode = not show_result
        arp_table_ids = range(self.tpm.tpm_10g_core[0].get_number_of_arp_table_entries())
        fpga_resolved_entries = []
        fpga_unresolved_entries = []
        for fpga in self.fpga_gen(fpga_id):
            if self.active_40g_port[fpga]:  # Ignore ARP table if 40G QSFP not in use
                resolved_cnt = 0
                unresolved_cnt = 0
                for arp_table in arp_table_ids:
                    arp_status, mac = self.tpm.tpm_10g_core[fpga].get_arp_table_status(arp_table, silent_mode)
                    if arp_status & 0x1:
                        if arp_status & 0x4:
                            resolved_cnt += 1
                        else:
                            unresolved_cnt += 1
                fpga_resolved_entries.append(resolved_cnt)
                fpga_unresolved_entries.append(unresolved_cnt)
        return True if all(fpga_resolved_entries) and not any(fpga_unresolved_entries) else False
           
    def check_udp_status(self, fpga_id=None):
        """
        Check for 40G errors.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: true if all OK (all error counters are 0)
        :rtype: bool
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga, 4 ARP table IDs per core
        errors = []
        for fpga in self.fpga_gen(fpga_id):
            if self.active_40g_port[fpga]:  # Ignore errors if 40G QSFP not in use
                errors.append(self.tpm.tpm_10g_core[fpga].check_errors())
        return not any(errors) # Return True if status OK, all errors False
           
    def clear_udp_status(self, fpga_id=None):
        """
        Reset 40G error counters.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga, 4 ARP table IDs per core
        for fpga in self.fpga_gen(fpga_id):
            self.tpm.tpm_10g_core[fpga].reset_errors()
        return
    
    def check_udp_linkup_loss_counter(self, fpga_id=None, show_result=True):
        """
        Check UDP interface for linkup loss events.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: counter values
        :rtype: dict
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga, 4 ARP table IDs per core
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.tpm_10g_core[fpga].check_linkup_loss_cnt(show_result)
        return counts # Return dict of counter values

    def check_udp_crc_error_counter(self, fpga_id=None):
        """
        Check UDP interface for CRC errors.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: counter values
        :rtype: dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.tpm_10g_core[fpga].get_crc_error_count()
        return counts # Return dict of counter values
    
    def check_udp_bip_error_counter(self, fpga_id=None):
        """
        Check UDP interface for BIP errors.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: counter values
        :rtype: dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            if self.active_40g_port[fpga]:  # Ignore BIP errors if 40G QSFP not in use
                counts[f'FPGA{fpga}'] = self.tpm.tpm_10g_core[fpga].get_bip_error_count()
            else:
                counts[f'FPGA{fpga}'] = {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0}
        return counts # Return dict of counter values

    def check_udp_decode_error_counter(self, fpga_id=None):
        """
        Check UDP interface for 66b64b decoding errors.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: counter values
        :rtype: dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.tpm_10g_core[fpga].get_decode_error_count()
        return counts # Return dict of counter values
    
    def check_tile_beamformer_status(self, fpga_id=None):
        """
        Check tile beamformer error flags.
        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.is_programmed():
            result = []
            for fpga in self.fpga_gen(fpga_id):
                result.append(self.tpm.beamf_fd[fpga].check_errors())
            return all(result)
        return
    
    def clear_tile_beamformer_status(self, fpga_id=None):
        """
        Clear tile beamformer error flags.
        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tpm.beamf_fd[fpga].clear_errors()
        return

    def check_station_beamformer_status(self, fpga_id=None):
        """
        Check status of Station Beamformer error flags and counters.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.is_programmed():
            errors = []
            for fpga in self.fpga_gen(fpga_id):
                errors.append(self.tpm.station_beamf[fpga].report_errors())
            return not any(errors) # Return True if all flags and counters are 0, else False
        return

    def clear_station_beamformer_status(self, fpga_id=None):
        """
        Clear status of Station Beamformer error flags and counters.
        Including DDR parity error counter.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tpm.station_beamf[fpga].clear_errors()
        return

    #######################################################################################
    # ------------------- Test methods
    
    def inject_ddr_parity_error(self, fpga_id=None):
        for fpga in self.fpga_gen(fpga_id):
            board = f'fpga{fpga+1}'
            self.logger.info(f"Injecting DDR Parity Error - FPGA{fpga}")
            self[f'{board}.beamf_ring.ddr_parity_error_inject'] = 1
            timeout = 60 # 30 seconds
            count = 0
            while True:
                reg = self[f'{board}.beamf_ring.ddr_parity_error_inject']
                if reg == 0:  # Register deasserts once injection has completed
                    break
                if count % 4 == 0: # Every 2 seconds
                    self.logger.info("Waiting for valid DDR read transaction...")
                if count > timeout:
                    self.logger.error("Timed out waiting for DDR parity error injection acknowledge. No valid DDR read transaction")
                    break
                time.sleep(0.5)
                count += 1
        return
