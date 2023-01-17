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


class TileHealthMonitor:
    """
    """

    def __init__(self, tile):
        """
        Initialise a new TileHealthMonitor instance.
        """
        self.tile = tile
        return
    
    def enable_health_monitoring(self):
        # For use with get_health_status and clear_health_status
        # Enable anything that requires an enable
        self.enable_clock_monitoring()
        return

    def get_health_status(self):
        health_dict = {}

        # Temp initialisations
        fpga_id = None
        core_id = None
        voltage_name = None
        current_name = None
        clock_name = 'all'
        name = None

        # Board level monitoring points
        health_dict['temperature'] = {}
        health_dict['temperature']['board'] = self.tile.get_temperature()
        health_dict['temperature'].update(self.get_fpga_temperature(fpga_id))
        health_dict['voltage'] = {}
        health_dict['voltage'].update(self.get_voltage(fpga_id, voltage_name))
        health_dict['current'] = {}
        health_dict['current'].update(self.get_current(fpga_id, current_name))

        # Timing Signal monitoing points
        health_dict['timing'] = {}
        health_dict['timing']['clocks'] = self.check_clock_status(fpga_id, clock_name)
        health_dict['timing'].update(self.check_clock_manager_status(fpga_id, name))
        health_dict['timing']['pps'] = self.check_pps_status(fpga_id)
        # health_dict['timing']['pll'] = self.check_pll_status() # TODO: add method


        # JESD monitoing points
        health_dict['jesd_if'] = {}
        health_dict['jesd_if']['lanes'] = self.check_jesd_lanes(fpga_id, core_id)
        health_dict['jesd_if']['error_count'] = self.check_jesd_error_counter(fpga_id, core_id)
        health_dict['jesd_if']['resync_count'] = self.check_jesd_resync_counter(fpga_id)
        health_dict['jesd_if']['drop_count'] = self.check_jesd_qpll_drop_counter(fpga_id)

        # DDR monitoring points
        health_dict['ddr_if'] = {}
        health_dict['ddr_if']['initialisation'] = self.check_ddr_initialisation(fpga_id)
        health_dict['ddr_if']['reset_counter'] = self.check_ddr_reset_counter(fpga_id)
        
        # F2F monitoing points
        health_dict['f2f_if'] = {}
        health_dict['f2f_if']['drop_count'] = self.check_f2f_drop_counter()

        # UDP monitoring points
        health_dict['udp_if'] = {}
        health_dict['udp_if']['arp'] = self.check_udp_arp_table_status(fpga_id)
        health_dict['udp_if']['status'] = self.check_udp_status(fpga_id)
        health_dict['udp_if']['drop_count'] = self.check_udp_link_drop_counter(fpga_id)

        # DSP monitoring points
        health_dict['tile_beamf'] = self.check_tile_beamformer_status(fpga_id)
        health_dict['station_beamf'] = self.check_station_beamformer_status(fpga_id)

        return health_dict
    
    def clear_health_status(self):
        pass
    
    def fpga_gen(self, fpga_id):
        return range(len(self.tile.tpm.tpm_test_firmware)) if fpga_id is None else [fpga_id]
    
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
            if self.tile.is_programmed():
                temperature_dict[f'FPGA{fpga}'] = round(self.tile.tpm.tpm_sysmon[fpga].get_fpga_temperature(), 2)
            else:
                temperature_dict[f'FPGA{fpga}'] = 0
        return temperature_dict
    
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
        if hasattr(self.tile.tpm, 'tpm_lasc'):
            available_voltages.extend(self.tile.tpm.tpm_lasc[0].get_available_voltages())
        # MCU Plugin TPM 1.6
        if hasattr(self.tile.tpm, 'tpm_monitor'):
            available_voltages.extend(self.tile.tpm.tpm_monitor[0].get_available_voltages())
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            available_voltages.extend(self.tile.tpm.tpm_sysmon[fpga].get_available_voltages())
        return available_voltages

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
        if hasattr(self.tile.tpm, 'tpm_lasc'):
            voltage_dict.update(self.tile.tpm.tpm_lasc[0].get_voltage(voltage_name))
        # MCU Plugin TPM 1.6
        if hasattr(self.tile.tpm, 'tpm_monitor'):
            voltage_dict.update(self.tile.tpm.tpm_monitor[0].get_voltage(voltage_name))
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            voltage_dict.update(self.tile.tpm.tpm_sysmon[fpga].get_voltage(voltage_name))
        if voltage_name is not None and not voltage_dict:
            raise LibraryError(f"No voltage named '{voltage_name.upper()}' \n Options are {', '.join(self.get_available_voltages(fpga_id))} (not case sensitive)")
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
        if hasattr(self.tile.tpm, 'tpm_lasc'):
            available_currents.extend(self.tile.tpm.tpm_lasc[0].get_available_currents())
        # MCU Plugin TPM 1.6
        if hasattr(self.tile.tpm, 'tpm_monitor'):
            available_currents.extend(self.tile.tpm.tpm_monitor[0].get_available_currents())
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            available_currents.extend(self.tile.tpm.tpm_sysmon[fpga].get_available_currents())
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
        if hasattr(self.tile.tpm, 'tpm_lasc'):
            current_dict.update(self.tile.tpm.tpm_lasc[0].get_current(current_name))
        # MCU Plugin TPM 1.6
        if hasattr(self.tile.tpm, 'tpm_monitor'):
            current_dict.update(self.tile.tpm.tpm_monitor[0].get_current(current_name))
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            current_dict.update(self.tile.tpm.tpm_sysmon[fpga].get_current(current_name))
        if current_name is not None and not current_dict:
            raise LibraryError(f"No current named '{current_name.upper()}' \n Options are {', '.join(self.get_available_currents(fpga_id))} (not case sensitive)")
        return current_dict
    
    def get_available_clocks_to_monitor(self):
        """
        :return: list of clock names available to be monitored
        :rtype list of string
        """
        if self.tile.is_programmed():
            return self.tile.tpm.tpm_clock_monitor[0].get_available_clocks_to_monitor()

    def enable_clock_monitoring(self, fpga_id=None, clock_name='all'):
        """
        Enable clock monitoring of named TPM clocks
        Options 'jesd', 'ddr', 'udp', 'all'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only enable monitoring on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        :param clock_name: Specify name of clock
        :type clock_name: string
        """
        if self.tile.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                    self.tile.tpm.tpm_clock_monitor[fpga].enable_clock_monitoring(clock_name)
        return

    def disable_clock_monitoring(self, fpga_id=None, clock_name='all'):
        """
        Disable clock monitoring of named TPM clocks
        Options 'jesd', 'ddr', 'udp', 'all'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only disable monitoring on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        :param clock_name: Specify name of clock
        :type clock_name: string
        """
        if self.tile.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tile.tpm.tpm_clock_monitor[fpga].disable_clock_monitoring(clock_name)
        return
    
    def check_clock_status(self, fpga_id=None, clock_name='all'):
        """
        Check status of named TPM clocks
        Options 'jesd', 'ddr', 'udp', 'all'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only check status on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        :param clock_name: Specify name of clock
        :type clock_name: string

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.tile.is_programmed():
            result = []
            for fpga in self.fpga_gen(fpga_id):
                result.append(self.tile.tpm.tpm_clock_monitor[fpga].check_clock_status(clock_name))
            return all(result)
        return
    
    def clear_clock_status(self, fpga_id=None, clock_name='all'):
        """
        Clear status of named TPM clocks
        Used to Clear error flags in FPGA Firmware
        Options 'jesd', 'ddr', 'udp', 'all'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only clear status on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        :param clock_name: Specify name of clock
        :type clock_name: string
        """
        if self.tile.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tile.tpm.tpm_clock_monitor[fpga].clear_clock_status(clock_name)
        return    

    def check_clock_manager_status(self, fpga_id=None, name=None):
        """
        Check status of named TPM clock manager cores (MMCM Core).
        Reports the values each MMCM lock loss counter.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param name: Specify name of clock manager (non case sensitive)
        :type name: string

        :return: Counter values
        :rtype dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tile.tpm.tpm_clock_monitor[fpga].check_clock_manager_status(name)
        return counts
    
    def clear_clock_manager_status(self, fpga_id=None, name=None):
        """
        Clear status of named TPM clock manager cores (MMCM Core).
        Used to reset MMCM lock loss counters.
        Options 'jesd', 'ddr', 'udp', 'all'

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param name: Specify name of clock manager (non case sensitive)
        :type name: string
        """
        for fpga in self.fpga_gen(fpga_id):
            self.tile.tpm.tpm_clock_monitor[fpga].clear_clock_manager_status(name)
        return    

    def get_available_clock_managers(self):
        return self.tile.tpm.tpm_clock_monitor[0].available_clock_managers

    def check_pps_status(self, fpga_id=None):
        """
        Check PPS is detected and error free.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: true if all OK
        :rtype: bool
        """
        status = []
        for fpga in self.fpga_gen(fpga_id):
            status.append(self.tile.tpm.tpm_test_firmware[fpga].check_pps_status())
        return all(status)
        
    def clear_pps_status(self, fpga_id=None):
        """
        Clear PPS error flags.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        status = []
        for fpga in self.fpga_gen(fpga_id):
            self.tile.tpm.tpm_test_firmware[fpga].clear_pps_status()
        return

    def check_jesd_lanes(self, fpga_id=None, core_id=None):
        """
        Check if JESD204 lanes are error free.
        Checks the FPGA link error status and FPGA sync status registers.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param core_id: Specify which JESD Core, 0,1, or None for both cores
        :type core_id: integer

        :return: true if all OK
        :rtype: bool
        """
        jesd_cores_per_fpga = len(self.tile.tpm.tpm_jesd) // len(self.tile.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga) if core_id is None else [core_id]
        result = []
        for fpga in self.fpga_gen(fpga_id):
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                result.append(self.tile.tpm.tpm_jesd[idx].check_link_error_status())
                result.append(self.tile.tpm.tpm_jesd[idx].check_sync_status())
        return all(result)

    def clear_jesd_error_counters(self, fpga_id=None):
        """
        Reset JESD error counters.
         - JESD Error Counter
         - JESD Resync Counter (shared between JESD cores)
         - JESD QPLL Drop Counter (shared between JESD cores)

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        jesd_cores_per_fpga = len(self.tile.tpm.tpm_jesd) // len(self.tile.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga)
        for fpga in self.fpga_gen(fpga_id):
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                self.tile.tpm.tpm_jesd[idx].clear_error_counters()
        return

    def check_jesd_error_counter(self, fpga_id=None, core_id=None, show_result=True):
        """
        Check JESD204 lanes errors.
        Checks the FPGA link error counter register.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param core_id: Specify which JESD Core, 0,1, or None for both cores
        :type core_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: true if all OK
        :rtype: bool
        """
        jesd_cores_per_fpga = len(self.tile.tpm.tpm_jesd) // len(self.tile.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga) if core_id is None else [core_id]
        result = []
        for fpga in self.fpga_gen(fpga_id):
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                result.append(self.tile.tpm.tpm_jesd[idx].check_link_error_counter(show_result))
        return all(result)

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
        jesd_cores_per_fpga = len(self.tile.tpm.tpm_jesd) // len(self.tile.tpm.tpm_test_firmware)
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            idx = fpga * jesd_cores_per_fpga
            counts[f'FPGA{fpga}'] = self.tile.tpm.tpm_jesd[idx].check_resync_counter(show_result)
        return counts # Return dict of counter values

    def check_jesd_qpll_drop_counter(self, fpga_id=None, show_result=True):
        """
        Check JESD204 for dropped QPLL lock events.
        Checks the FPGA qpll lock loss counter register (shared between JESD cores).

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: counter values
        :rtype: dict
        """
        jesd_cores_per_fpga = len(self.tile.tpm.tpm_jesd) // len(self.tile.tpm.tpm_test_firmware)
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            idx = fpga * jesd_cores_per_fpga
            counts[f'FPGA{fpga}'] = self.tile.tpm.tpm_jesd[idx].check_qpll_lock_loss_counter(show_result)
        return counts # Return dict of counter values

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
            result.append(self.tile.tpm.tpm_test_firmware[fpga].check_ddr_initialisation())
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
            counts[f'FPGA{fpga}'] = self.tile.tpm.tpm_test_firmware[fpga].check_ddr_user_reset_counter(show_result)
        return counts # Return dict of counter values
    
    def clear_ddr_reset_counter(self, fpga_id=None):
        """
        Reset value of DDR user reset counter.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        for fpga in self.fpga_gen(fpga_id):
            self.tile.tpm.tpm_test_firmware[fpga].clear_ddr_user_reset_counter()
        return

    def check_f2f_drop_counter(self, core_id=None, show_result=True):
        """
        Check for F2F PLL loss of lock events.

        :param core_id: Specify which F2F Core, 0,1, or None for both cores
        :type core_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: counter values
        :rtype: dict
        """
        # TPM 1.2 has 2 cores per FPGA while TPM 1.6 has 1
        # The below code is temporary until nof tpm_f2f instances is corrected and
        # nof_f2f_cores can be replaced with len(self.tile.tpm.tpm_f2f)
        nof_f2f_cores = 2 if self.tile.tpm_version() == "tpm_v1_2" else 1
        cores = range(nof_f2f_cores) if core_id is None else [core_id]
        counts = {}
        for core in cores:
            counts[f'Core{core}'] = self.tile.tpm.tpm_f2f[core].check_pll_lock_loss_counter(show_result)
        return counts # Return dict of counter values

    def clear_f2f_drop_counter(self, core_id=None):
        """
        Reset value of F2F PLL lock loss counter.

        :param core_id: Specify which F2F Core, 0,1, or None for both cores
        :type core_id: integer
        """
        # TPM 1.2 has 2 cores per FPGA while TPM 1.6 has 1
        # The below code is temporary until nof tpm_f2f instances is corrected and
        # nof_f2f_cores can be replaced with len(self.tile.tpm.tpm_f2f)
        nof_f2f_cores = 2 if self.tile.tpm_version() == "tpm_v1_2" else 1
        cores = range(nof_f2f_cores) if core_id is None else [core_id]
        for core in cores:
            self.tile.tpm.tpm_f2f[core].clear_pll_lock_loss_counter()
        return

    def check_udp_arp_table_status(self, fpga_id=None, show_result=True):
        """
        Check UDP ARP Table has been populated correctly. This is a non-
        destructive version of the method check_arp_table.

        :param show_result: prints ARP table contents on logger
        :type show_result: bool

        :return: true if all OK, entries valid and resolved.
        :rtype: bool
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga, 4 ARP table IDs per core
        silent_mode = not show_result
        arp_table_ids = range(4)
        status = []
        nof_resolved_entries = 0
        fpgas = self.fpga_gen(fpga_id)
        for i, fpga in enumerate(fpgas):
            for arp_table in arp_table_ids:
                arp_status, mac = self.tile.tpm.tpm_10g_core[fpga].get_arp_table_status(arp_table, silent_mode)
                if arp_status & 0x1 and arp_status & 0x4:
                    nof_resolved_entries += 1
        return True if nof_resolved_entries == 2*len(fpgas) else False
        # TODO: Will it always be the case there are 2 resolved valid entries per FPGA?

    def check_udp_status(self, fpga_id=None):
        """
        Check for UDP C2C and BIP errors.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: true if all OK (all error counters are 0)
        :rtype: bool
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga, 4 ARP table IDs per core
        errors = []
        for fpga in self.fpga_gen(fpga_id):
            errors.append(self.tile.tpm.tpm_10g_core[fpga].check_errors())
        return not any(errors) # Return True if status OK, all errors False
    
    def clear_udp_status(self, fpga_id=None):
        """
        Reset UDP C2C and BIP error counters.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga, 4 ARP table IDs per core
        for fpga in self.fpga_gen(fpga_id):
            self.tile.tpm.tpm_10g_core[fpga].reset_errors()
        return
    
    def check_udp_link_drop_counter(self, fpga_id=None, show_result=True):
        """
        Check UDP interface for link drop events.

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
            counts[f'FPGA{fpga}'] = self.tile.tpm.tpm_10g_core[fpga].check_linkup_loss_cnt(show_result)
        return counts # Return dict of counter values
    
    def check_tile_beamformer_status(self, fpga_id=None):
        """
        Check tile beamformer error flags.
        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.tile.is_programmed():
            result = []
            for fpga in self.fpga_gen(fpga_id):
                result.append(self.tile.tpm.beamf_fd[fpga].check_errors())
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
        if self.tile.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tile.tpm.beamf_fd[fpga].clear_errors()
        return

    def check_station_beamformer_status(self, fpga_id=None, show_result=True):
        """
        Check status of Station Beamformer error flags and counters.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.tile.is_programmed():
            result = []
            for fpga in self.fpga_gen(fpga_id):
                frame_errors, errors = self.tile.tpm.station_beamf[fpga].report_errors(show_result)
                result.append(frame_errors)
                result.append(errors)
            return not any(result) # Return True if all flags and counters are 0, else False
        return

    def clear_station_beamformer_status(self, fpga_id=None):
        """
        Clear status of Station Beamformer error flags and counters.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        if self.tile.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tile.tpm.station_beamf[fpga].clear_errors()
        return
