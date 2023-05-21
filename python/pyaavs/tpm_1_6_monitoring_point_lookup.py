from functools import partial

"""
For use with Tile Health Monitor Class
Tile Health Monitor will produce a health status dictionary matching
the format descibed below.

* Hierarchy can easily be changed by modifying below.
* Moitoring points can easily be expanded by adding a new entry with 
  specified method, exp_value, rate and group.
* Values specified here for rate and group are only defaults, values
  can be changed during deployment using set_monitoring_point_attr() 
  method with argument "rate" or "group" or other.
* It is not even necessary to use the predefined attributes "rate" 
  and "group". Monitoring points can be divided in any way using any
  key using the set_monitoring_point_attr() method.
* Expected values used only for AAVS HW test suite at present.

TPM 1.6 min and max voltage ranges are taken from factory acceptance
testing. See https://confluence.skatelescope.org/x/nDhED
"""

def load_tpm_1_6_lookup(obj):
    return {
        'temperatures': {
            'board': {"method": obj.get_temperature,                          "rate": ["fast"], "group": ["temperatures"], "exp_value": { "min": 10.00, "max": 68.00}},
            'FPGA0': {"method": partial(obj.get_fpga_temperature, fpga_id=0), "rate": ["fast"], "group": ["temperatures"], "exp_value": { "min": 10.00, "max": 95.00}},
            'FPGA1': {"method": partial(obj.get_fpga_temperature, fpga_id=1), "rate": ["fast"], "group": ["temperatures"], "exp_value": { "min": 10.00, "max": 95.00}}
        },
        'voltages': {
            'VREF_2V5'   : {"method": partial(obj.get_voltage, voltage_name='VREF_2V5'),    "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 2.370, "max": 2.630, "skip": True}},  # TODO: add support for this measurement
            'MGT_AVCC'   : {"method": partial(obj.get_voltage, voltage_name='MGT_AVCC'),    "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.850, "max": 0.950}},
            'MGT_AVTT'   : {"method": partial(obj.get_voltage, voltage_name='MGT_AVTT'),    "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 1.140, "max": 1.260}},
            'SW_AVDD1'   : {"method": partial(obj.get_voltage, voltage_name='SW_AVDD1'),    "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 1.040, "max": 1.160}},
            'SW_AVDD2'   : {"method": partial(obj.get_voltage, voltage_name='SW_AVDD2'),    "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 2.180, "max": 2.420}},
            'AVDD3'      : {"method": partial(obj.get_voltage, voltage_name='AVDD3'),       "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 2.370, "max": 2.600}},
            'MAN_1V2'    : {"method": partial(obj.get_voltage, voltage_name='MAN_1V2'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 1.140, "max": 1.260}},
            'DDR0_VREF'  : {"method": partial(obj.get_voltage, voltage_name='DDR0_VREF'),   "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.570, "max": 0.630}},
            'DDR1_VREF'  : {"method": partial(obj.get_voltage, voltage_name='DDR1_VREF'),   "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.570, "max": 0.630}},
            'VM_DRVDD'   : {"method": partial(obj.get_voltage, voltage_name='VM_DRVDD'),    "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 1.710, "max": 1.890}},
            'VIN'        : {"method": partial(obj.get_voltage, voltage_name='VIN'),         "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 11.40, "max": 12.60}},
            'MON_3V3'    : {"method": partial(obj.get_voltage, voltage_name='MON_3V3'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 3.130, "max": 3.460, "skip": True}},  # SKIP can be removed once MCCS-1348 is complete
            'MON_1V8'    : {"method": partial(obj.get_voltage, voltage_name='MON_1V8'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 1.710, "max": 1.890, "skip": True}},  # SKIP can be removed once MCCS-1348 is complete
            'MON_5V0'    : {"method": partial(obj.get_voltage, voltage_name='MON_5V0'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 4.690, "max": 5.190}},
            'VM_ADA0'    : {"method": partial(obj.get_voltage, voltage_name='VM_ADA0'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 3.040, "max": 3.560, "skip": True}},  # Assume ADAs disabled
            'VM_ADA1'    : {"method": partial(obj.get_voltage, voltage_name='VM_ADA1'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 3.040, "max": 3.560, "skip": True}},  # Assume ADAs disabled
            'VM_AGP0'    : {"method": partial(obj.get_voltage, voltage_name='VM_AGP0'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.840, "max": 1.000}},
            'VM_AGP1'    : {"method": partial(obj.get_voltage, voltage_name='VM_AGP1'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.840, "max": 1.000}},
            'VM_AGP2'    : {"method": partial(obj.get_voltage, voltage_name='VM_AGP2'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.840, "max": 1.000}},
            'VM_AGP3'    : {"method": partial(obj.get_voltage, voltage_name='VM_AGP3'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.840, "max": 1.000}},
            'VM_CLK0B'   : {"method": partial(obj.get_voltage, voltage_name='VM_CLK0B'),    "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 3.040, "max": 3.560}},
            'VM_DDR0_VTT': {"method": partial(obj.get_voltage, voltage_name='VM_DDR0_VTT'), "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.550, "max": 0.650}},
            'VM_FE0'     : {"method": partial(obj.get_voltage, voltage_name='VM_FE0'),      "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 3.220, "max": 3.780, "skip": True}},  # Assume PreADUs disabled
            'VM_MGT0_AUX': {"method": partial(obj.get_voltage, voltage_name='VM_MGT0_AUX'), "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 1.660, "max": 1.940}},
            'VM_PLL'     : {"method": partial(obj.get_voltage, voltage_name='VM_PLL'),      "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 3.040, "max": 3.560}},
            'VM_AGP4'    : {"method": partial(obj.get_voltage, voltage_name='VM_AGP4'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.840, "max": 1.000}},
            'VM_AGP5'    : {"method": partial(obj.get_voltage, voltage_name='VM_AGP5'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.840, "max": 1.000}},
            'VM_AGP6'    : {"method": partial(obj.get_voltage, voltage_name='VM_AGP6'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.840, "max": 1.000}},
            'VM_AGP7'    : {"method": partial(obj.get_voltage, voltage_name='VM_AGP7'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.840, "max": 1.000}},
            'VM_CLK1B'   : {"method": partial(obj.get_voltage, voltage_name='VM_CLK1B'),    "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 3.040, "max": 3.560}},
            'VM_DDR1_VDD': {"method": partial(obj.get_voltage, voltage_name='VM_DDR1_VDD'), "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 1.100, "max": 1.300}},
            'VM_DDR1_VTT': {"method": partial(obj.get_voltage, voltage_name='VM_DDR1_VTT'), "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 0.550, "max": 0.650}},
            'VM_DVDD'    : {"method": partial(obj.get_voltage, voltage_name='VM_DVDD'),     "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 1.010, "max": 1.190}},
            'VM_FE1'     : {"method": partial(obj.get_voltage, voltage_name='VM_FE1'),      "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 3.220, "max": 3.780, "skip": True}},  # Assume PreADUs disabled
            'VM_MGT1_AUX': {"method": partial(obj.get_voltage, voltage_name='VM_MGT1_AUX'), "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 1.660, "max": 1.940}},
            'VM_SW_AMP'  : {"method": partial(obj.get_voltage, voltage_name='VM_SW_AMP'),   "rate": ["fast"], "group": ["voltages"], "exp_value": { "min": 3.220, "max": 3.780}}
        },
        'currents': {
            'FE0_mVA': {"method": partial(obj.get_current, current_name='FE0_mVA'), "rate": ["fast"], "group": ["currents"], "exp_value": { "min": 0.000, "max": 2.270}},
            'FE1_mVA': {"method": partial(obj.get_current, current_name='FE1_mVA'), "rate": ["fast"], "group": ["currents"], "exp_value": { "min": 0.000, "max": 2.380}}
        },
        'alarms': {"method": obj.check_global_status_alarms, "rate": ["fast"], "group": ["alarms"], "exp_value": {'I2C_access_alm': 0, 'temperature_alm': 0, 'voltage_alm': 0, 'SEM_wd': 0, 'MCU_wd': 0}},
        'adcs'  : {
            'pll_status': {
                'ADC0' : {"method": partial(obj.check_adc_pll_status, adc_id=0),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC1' : {"method": partial(obj.check_adc_pll_status, adc_id=1),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC2' : {"method": partial(obj.check_adc_pll_status, adc_id=2),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC3' : {"method": partial(obj.check_adc_pll_status, adc_id=3),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC4' : {"method": partial(obj.check_adc_pll_status, adc_id=4),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC5' : {"method": partial(obj.check_adc_pll_status, adc_id=5),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC6' : {"method": partial(obj.check_adc_pll_status, adc_id=6),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC7' : {"method": partial(obj.check_adc_pll_status, adc_id=7),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC8' : {"method": partial(obj.check_adc_pll_status, adc_id=8),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC9' : {"method": partial(obj.check_adc_pll_status, adc_id=9),  "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC10': {"method": partial(obj.check_adc_pll_status, adc_id=10), "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC11': {"method": partial(obj.check_adc_pll_status, adc_id=11), "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC12': {"method": partial(obj.check_adc_pll_status, adc_id=12), "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC13': {"method": partial(obj.check_adc_pll_status, adc_id=13), "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC14': {"method": partial(obj.check_adc_pll_status, adc_id=14), "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)},
                'ADC15': {"method": partial(obj.check_adc_pll_status, adc_id=15), "rate": ["fast"], "group": ["adcs"], "exp_value": (True, True)}
            },
            'sysref_timing_requirements': {
                'ADC0' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=0, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC1' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=1, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC2' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=2, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC3' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=3, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC4' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=4, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC5' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=5, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC6' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=6, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC7' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=7, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC8' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=8, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC9' : {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=9, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC10': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=10, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC11': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=11, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC12': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=12, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC13': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=13, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC14': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=14, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC15': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=15, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True}
            },
            'sysref_counter': {
                'ADC0' : {"method": partial(obj.check_adc_sysref_counter, adc_id=0, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC1' : {"method": partial(obj.check_adc_sysref_counter, adc_id=1, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC2' : {"method": partial(obj.check_adc_sysref_counter, adc_id=2, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC3' : {"method": partial(obj.check_adc_sysref_counter, adc_id=3, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC4' : {"method": partial(obj.check_adc_sysref_counter, adc_id=4, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC5' : {"method": partial(obj.check_adc_sysref_counter, adc_id=5, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC6' : {"method": partial(obj.check_adc_sysref_counter, adc_id=6, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC7' : {"method": partial(obj.check_adc_sysref_counter, adc_id=7, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC8' : {"method": partial(obj.check_adc_sysref_counter, adc_id=8, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC9' : {"method": partial(obj.check_adc_sysref_counter, adc_id=9, show_info=False),  "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC10': {"method": partial(obj.check_adc_sysref_counter, adc_id=10, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC11': {"method": partial(obj.check_adc_sysref_counter, adc_id=11, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC12': {"method": partial(obj.check_adc_sysref_counter, adc_id=12, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC13': {"method": partial(obj.check_adc_sysref_counter, adc_id=13, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC14': {"method": partial(obj.check_adc_sysref_counter, adc_id=14, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True},
                'ADC15': {"method": partial(obj.check_adc_sysref_counter, adc_id=15, show_info=False), "rate": ["fast"], "group": ["adcs"], "exp_value": True}
            }
        }, 
        'timing': {
            'clocks': {
                'FPGA0': {
                    'JESD': {"method": partial(obj.check_clock_status, fpga_id=0, clock_name='JESD'), "rate": ["fast"], "group": ["timing", "clocks"], "exp_value": True},
                    'DDR' : {"method": partial(obj.check_clock_status, fpga_id=0, clock_name='DDR'),  "rate": ["fast"], "group": ["timing", "clocks"], "exp_value": True},
                    'UDP' : {"method": partial(obj.check_clock_status, fpga_id=0, clock_name='UDP'),  "rate": ["fast"], "group": ["timing", "clocks"], "exp_value": True}
                },
                'FPGA1': {
                    'JESD': {"method": partial(obj.check_clock_status, fpga_id=1, clock_name='JESD'), "rate": ["fast"], "group": ["timing", "clocks"], "exp_value": True},
                    'DDR' : {"method": partial(obj.check_clock_status, fpga_id=1, clock_name='DDR'),  "rate": ["fast"], "group": ["timing", "clocks"], "exp_value": True},
                    'UDP' : {"method": partial(obj.check_clock_status, fpga_id=1, clock_name='UDP'),  "rate": ["fast"], "group": ["timing", "clocks"], "exp_value": True}
                }
            },
            'clock_managers' : {
                'FPGA0': {
                    'C2C_MMCM' : {"method": partial(obj.check_clock_manager_status, fpga_id=0, name='C2C'),  "rate": ["fast"], "group": ["timing", "clock_managers"], "exp_value": (True, 0)},
                    'JESD_MMCM': {"method": partial(obj.check_clock_manager_status, fpga_id=0, name='JESD'), "rate": ["fast"], "group": ["timing", "clock_managers"], "exp_value": (True, 0)},
                    'DSP_MMCM' : {"method": partial(obj.check_clock_manager_status, fpga_id=0, name='DSP'),  "rate": ["fast"], "group": ["timing", "clock_managers"], "exp_value": (True, 0)}
                },
                'FPGA1': {
                    'C2C_MMCM' : {"method": partial(obj.check_clock_manager_status, fpga_id=1, name='C2C'),  "rate": ["fast"], "group": ["timing", "clock_managers"], "exp_value": (True, 0)},
                    'JESD_MMCM': {"method": partial(obj.check_clock_manager_status, fpga_id=1, name='JESD'), "rate": ["fast"], "group": ["timing", "clock_managers"], "exp_value": (True, 0)},
                    'DSP_MMCM' : {"method": partial(obj.check_clock_manager_status, fpga_id=1, name='DSP'),  "rate": ["fast"], "group": ["timing", "clock_managers"], "exp_value": (True, 0)}
                }
            },
            'pps': {
                'status': {"method": obj.check_pps_status, "rate": ["fast"], "group": ["timing", "pps"], "exp_value": True}
            },
            'pll': {"method": obj.check_ad9528_pll_status, "rate": ["fast"], "group": ["timing", "pll"], "exp_value": (True, 0)}
        },
        'io':{
            'jesd_interface': {
                'link_status'     : {"method": obj.check_jesd_link_status, "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": True},
                'lane_error_count': {
                    'FPGA0': {
                        'Core0': {"method": partial(obj.check_jesd_lane_error_counter,fpga_id=0, core_id=0), "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0, 'lane4': 0, 'lane5': 0, 'lane6': 0, 'lane7': 0}},
                        'Core1': {"method": partial(obj.check_jesd_lane_error_counter,fpga_id=0, core_id=1), "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0, 'lane4': 0, 'lane5': 0, 'lane6': 0, 'lane7': 0}}
                    },
                    'FPGA1': {
                        'Core0': {"method": partial(obj.check_jesd_lane_error_counter,fpga_id=1, core_id=0), "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0, 'lane4': 0, 'lane5': 0, 'lane6': 0, 'lane7': 0}},
                        'Core1': {"method": partial(obj.check_jesd_lane_error_counter,fpga_id=1, core_id=1), "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0, 'lane4': 0, 'lane5': 0, 'lane6': 0, 'lane7': 0}}
                    }
                },
                'lane_status' : {"method": obj.check_jesd_lane_status, "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": True},
                'resync_count': {
                    'FPGA0': {"method": partial(obj.check_jesd_resync_counter, fpga_id=0, show_result=False), "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": 0},
                    'FPGA1': {"method": partial(obj.check_jesd_resync_counter, fpga_id=1, show_result=False), "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": 0},
                },
                'qpll_status': {
                    'FPGA0': {"method": partial(obj.check_jesd_qpll_status, fpga_id=0, show_result=False), "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": (True, 0)},
                    'FPGA1': {"method": partial(obj.check_jesd_qpll_status, fpga_id=1, show_result=False), "rate": ["fast"], "group": ["io", "jesd_interface"], "exp_value": (True, 0)},
                }
            },
            'ddr_interface': {
                'initialisation': {"method": obj.check_ddr_initialisation, "rate": ["fast"], "group": ["io", "ddr_interface"], "exp_value": True},
                'reset_counter' : {
                    'FPGA0': {"method": partial(obj.check_ddr_reset_counter, fpga_id=0, show_result=False), "rate": ["fast"], "group": ["io", "ddr_interface"], "exp_value": 0},
                    'FPGA1': {"method": partial(obj.check_ddr_reset_counter, fpga_id=1, show_result=False), "rate": ["fast"], "group": ["io", "ddr_interface"], "exp_value": 0}
                }
            },
            'f2f_interface': {
                'pll_status': {"method": partial(obj.check_f2f_pll_status, show_result=False), "rate": ["fast"], "group": ["io", "f2f_interface"], "exp_value": (True, 0)},
                'soft_error': {"method": obj.check_f2f_soft_errors,                            "rate": ["fast"], "group": ["io", "f2f_interface"], "exp_value": 0},
                'hard_error': {"method": obj.check_f2f_hard_errors,                            "rate": ["fast"], "group": ["io", "f2f_interface"], "exp_value": 0}
            },
            'udp_interface': {
                'arp'            : {"method": partial(obj.check_udp_arp_table_status, show_result=False), "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": True},
                'status'         : {"method": obj.check_udp_status,                                       "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": True},
                'crc_error_count': {
                    'FPGA0': {"method": partial(obj.check_udp_crc_error_counter, fpga_id=0), "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": 0},
                    'FPGA1': {"method": partial(obj.check_udp_crc_error_counter, fpga_id=1), "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": 0}
                },
                'bip_error_count': {
                    'FPGA0': {"method": partial(obj.check_udp_bip_error_counter, fpga_id=0), "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0}},
                    'FPGA1': {"method": partial(obj.check_udp_bip_error_counter, fpga_id=1), "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0}}
                },
                'decode_error_count': {
                    'FPGA0': {"method": partial(obj.check_udp_decode_error_counter, fpga_id=0), "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0}},
                    'FPGA1': {"method": partial(obj.check_udp_decode_error_counter, fpga_id=1), "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0}}
                },
                'linkup_loss_count': {
                    'FPGA0': {"method": partial(obj.check_udp_linkup_loss_counter, fpga_id=0, show_result=False), "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": 0},
                    'FPGA1': {"method": partial(obj.check_udp_linkup_loss_counter, fpga_id=1, show_result=False), "rate": ["fast"], "group": ["io", "udp_interface"], "exp_value": 0}
                }
            }
        },
        'dsp': {
            'tile_beamf': {"method": obj.check_tile_beamformer_status, "rate": ["fast"], "group": ["dsp", "tile_beamf"], "exp_value": True},
            'station_beamf': {
                'status'                : {"method": obj.check_station_beamformer_status, "rate": ["fast"], "group": ["dsp", "station_beamf"], "exp_value": True},
                'ddr_parity_error_count': {"method": obj.check_ddr_parity_error_counter,  "rate": ["fast"], "group": ["dsp", "station_beamf"], "exp_value": {'FPGA0': 0, 'FPGA1': 0}},
            }
        }
    }
