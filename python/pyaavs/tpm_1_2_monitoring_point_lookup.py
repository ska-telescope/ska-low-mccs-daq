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
* Subdividing monitoring points can be achieved by adding further keys
  as with rate and group. This will require minimal modification to 
  get_health_status method.
* Expected values used only for AAVS HW test suite at present.
"""

def load_tpm_1_2_lookup(obj):
    return {
        'temperatures': {
            'board': {"method": obj.get_temperature, "exp_value": 0, "rate": ["fast"], "group": ["temperatures"]},
            'FPGA0': {"method": partial(obj.get_fpga_temperature, fpga_id=0), "exp_value": 0, "rate": ["fast"], "group": ["temperatures"]},
            'FPGA1': {"method": partial(obj.get_fpga_temperature, fpga_id=1), "exp_value": 0, "rate": ["fast"], "group": ["temperatures"]}
        },
        'voltages': {
            '5V0': {"method": partial(obj.get_voltage, voltage_name='5V0'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'FPGA0_CORE': {"method": partial(obj.get_voltage, voltage_name='FPGA0_CORE'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'FPGA1_CORE': {"method": partial(obj.get_voltage, voltage_name='FPGA1_CORE'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'MGT_AV': {"method": partial(obj.get_voltage, voltage_name='MGT_AV'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'MGT_AVTT': {"method": partial(obj.get_voltage, voltage_name='MGT_AVTT'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'SW_AVDD1': {"method": partial(obj.get_voltage, voltage_name='SW_AVDD1'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'SW_AVDD2': {"method": partial(obj.get_voltage, voltage_name='SW_AVDD2'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'SW_AVDD3': {"method": partial(obj.get_voltage, voltage_name='SW_AVDD3'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VCC_AUX': {"method": partial(obj.get_voltage, voltage_name='VCC_AUX'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VIN': {"method": partial(obj.get_voltage, voltage_name='VIN'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_ADA0': {"method": partial(obj.get_voltage, voltage_name='VM_ADA0'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_ADA1': {"method": partial(obj.get_voltage, voltage_name='VM_ADA1'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_AGP0': {"method": partial(obj.get_voltage, voltage_name='VM_AGP0'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_AGP1': {"method": partial(obj.get_voltage, voltage_name='VM_AGP1'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_AGP2': {"method": partial(obj.get_voltage, voltage_name='VM_AGP2'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_AGP3': {"method": partial(obj.get_voltage, voltage_name='VM_AGP3'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_CLK0B': {"method": partial(obj.get_voltage, voltage_name='VM_CLK0B'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_DDR0_VREF': {"method": partial(obj.get_voltage, voltage_name='VM_DDR0_VREF'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_DDR0_VTT': {"method": partial(obj.get_voltage, voltage_name='VM_DDR0_VTT'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_FE0': {"method": partial(obj.get_voltage, voltage_name='VM_FE0'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_MAN1V2': {"method": partial(obj.get_voltage, voltage_name='VM_MAN1V2'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_MAN2V5': {"method": partial(obj.get_voltage, voltage_name='VM_MAN2V5'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_MAN3V3': {"method": partial(obj.get_voltage, voltage_name='VM_MAN3V3'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_MGT0_AUX': {"method": partial(obj.get_voltage, voltage_name='VM_MGT0_AUX'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_PLL': {"method": partial(obj.get_voltage, voltage_name='VM_PLL'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_ADA3': {"method": partial(obj.get_voltage, voltage_name='VM_ADA3'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_DDR1_VREF': {"method": partial(obj.get_voltage, voltage_name='VM_DDR1_VREF'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_DDR1_VTT': {"method": partial(obj.get_voltage, voltage_name='VM_DDR1_VTT'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_AGP4': {"method": partial(obj.get_voltage, voltage_name='VM_AGP4'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_AGP5': {"method": partial(obj.get_voltage, voltage_name='VM_AGP5'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_AGP6': {"method": partial(obj.get_voltage, voltage_name='VM_AGP6'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_AGP7': {"method": partial(obj.get_voltage, voltage_name='VM_AGP7'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_FE1': {"method": partial(obj.get_voltage, voltage_name='VM_FE1'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_DDR_VDD': {"method": partial(obj.get_voltage, voltage_name='VM_DDR_VDD'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_SW_DVDD': {"method": partial(obj.get_voltage, voltage_name='VM_SW_DVDD'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_MGT1_AUX': {"method": partial(obj.get_voltage, voltage_name='VM_MGT1_AUX'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_ADA2': {"method": partial(obj.get_voltage, voltage_name='VM_ADA2'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_SW_AMP': {"method": partial(obj.get_voltage, voltage_name='VM_SW_AMP'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]},
            'VM_CLK1B': {"method": partial(obj.get_voltage, voltage_name='VM_CLK1B'), "exp_value": 0, "rate": ["fast"], "group": ["voltages"]}
        },
        'currents': {
            'ACS_5V0_VI': {"method": partial(obj.get_current, current_name='ACS_5V0_VI'), "exp_value": 0, "rate": ["fast"], "group": ["currents"]},
            'ACS_FE0_VI': {"method": partial(obj.get_current, current_name='ACS_FE0_VI'), "exp_value": 0, "rate": ["fast"], "group": ["currents"]},
            'ACS_FE1_VI': {"method": partial(obj.get_current, current_name='ACS_FE1_VI'), "exp_value": 0, "rate": ["fast"], "group": ["currents"]}
        },
        'alarms': {"method": obj.check_global_status_alarms, "exp_value": 0, "rate": ["fast"], "group": ["alarms"]},
        'adcs': {
            'pll_status': {
                'ADC0': {"method": partial(obj.check_adc_pll_status, adc_id=0), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC1': {"method": partial(obj.check_adc_pll_status, adc_id=1), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC2': {"method": partial(obj.check_adc_pll_status, adc_id=2), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC3': {"method": partial(obj.check_adc_pll_status, adc_id=3), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC4': {"method": partial(obj.check_adc_pll_status, adc_id=4), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC5': {"method": partial(obj.check_adc_pll_status, adc_id=5), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC6': {"method": partial(obj.check_adc_pll_status, adc_id=6), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC7': {"method": partial(obj.check_adc_pll_status, adc_id=7), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC8': {"method": partial(obj.check_adc_pll_status, adc_id=8), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC9': {"method": partial(obj.check_adc_pll_status, adc_id=9), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC10': {"method": partial(obj.check_adc_pll_status, adc_id=10), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC11': {"method": partial(obj.check_adc_pll_status, adc_id=11), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC12': {"method": partial(obj.check_adc_pll_status, adc_id=12), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC13': {"method": partial(obj.check_adc_pll_status, adc_id=13), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC14': {"method": partial(obj.check_adc_pll_status, adc_id=14), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC15': {"method": partial(obj.check_adc_pll_status, adc_id=15), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]}
            },
            'sysref_timing_requirements': {
                'ADC0': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=0, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC1': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=1, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC2': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=2, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC3': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=3, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC4': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=4, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC5': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=5, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC6': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=6, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC7': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=7, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC8': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=8, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC9': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=9, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC10': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=10, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC11': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=11, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC12': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=12, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC13': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=13, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC14': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=14, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC15': {"method": partial(obj.check_adc_sysref_setup_and_hold, adc_id=15, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]}
            },
            'sysref_counter': {
                'ADC0': {"method": partial(obj.check_adc_sysref_counter, adc_id=0, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC1': {"method": partial(obj.check_adc_sysref_counter, adc_id=1, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC2': {"method": partial(obj.check_adc_sysref_counter, adc_id=2, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC3': {"method": partial(obj.check_adc_sysref_counter, adc_id=3, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC4': {"method": partial(obj.check_adc_sysref_counter, adc_id=4, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC5': {"method": partial(obj.check_adc_sysref_counter, adc_id=5, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC6': {"method": partial(obj.check_adc_sysref_counter, adc_id=6, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC7': {"method": partial(obj.check_adc_sysref_counter, adc_id=7, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC8': {"method": partial(obj.check_adc_sysref_counter, adc_id=8, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC9': {"method": partial(obj.check_adc_sysref_counter, adc_id=9, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC10': {"method": partial(obj.check_adc_sysref_counter, adc_id=10, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC11': {"method": partial(obj.check_adc_sysref_counter, adc_id=11, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC12': {"method": partial(obj.check_adc_sysref_counter, adc_id=12, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC13': {"method": partial(obj.check_adc_sysref_counter, adc_id=13, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC14': {"method": partial(obj.check_adc_sysref_counter, adc_id=14, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]},
                'ADC15': {"method": partial(obj.check_adc_sysref_counter, adc_id=15, show_info=False), "exp_value": 0, "rate": ["fast"], "group": ["adcs"]}
            }
        }, 
        'timing': {
            'clocks': {
                'FPGA0': {
                    'JESD': {"method": partial(obj.check_clock_status, fpga_id=0, clock_name='JESD'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clocks"]},
                    'DDR': {"method": partial(obj.check_clock_status, fpga_id=0, clock_name='DDR'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clocks"]},
                    'UDP': {"method": partial(obj.check_clock_status, fpga_id=0, clock_name='UDP'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clocks"]}
                },
                'FPGA1': {
                    'JESD': {"method": partial(obj.check_clock_status, fpga_id=1, clock_name='JESD'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clocks"]},
                    'DDR': {"method": partial(obj.check_clock_status, fpga_id=1, clock_name='DDR'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clocks"]},
                    'UDP': {"method": partial(obj.check_clock_status, fpga_id=1, clock_name='UDP'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clocks"]}
                }
            },
            'clock_managers' : {
                'FPGA0': {
                    'C2C_MMCM': {"method": partial(obj.check_clock_manager_status, fpga_id=0, name='C2C'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clock_managers"]},
                    'JESD_MMCM': {"method": partial(obj.check_clock_manager_status, fpga_id=0, name='JESD'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clock_managers"]},
                    'DSP_MMCM': {"method": partial(obj.check_clock_manager_status, fpga_id=0, name='DSP'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clock_managers"]}
                },
                'FPGA1': {
                    'C2C_MMCM': {"method": partial(obj.check_clock_manager_status, fpga_id=1, name='C2C'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clock_managers"]},
                    'JESD_MMCM': {"method": partial(obj.check_clock_manager_status, fpga_id=1, name='JESD'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clock_managers"]},
                    'DSP_MMCM': {"method": partial(obj.check_clock_manager_status, fpga_id=1, name='DSP'), "exp_value": 0, "rate": ["fast"], "group": ["timing", "clock_managers"]}
                }
            },
            'pps': {
                'status': {"method": obj.check_pps_status, "exp_value": 0, "rate": ["fast"], "group": ["timing", "pps"]}
            },
            'pll': {"method": obj.check_ad9528_pll_status, "exp_value": 0, "rate": ["fast"], "group": ["timing", "pll"]}
        },
        'io':{
            'jesd_interface': {
                'link_status': {"method": obj.check_jesd_link_status, "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]},
                'lane_error_count': {
                    'FPGA0': {
                        'Core0': {"method": partial(obj.check_jesd_lane_error_counter,fpga_id=0, core_id=0), "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]},
                        'Core1': {"method": partial(obj.check_jesd_lane_error_counter,fpga_id=0, core_id=1), "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]}
                    },
                    'FPGA1': {
                        'Core0': {"method": partial(obj.check_jesd_lane_error_counter,fpga_id=1, core_id=0), "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]},
                        'Core1': {"method": partial(obj.check_jesd_lane_error_counter,fpga_id=1, core_id=1), "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]}
                    }
                },
                'lane_status': {"method": obj.check_jesd_lane_status, "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]},
                'resync_count': {
                    'FPGA0': {"method": partial(obj.check_jesd_resync_counter, fpga_id=0, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]},
                    'FPGA1': {"method": partial(obj.check_jesd_resync_counter, fpga_id=1, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]},
                },
                'qpll_status': {
                    'FPGA0': {"method": partial(obj.check_jesd_qpll_status, fpga_id=0, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]},
                    'FPGA1': {"method": partial(obj.check_jesd_qpll_status, fpga_id=1, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "jesd_interface"]},
                }
            },
            'ddr_interface': {
                'initialisation': {"method": obj.check_ddr_initialisation, "exp_value": 0, "rate": ["fast"], "group": ["io", "ddr_interface"]},
                'reset_counter': {
                    'FPGA0': {"method": partial(obj.check_ddr_reset_counter, fpga_id=0, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "ddr_interface"]},
                    'FPGA1': {"method": partial(obj.check_ddr_reset_counter, fpga_id=1, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "ddr_interface"]}
                }
            },
            'f2f_interface': {
                'pll_status': {"method": partial(obj.check_f2f_pll_status, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "f2f_interface"]},
                'soft_error': {"method": obj.check_f2f_soft_errors, "exp_value": 0, "rate": ["fast"], "group": ["io", "f2f_interface"]},
                'hard_error': {"method": obj.check_f2f_hard_errors, "exp_value": 0, "rate": ["fast"], "group": ["io", "f2f_interface"]}
            },
            'udp_interface': {
                'arp': {"method": partial(obj.check_udp_arp_table_status, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "udp_interface"]},
                'status': {"method": obj.check_udp_status, "exp_value": 0, "rate": ["fast"], "group": ["io", "udp_interface"]},
                'crc_error_count': {
                    'FPGA0': {"method": partial(obj.check_udp_crc_error_counter, fpga_id=0), "exp_value": 0, "rate": ["fast"], "group": ["io", "udp_interface"]},
                    'FPGA1': {"method": partial(obj.check_udp_crc_error_counter, fpga_id=1), "exp_value": 0, "rate": ["fast"], "group": ["io", "udp_interface"]}
                },
                'bip_error_count': {
                    'FPGA0': {"method": partial(obj.check_udp_bip_error_counter, fpga_id=0), "exp_value": 0, "rate": ["fast"], "group": ["io", "udp_interface"]},
                    'FPGA1': {"method": partial(obj.check_udp_bip_error_counter, fpga_id=1), "exp_value": 0, "rate": ["fast"], "group": ["io", "udp_interface"]}
                },
                'linkup_loss_count': {
                    'FPGA0': {"method": partial(obj.check_udp_linkup_loss_counter, fpga_id=0, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "udp_interface"]},
                    'FPGA1': {"method": partial(obj.check_udp_linkup_loss_counter, fpga_id=1, show_result=False), "exp_value": 0, "rate": ["fast"], "group": ["io", "udp_interface"]}
                }
            }
        },
        'dsp': {
            'tile_beamf': {"method": obj.check_tile_beamformer_status, "exp_value": 0, "rate": ["fast"], "group": ["dsp", "tile_beamf"]},
            'station_beamf': {
                'status': {"method": obj.check_station_beamformer_status, "exp_value": 0, "rate": ["fast"], "group": ["dsp", "station_beamf"]},
                'ddr_parity_error_count': {"method": obj.check_ddr_parity_error_counter, "exp_value": 0, "rate": ["fast"], "group": ["dsp", "station_beamf"]},
            }
        }
    }
