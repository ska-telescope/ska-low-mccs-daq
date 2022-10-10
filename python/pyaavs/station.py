#! /usr/bin/env python
from pyaavs.slack import get_slack_instance
from pyaavs.tile_wrapper import Tile
from pyfabil import Device

from future.utils import iteritems
from multiprocessing import Pool
from threading import Thread
from builtins import input
import threading
import logging
import yaml
import time
import math
import sys
import os

# Define default configuration
configuration = {'tiles': None,
                 'time_delays': None,
                 'station': {
                     'id': 0,
                     'name': "Unnamed",
                     "number_of_antennas": 256,
                     'program': False,
                     'initialise': False,
                     'program_cpld': False,
                     'enable_test': False,
                     'start_beamformer': False,
                     'bitfile': None,
                     'channel_truncation': 5,
                     'channel_integration_time': -1,
                     'beam_integration_time': -1,
                     'equalize_preadu': 0,
                     'default_preadu_attenuation': 0,
                     'beamformer_scaling': 4,
                     'pps_delays': 0,
                     'use_internal_pps': False},
                 'observation': {
                     'bandwidth': 8 * (400e6 / 512.0),
                     'start_frequency_channel': 50e6},
                 'network': {
                     'lmc': {
                         'tpm_cpld_port': 10000,
                         'lmc_ip': "10.0.10.200",
                         'use_teng': True,
                         'lmc_port': 4660,
                         'lmc_mac': 0x248A078F9D38,
                         'integrated_data_ip': "10.0.0.2",
                         'integrated_data_port': 5000,
                         'use_teng_integrated': True},
                     'csp_ingest': {
                         'src_ip': "10.0.10.254",
                         'dst_mac': 0x248A078F9D38,
                         'src_port': None,
                         'dst_port': 4660,
                         'dst_ip': "10.0.10.200",
                         'src_mac': None}
                    }
                 }


def create_tile_instance(config, tile_number):
    """ Add a new tile to the station
    :param config: Station configuration
    :param tile_ip: TPM to associate tile to """

    # If all traffic is going through 1G then set the destination port to
    # the lmc_port. If only integrated data is going through the 1G set the
    # destination port to integrated_data_port
    dst_port = config['network']['lmc']['lmc_port']
    lmc_ip = config['network']['lmc']['lmc_ip']

    if not config['network']['lmc']['use_teng_integrated'] and \
            config['network']['lmc']['use_teng']:
        dst_port = config['network']['lmc']['integrated_data_port']
        lmc_ip = config['network']['lmc']['integrated_data_ip']

    return Tile(config['tiles'][tile_number],
                config['network']['lmc']['tpm_cpld_port'],
                lmc_ip,
                dst_port)


def program_cpld(params):
    """ Update tile CPLD.
     :param params: Contain 0) Station configuration and 1) Tile number to program CPLD """
    config, tile_number = params

    try:
        threading.current_thread().name = config['tiles'][tile_number]
        logging.info("Initialising Tile {}".format(config['tiles'][tile_number]))

        # Create station instance and program CPLD
        station_tile = create_tile_instance(config, tile_number)
        station_tile.program_cpld(config['station']['bitfile'])
        return True
    except Exception as e:
        logging.error("Could not program CPLD of {}: {}".format(config['tiles'][tile_number], e))
        return False


def program_fpgas(params):
    """ Program FPGAs
     :param params: Contain 0) Station configuration and 1) Tile number to program FPGAs """
    config, tile_number = params

    try:
        threading.current_thread().name = config['tiles'][tile_number]
        logging.info("Initialising Tile {}".format(config['tiles'][tile_number]))

        # Create station instance and program FPGAs
        station_tile = create_tile_instance(config, tile_number)
        station_tile.program_fpgas(config['station']['bitfile'])
        return True
    except Exception as e:
        logging.error("Could not program FPGAs of {}: {}".format(config['tiles'][tile_number], e))
        return False


def initialise_tile(params):
    """ Internal connect method to thread connection
     :param params: Contain 0) Station configuration and 1) Tile number to initialise """
    config, tile_number = params

    try:
        threading.current_thread().name = config['tiles'][tile_number]
        logging.info("Initialising Tile {}".format(config['tiles'][tile_number]))
        threading.current_thread().name = config['tiles'][tile_number]

        # Create station instance and initialise
        station_tile = create_tile_instance(config, tile_number)
        station_tile.initialise(
            enable_test=config['station']['enable_test'],
            use_internal_pps=config['station']['use_internal_pps']
        )

        # Set channeliser truncation
        station_tile.set_channeliser_truncation(config['station']['channel_truncation'])

        # Configure channel and beam integrated data
        station_tile.stop_integrated_data()
        if config['station']['channel_integration_time'] != -1:
            station_tile.configure_integrated_channel_data(
                config['station']['channel_integration_time'])

        if config['station']['beam_integration_time'] != -1:
            station_tile.configure_integrated_beam_data(
                config['station']['beam_integration_time'])

        return True
    except Exception as e:
        logging.warning("Could not initialise Tile {}: {}".format(config['tiles'][tile_number], e))
        return False


class Station(object):
    """ Class representing an AAVS station """

    def __init__(self, config):
        """ Class constructor
         :param config: Configuration dictionary for station """

        # Save configuration locally
        self.configuration = config
        self._station_id = config['station']['id']

        # Check if station name is specified
        self._slack = None
        if config['station']['name'] == "":
            logging.warning("Station name not defined, will be able to push notifications to Slack")
        else:
            self._slack = get_slack_instance(config['station']['name'])

        # Add tiles to station
        self.tiles = []
        for tile in config['tiles']:
            self.add_tile(tile)

        # Default duration of sleeps
        self._seconds = 1.0

        # Set if the station is properly configured
        self.properly_formed_station = None

        # Cache plugin directory
        # __import__("pyaavs.tpm_test_firmware", fromlist=[None])

    def add_tile(self, tile_ip):
        """ Add a new tile to the station
        :param tile_ip: Tile IP to be added to station """

        # If all traffic is going through 1G then set the destination port to
        # the lmc_port. If only integrated data is going through the 1G set the
        # destination port to integrated_data_port
        dst_port = self.configuration['network']['lmc']['lmc_port']
        lmc_ip = self.configuration['network']['lmc']['lmc_ip']

        if not self.configuration['network']['lmc']['use_teng_integrated'] and \
                self.configuration['network']['lmc']['use_teng']:
            dst_port = self.configuration['network']['lmc']['integrated_data_port']
            lmc_ip = self.configuration['network']['lmc']['integrated_data_ip']

        self.tiles.append(Tile(tile_ip,
                               self.configuration['network']['lmc']['tpm_cpld_port'],
                               lmc_ip,
                               dst_port))

    def connect(self):
        """ Initialise all tiles """

        # Start with the assumption that the station will be properly formed
        self.properly_formed_station = True

        # Create a pool of nof_tiles processes
        pool = None
        if any([self.configuration['station']['program_cpld'],
                self.configuration['station']['program'],
                self.configuration['station']['initialise']]):
            pool = Pool(len(self.tiles))

        # Create parameters for processes
        params = tuple([(self.configuration, i) for i in range(len(self.tiles))])

        # Check if we are programming the CPLD, and if so program
        if self.configuration['station']['program_cpld']:
            logging.info("Programming CPLD")
            self._slack.info("CPLD is being updated for tiles: {}".format(self.tiles))
            res = pool.map(program_cpld, params)

            if not all(res):
                logging.error("Could not program TPM CPLD!")
                self.properly_formed_station = False

        # Check if programming is required, and if so program
        if self.configuration['station']['program'] and self.properly_formed_station:
            logging.info("Programming tiles")
            self._slack.info("Station is being programmed")
            res = pool.map(program_fpgas, params)

            if not all(res):
                logging.error("Could not program tiles!")
                self.properly_formed_station = False

        # Check if initialisation is required, and if so initialise
        if self.configuration['station']['initialise'] and self.properly_formed_station:
            logging.info("Initialising tiles")
            self._slack.info("Station is being initialised")
            res = pool.map(initialise_tile, params)

            if not all(res):
                logging.error("Could not initialise tiles!")
                self.properly_formed_station = False

        # Ready from pool
        if pool is not None:
            pool.terminate()

        # Connect all tiles
        for tile in self.tiles:
            tile.connect()

        # Initialise if required
        if self.configuration['station']['initialise'] and self.properly_formed_station:
            logging.info("Forming station")
            self._form_station()

            logging.info("Setting time domain delays")
            if self.configuration['time_delays'] is not None:
                if len(self.configuration['time_delays']) != len(self.tiles):
                    logging.warning("Incorrect number of time delays specified, must match number of TPMs. Ignoring")
                else:
                    for i, tile in enumerate(self.tiles):
                        logging.info(
                            "Setting a delay of {}ns to tile {}".format(self.configuration['time_delays'][i], i))
                        tile.set_time_delays(self.configuration['time_delays'][i])

            logging.info("Initializing tile and station beamformer")
            start_channel = int(round(self.configuration['observation']['start_frequency_channel'] / (400e6 / 512.0)))
            nof_channels = max(int(round(self.configuration['observation']['bandwidth'] / (400e6 / 512.0))), 8)

            if self.configuration['station']['start_beamformer']:
                logging.info("Station beamformer enabled")
                self._slack.info("Station beamformer enabled with start frequency {:.2f} MHz and bandwidth {:.2f} MHz".format(
                    self.configuration['observation']['start_frequency_channel'] * 1e-6,
                    self.configuration['observation']['bandwidth'] * 1e-6))

            if self.tiles[0].tpm.tpm_test_firmware[0].tile_beamformer_implemented and self.tiles[0].tpm.tpm_test_firmware[0].station_beamformer_implemented:
                for i, tile in enumerate(self.tiles):
                    # Initialise beamformer
                    tile.initialise_beamformer(start_channel, nof_channels, i == 0, i == len(self.tiles) - 1)

                    # Define SPEAD header
                    # TODO: Insert proper values here
                    if i == len(self.tiles) - 1:
                        tile.define_spead_header(self._station_id, 0, self.configuration['station']['number_of_antennas'],
                                                 -1, 0)

                    # Start beamformer
                    if self.configuration['station']['start_beamformer']:
                        logging.info("Starting station beamformer")
                        tile.start_beamformer(start_time=0, duration=-1)

                        # Set beamformer scaling
                        for t in self.tiles:
                            t.tpm.station_beamf[0].set_csp_rounding(self.configuration['station']['beamformer_scaling'])
                            t.tpm.station_beamf[1].set_csp_rounding(self.configuration['station']['beamformer_scaling'])

            # for tile in self.tiles:
            #     tile.tpm.tpm_pattern_generator[0].initialise()
            #     tile.tpm.tpm_pattern_generator[1].initialise()

            # If in testing mode, override tile-specific test generators
            if self.configuration['station']['enable_test']:
                for tile in self.tiles:
                    for gen in tile.tpm.test_generator:
                        gen.channel_select(0x0000)
                        gen.disable_prdg()

                for tile in self.tiles:
                    for gen in tile.tpm.test_generator:
                        gen.set_tone(0, 100 * 800e6 / 1024, 1)
                        gen.set_tone(1, 100 * 800e6 / 1024, 0)
                        gen.channel_select(0xFFFF)

            if self['fpga1.regfile.feature.xg_eth_implemented'] == 1:
                for tile in self.tiles:
                    tile.reset_eth_errors()
                time.sleep(1)
                for tile in self.tiles:
                    tile.check_arp_table()

            # If initialising, synchronise all tiles in station
            logging.info("Synchronising station")
            self._station_post_synchronisation()
            self._synchronise_tiles(self.configuration['network']['lmc']['use_teng'])

            # Setting PREADU values
            att_value = self.configuration['station']['default_preadu_attenuation']
            if not (self.configuration['station']['enable_test'] or att_value == -1):
                # Set default preadu attenuation
                time.sleep(1)
                logging.info("Setting default PREADU attenuation to {}".format(att_value))
                self.set_preadu_attenuation(att_value)

                # If equalization is required, do it
                if self.configuration['station']['equalize_preadu'] != 0:
                    logging.info("Equalizing PREADU signals")
                    self.equalize_preadu_gain(self.configuration['station']['equalize_preadu'])

        elif not self.properly_formed_station:
            logging.warning("Some tiles were not initialised or programmed. Not forming station")

        # If not initialising, check that station is formed properly
        else:
            self.check_station_status()

    def check_station_status(self):
        """ Check that the station is still valid """
        tile_ids = []
        for tile in self.tiles:
            if tile.tpm is None:
                self.properly_formed_station = False
                break

            tile_id = tile.get_tile_id()
            if tile.get_tile_id() < len(self.tiles) and tile_id not in tile_ids:
                tile_ids.append(tile_id)
            else:
                self.properly_formed_station = False
                break

        if not self.properly_formed_station:
            logging.warning("Station configuration is incorrect (unreachable TPMs or incorrect tile ids)!")

    def equalize_preadu_gain(self, required_rms=20):
        """ Equalize the preadu gain to get target RMS"""

        self._slack.info("Station gains are being equalized to ADU RMS {}".format(required_rms))

        preadu_signal_map = {0: {'preadu_id': 1, 'channel': 14},
                             1: {'preadu_id': 1, 'channel': 15},
                             2: {'preadu_id': 1, 'channel': 12},
                             3: {'preadu_id': 1, 'channel': 13},
                             4: {'preadu_id': 1, 'channel': 10},
                             5: {'preadu_id': 1, 'channel': 11},
                             6: {'preadu_id': 1, 'channel': 8},
                             7: {'preadu_id': 1, 'channel': 9},
                             8: {'preadu_id': 0, 'channel': 0},
                             9: {'preadu_id': 0, 'channel': 1},
                             10: {'preadu_id': 0, 'channel': 2},
                             11: {'preadu_id': 0, 'channel': 3},
                             12: {'preadu_id': 0, 'channel': 4},
                             13: {'preadu_id': 0, 'channel': 5},
                             14: {'preadu_id': 0, 'channel': 6},
                             15: {'preadu_id': 0, 'channel': 7},
                             16: {'preadu_id': 1, 'channel': 6},
                             17: {'preadu_id': 1, 'channel': 7},
                             18: {'preadu_id': 1, 'channel': 4},
                             19: {'preadu_id': 1, 'channel': 5},
                             20: {'preadu_id': 1, 'channel': 2},
                             21: {'preadu_id': 1, 'channel': 3},
                             22: {'preadu_id': 1, 'channel': 0},
                             23: {'preadu_id': 1, 'channel': 1},
                             24: {'preadu_id': 0, 'channel': 8},
                             25: {'preadu_id': 0, 'channel': 9},
                             26: {'preadu_id': 0, 'channel': 10},
                             27: {'preadu_id': 0, 'channel': 11},
                             28: {'preadu_id': 0, 'channel': 12},
                             29: {'preadu_id': 0, 'channel': 13},
                             30: {'preadu_id': 0, 'channel': 14},
                             31: {'preadu_id': 0, 'channel': 15}}

        # Loop over all tiles
        for tt, tile in enumerate(self.tiles):

            # Get current preadu settings
            for preadu in tile.tpm.tpm_preadu:
                preadu.select_low_passband()
                preadu.read_configuration()

            # Get current RMS
            rms = tile.get_adc_rms()

            # Loop over all signals
            for channel in list(preadu_signal_map.keys()):
                # Calculate required attenuation difference
                if rms[channel] / required_rms > 0:
                    attenuation = 20 * math.log10(rms[channel] / required_rms)
                else:
                    attenuation = 0

                # Apply attenuation
                pid = preadu_signal_map[channel]['preadu_id']
                channel = preadu_signal_map[channel]['channel']

                attenuation = (tile.tpm.tpm_preadu[pid].channel_filters[channel] >> 3) + attenuation
                tile.tpm.tpm_preadu[pid].set_attenuation(int(round(attenuation)), [channel])

            for preadu in tile.tpm.tpm_preadu:
                preadu.write_configuration()

        logging.info("Equalized station")

    def set_preadu_attenuation(self, attenuation):
        """ Set same preadu attenuation in all preadus """

        self._slack.info("Station attenuations are being set to {}".format(attenuation))

        # Loop over all tiles
        for tile in self.tiles:

            # Get current preadu settings
            for preadu in tile.tpm.tpm_preadu:
                preadu.select_low_passband()
                preadu.read_configuration()
                preadu.set_attenuation(int(round(attenuation)), list(range(16)))
                preadu.write_configuration()

    def _form_station(self):
        """ Forms the station """

        # Assign station and tile id, and tweak transceivers
        for i, tile in enumerate(self.tiles):
            tile.set_station_id(self._station_id, i)
            tile.tweak_transceivers()

        #if self.tiles[0]['fpga1.regfile.feature.xg_eth_implemented'] == 0:
        #    for tile in self.tiles:
        #        tile['fpga1.regfile.reset.eth10g_rst'] = 0
        #        tile['fpga2.regfile.reset.eth10g_rst'] = 0
        #        tile['fpga1.regfile.reset.eth10g_rst'] = 1
        #        tile['fpga2.regfile.reset.eth10g_rst'] = 1
        #        tile['fpga1.regfile.reset.eth10g_rst'] = 0
        #        tile['fpga2.regfile.reset.eth10g_rst'] = 0

        # Loop over tiles and configure 10g cores
        # Note that 10G lanes already have a correct source IP, MAC and port,
        # all that is required is to change their destination parameters

        # Loop over tiles and configure 10g cores
        if len(self.tiles) > 1:
            # Chain up TPMs
            for i in range(len(self.tiles) - 1):
                for core_id in range(len(self.tiles[0].tpm.tpm_10g_core)):
                    if self.tiles[0].tpm.tpm_test_firmware[0].xg_40g_eth:
                        next_tile_config = self.tiles[i + 1].get_40g_core_configuration(core_id)
                        self.tiles[i].configure_40g_core(core_id, 0,
                                                         dst_ip=next_tile_config['src_ip'])
                    else:
                        next_tile_config = self.tiles[i + 1].get_10g_core_configuration(core_id)
                        self.tiles[i].configure_10g_core(core_id,
                                                         dst_mac=next_tile_config['src_mac'],
                                                         dst_ip=next_tile_config['src_ip'])

        # Create initialise configuration
        csp_ingest_network = {}
        for core_id in range(len(self.tiles[0].tpm.tpm_10g_core)):
            csp_ingest_network[core_id] = {'dst_mac': self.configuration['network']['csp_ingest']['dst_mac'],
                                           'dst_ip': self.configuration['network']['csp_ingest']['dst_ip'],
                                           'dst_port': self.configuration['network']['csp_ingest']['dst_port'],
                                           'src_mac': self.configuration['network']['csp_ingest']['src_mac'],
                                           'src_ip': self.configuration['network']['csp_ingest']['src_ip'],
                                           'src_port': self.configuration['network']['csp_ingest']['src_port']}

        # For the last TPM, if CSP ingest parameters are not specified for the lanes
        # loop them back to the first TPM in the chain
        for core_id in range(len(self.tiles[0].tpm.tpm_10g_core)):
            if csp_ingest_network[core_id]['dst_ip'] == "0.0.0.0":
                next_tile_config = self.tiles[0].get_10g_core_configuration(core_id)
                if self.tiles[0].tpm.tpm_test_firmware[0].xg_40g_eth:
                    self.tiles[-1].configure_40g_core(core_id, 0,
                                                      dst_ip=next_tile_config['src_ip'])
                else:
                    self.tiles[-1].configure_10g_core(core_id,
                                                      dst_mac=next_tile_config['src_mac'],
                                                      dst_ip=next_tile_config['src_ip'])

            else:
                if self.tiles[0].tpm.tpm_test_firmware[0].xg_40g_eth:
                    self.tiles[-1].configure_40g_core(core_id, 0,
                                                      dst_ip=csp_ingest_network[core_id]['dst_ip'],
                                                      dst_port=csp_ingest_network[core_id]['dst_port'],
                                                      src_mac=csp_ingest_network[core_id]['src_mac'],
                                                      src_ip=csp_ingest_network[core_id]['src_ip'],
                                                      src_port=csp_ingest_network[core_id]['src_port'])
                else:
                    self.tiles[-1].configure_10g_core(core_id,
                                                      dst_mac=csp_ingest_network[core_id]['dst_mac'],
                                                      dst_ip=csp_ingest_network[core_id]['dst_ip'],
                                                      dst_port=csp_ingest_network[core_id]['dst_port'],
                                                      src_mac=csp_ingest_network[core_id]['src_mac'],
                                                      src_ip=csp_ingest_network[core_id]['src_ip'],
                                                      src_port=csp_ingest_network[core_id]['src_port'])

    def _synchronise_tiles(self, use_teng=False):
        """ Synchronise time on all tiles """

        pps_detect = self['fpga1.pps_manager.pps_detected']
        logging.debug("FPGA1 PPS detection register is ({})".format(pps_detect))
        pps_detect = self['fpga2.pps_manager.pps_detected']
        logging.debug("FPGA2 PPS detection register is ({})".format(pps_detect))

        # Repeat operation until Tiles are synchronised
        while True:
            # Read the current time on first tile
            self.tiles[0].wait_pps_event()

            # PPS edge detected, write time to all tiles
            curr_time = self.tiles[0].get_fpga_time(Device.FPGA_1)
            logging.info("Synchronising tiles in station with time %d" % curr_time)

            for tile in self.tiles:
                tile.set_fpga_time(Device.FPGA_1, curr_time)
                tile.set_fpga_time(Device.FPGA_2, curr_time)

            # All done, check that PPS on all boards are the same
            self.tiles[0].wait_pps_event()

            times = set()
            for tile in self.tiles:
                times.add(tile.get_fpga_time(Device.FPGA_1))
                times.add(tile.get_fpga_time(Device.FPGA_2))

            if len(times) == 1:
                break

        # Tiles synchronised
        curr_time = self.tiles[0].get_fpga_time(Device.FPGA_1)
        logging.info("Tiles in station synchronised, time is %d" % curr_time)

        # Set LMC data lanes
        for tile in self.tiles:
            # Configure standard data streams
            if use_teng:
                logging.info("Using 10G for LMC traffic")
                tile.set_lmc_download("10g", 8192,
                                      dst_ip=self.configuration['network']['lmc']['lmc_ip'],
                                      dst_port=self.configuration['network']['lmc']['lmc_port'],
                                      lmc_mac=self.configuration['network']['lmc']['lmc_mac'])
            else:
                # Configure integrated data streams
                logging.info("Using 1G for LMC traffic")
                tile.set_lmc_download("1g")

            # Configure integrated data streams
            if self.configuration['network']['lmc']['use_teng_integrated']:
                logging.info("Using 10G for integrated LMC traffic")
                tile.set_lmc_integrated_download("10g", 1024, 2048,
                                                 dst_ip=self.configuration['network']['lmc']['lmc_ip'],
                                                 lmc_mac=self.configuration['network']['lmc']['lmc_mac'])
            else:
                # Configure integrated data streams
                logging.info("Using 1G for integrated LMC traffic")
                tile.set_lmc_integrated_download("1g", 1024, 2048)
                
        if self.tiles[0]['fpga1.regfile.feature.xg_eth_implemented'] == 0:
            logging.info("Waiting for 10G Ethernet link...")
            time.sleep(5)
        else:
            for tile in self.tiles:
                tile.check_arp_table()

        # Start data acquisition on all boards
        delay = 2
        t0 = self.tiles[0].get_fpga_time(Device.FPGA_1)
        for tile in self.tiles:
            tile.start_acquisition(start_time=t0, delay=delay)

        t1 = self.tiles[0].get_fpga_time(Device.FPGA_1)
        if t0 + delay > t1:
            logging.info("Waiting for start acquisition")
            while self.tiles[0]['fpga1.dsp_regfile.stream_status.channelizer_vld'] == 0:
                time.sleep(0.1)
        else:
            logging.error("Start data acquisition not synchronised! Rerun initialisation")
            exit()

    def _station_post_synchronisation(self):
        """ Post tile configuration synchronization """

        pps_delays = [0] * len(self.tiles)
        if self.configuration['station'].get('pps_delays', None) is not None:
            logging.info("Loading PPS delays")
            if type(self.configuration['station']['pps_delays']) is int:
                pps_delays = [self.configuration['station']['pps_delays']] * len(self.tiles)
            elif len(self.configuration['station']['pps_delays']) != len(self.tiles):
                logging.warning("Incorrect number of pps delays specified, must match number of TPMs. Ignoring")
            else:
                pps_delays = self.configuration['station']['pps_delays']

        for tile in self.tiles:
            tile['fpga1.pps_manager.sync_cnt_enable'] = 0x7
            tile['fpga2.pps_manager.sync_cnt_enable'] = 0x7
        time.sleep(0.2)
        for tile in self.tiles:
            tile['fpga1.pps_manager.sync_cnt_enable'] = 0x0
            tile['fpga2.pps_manager.sync_cnt_enable'] = 0x0

        # Station synchronisation loop
        sync_loop = 0
        max_sync_loop = 5
        while sync_loop < max_sync_loop:
            self.tiles[0].wait_pps_event()

            current_tc = [tile.get_phase_terminal_count() for tile in self.tiles]
            delay = [tile.get_pps_delay() for tile in self.tiles]
            from operator import add
            delay = list(map(add, delay, pps_delays))

            for n in range(len(self.tiles)):
                self.tiles[n].set_phase_terminal_count(self.tiles[n].calculate_delay(delay[n], current_tc[n], 16, 24))

            self.tiles[0].wait_pps_event()

            current_tc = [tile.get_phase_terminal_count() for tile in self.tiles]
            delay = [tile.get_pps_delay() for tile in self.tiles]

            for n in range(len(self.tiles)):
                self.tiles[n].set_phase_terminal_count(self.tiles[n].calculate_delay(delay[n], current_tc[n],
                                                                                     delay[0] - 4, delay[0] + 4))

            self.tiles[0].wait_pps_event()

            delay = [tile.get_pps_delay() for tile in self.tiles]
            delay = list(map(add, delay, pps_delays))

            synced = 1
            for n in range(len(self.tiles) - 1):
                if abs(delay[0] - delay[n + 1]) > 4:
                    logging.warning("Resynchronizing station ({})".format(delay))
                    sync_loop += 1
                    synced = 0

            if synced == 1:
                phase1 = [hex(tile['fpga1.pps_manager.sync_phase']) for tile in self.tiles]
                phase2 = [hex(tile['fpga2.pps_manager.sync_phase']) for tile in self.tiles]
                logging.debug("Final FPGA1 clock phase ({})".format(phase1))
                logging.debug("Final FPGA2 clock phase ({})".format(phase2))

                logging.info("Finished station post synchronisation ({})".format(delay))
                return delay

        logging.error("Station post synchronisation failed!")

    # ------------------------------------------------------------------------------------------------
    def test_generator_set_tone(self, dds, frequency=100e6, ampl=0.0, phase=0.0, delay=512):
        t0 = self.tiles[0]["fpga1.pps_manager.timestamp_read_val"] + delay
        for tile in self.tiles:
            for gen in tile.tpm.test_generator:
                gen.set_tone(dds, frequency, ampl, phase, t0)
        t1 = self.tiles[0]["fpga1.pps_manager.timestamp_read_val"]
        if t1 > t0:
            logging.info("Set tone test pattern generators synchronisation failed.")

    def test_generator_disable_tone(self, dds, delay=512):
        t0 = self.tiles[0]["fpga1.pps_manager.timestamp_read_val"] + delay
        for tile in self.tiles:
            for gen in tile.tpm.test_generator:
                gen.set_tone(dds, 0, 0, 0, t0)
        t1 = self.tiles[0]["fpga1.pps_manager.timestamp_read_val"]
        if t1 > t0:
            logging.info("Set tone test pattern generators synchronisation failed.")

    def test_generator_set_noise(self, ampl=0.0, delay=512):
        t0 = self.tiles[0]["fpga1.pps_manager.timestamp_read_val"] + delay
        for tile in self.tiles:
            for gen in tile.tpm.test_generator:
                gen.enable_prdg(ampl, t0)
        t1 = self.tiles[0]["fpga1.pps_manager.timestamp_read_val"]
        if t1 > t0:
            logging.info("Set tone test pattern generators synchronisation failed.")

    def test_generator_input_select(self, inputs):
        for tile in self.tiles:
            tile.test_generator[0].channel_select(inputs & 0xFFFF)
            tile.test_generator[1].channel_select((inputs >> 16) & 0xFFFF)

    def enable_beamformer_test_pattern(self, nof_tiles=16):
        """ Enable beamformer test pattern """
        for tile in self.tiles:
            log2_tiles = int(math.log(nof_tiles, 2))
            tile.tpm.tpm_pattern_generator[0].start_pattern("beamf")
            tile.tpm.tpm_pattern_generator[1].start_pattern("beamf")
            tile['fpga1.pattern_gen.beamf_left_shift'] = 4 - log2_tiles
            tile['fpga2.pattern_gen.beamf_left_shift'] = 4 - log2_tiles
            tile['fpga1.beamf_ring.csp_scaling'] = 4
            tile['fpga2.beamf_ring.csp_scaling'] = 4
            tile.tpm.tpm_pattern_generator[0].set_signal_adder([0] * 64, "beamf")
            tile.tpm.tpm_pattern_generator[1].set_signal_adder([1] * 64, "beamf")

    def disable_beamformer_test_pattern(self):
        """ Enable beamformer test pattern """
        for tile in self.tiles:
            tile.tpm.tpm_pattern_generator[0].stop_pattern("beamf")
            tile.tpm.tpm_pattern_generator[1].stop_pattern("beamf")

    def enable_channeliser_test_pattern(self):
        """ Enable beamformer test pattern """
        for tile in self.tiles:
            tile.tpm.tpm_pattern_generator[0].start_pattern("channel")
            tile.tpm.tpm_pattern_generator[1].start_pattern("channel")

    def stop_channeliser_test_pattern(self):
        """ Enable beamformer test pattern """
        for tile in self.tiles:
            tile.tpm.tpm_pattern_generator[0].stop_pattern("channel")
            tile.tpm.tpm_pattern_generator[1].stop_pattern("channel")

    # ------------------------------------------------------------------------------------------------

    def mii_test(self, pkt_num, show_result=True):
        """ Perform mii test """

        for i, tile in enumerate(self.tiles):
            logging.debug("MII test setting Tile " + str(i))
            tile.mii_prepare_test(i + 1)

        for i, tile in enumerate(self.tiles):
            logging.debug("MII test starting Tile " + str(i))
            tile.mii_exec_test(pkt_num, wait_result=False)

        if not show_result:
            return

        while True:
            for i, tile in enumerate(self.tiles):
                logging.debug("Tile " + str(i) + " MII test result:")
                tile.mii_show_result()
                k = input("Enter quit to exit. Any other key to continue.")
                if k == "quit":
                    return

    def enable_adc_trigger(self, threshold=127):
        """ Enable ADC trigger to send raw data when an RMS threshold is reached"""

        if 0 > threshold > 127:
            logging.error("Invalid threshold, must be 1 - 127")
            return

        # Enable trigger
        station['fpga1.lmc_gen.raw_ext_trigger_enable'] = 1
        station['fpga2.lmc_gen.raw_ext_trigger_enable'] = 1

        # Set threshold
        for tile in self.tiles:
            for adc in tile.tpm.tpm_adc:
                adc.adc_set_fast_detect(threshold << 6)

    @staticmethod
    def disable_adc_trigger():
        """ Disable ADC trigger """
        station['fpga1.lmc_gen.raw_ext_trigger_enable'] = 0
        station['fpga2.lmc_gen.raw_ext_trigger_enable'] = 0

    def cycle_preadu_attenuation(self, delay=60):
        """ Cycle through PREADU attenuation """
        for attenuation in range(31, 0, -1):
            logging.info("Setting attenuation to {}".format(attenuation))

            # Loop over all tiles
            for tile in self.tiles:

                # Get current preadu settings
                for preadu in tile.tpm.tpm_preadu:
                    preadu.select_low_passband()
                    #  preadu.read_configuration()

                    #  attenuation = (tile.tpm.tpm_preadu[i / 16].channel_filters[i % 16] >> 3) + att
                    preadu.set_attenuation(int(round(attenuation)))
                    preadu.write_configuration()
            time.sleep(delay)

    # --------------------------------- CALIBRATION OPERATIONS ---------------------------------------
    def calibrate_station(self, coefficients, switch_time=2048):
        """Coefficients is a 3D complex array of the form [antenna, channel, polarization], with each 
            element representing a  normalized coefficient, with (1.0, 0.0) the normal, expected response 
            for an ideal antenna. Antenna is the index specifying the antenna within the index (using 
            correlator indexing). Channel is the index specifying the channels at the beamformer output, 
            i.e. considering only those channels actually processed and beam assignments. The polarization 
            index ranges from 0 to 3.
            0: X polarization direct element
            1: X->Y polarization cross element
            2: Y->X polarization cross element
            3: Y polarization direct element"""

        # Check that we have the correct coefficients shape 
        nof_channels = int(round(self.configuration['observation']['bandwidth'] / (400e6 / 512.0)))
        if coefficients.shape != (len(self.tiles) * 16, nof_channels, 4):
            logging.error("Coefficients shape mismatch. Should be ({},{},4), is ({}). Not calibrating".format(
                len(self.tiles) * 16, nof_channels, coefficients.shape))
            return

        t0 = time.time()

        # Download coefficients
        for i, tile in enumerate(self.tiles):
            for antenna in range(16):
                tile.load_calibration_coefficients(antenna,
                                                   coefficients[i * 16 + antenna, :, :].tolist())

        t1 = time.time()
        logging.info("Downloaded coefficients to tiles in {0:.2}s".format(t1 - t0))

        # Done downloading coefficient, switch calibration bank
        self.switch_calibration_banks(switch_time)
        self._slack.info("Calibration coefficients loaded to station")
        logging.info("Switched calibration banks")

    def switch_calibration_banks(self, switch_time=0):
        """ Switch calibration bank on all tiles"""

        if switch_time == 0:
            switch_time = self.tiles[0].current_tile_beamformer_frame() + 64
        else:
            switch_time = self.tiles[0].current_tile_beamformer_frame() + switch_time

        # Switch calibration bank on all tiles
        for tile in self.tiles:
            tile.beamf_fd[0].switch_calibration_bank(switch_time)
            tile.beamf_fd[1].switch_calibration_bank(switch_time)

        if switch_time < self.tiles[0].current_tile_beamformer_frame():
            logging.warning("Calibration switching not synchronised!")

    def load_pointing_delay(self, load_time=0):
        """ Load pointing delays on all tiles """
        if load_time == 0:
            load_time = self.tiles[0].current_tile_beamformer_frame() + 64
        else:
            load_time = self.tiles[0].current_tile_beamformer_frame() + load_time

        # Load pointing delays
        for tile in self.tiles:
            tile.tpm.beamf_fd[0].load_delay(load_time)
            tile.tpm.beamf_fd[1].load_delay(load_time)

        if load_time < self.tiles[0].current_tile_beamformer_frame():
            logging.warning("Delay loading not synchronised!")

        self._slack.info("Pointing delays loaded to station")

    # ------------------------------------ DATA OPERATIONS -------------------------------------------

    def send_raw_data(self, sync=False, period=0, timeout=0):
        """ Send raw data from all Tiles """
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_raw_data(sync=sync, period=period, timeout=timeout, timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_raw_data_synchronised(self, period=0, timeout=0):
        """ Send synchronised raw data from all Tiles """
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_raw_data_synchronised(period=period, timeout=timeout, timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_channelised_data(self, number_of_samples=1024, first_channel=0, last_channel=511, period=0, timeout=0):
        """ Send channelised data from all Tiles """
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_channelised_data(number_of_samples=number_of_samples, first_channel=first_channel,
                                       last_channel=last_channel, period=period,
                                       timeout=timeout, timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_beam_data(self, period=0, timeout=0):
        """ Send beam data from all Tiles """
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_beam_data(period=period, timeout=timeout, timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_csp_data(self, samples_per_packet, number_of_samples):
        """ Send CSP data from all Tiles """
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_csp_data(samples_per_packet=samples_per_packet, number_of_samples=number_of_samples,
                               timestamp=t0, seconds=0.5)
        return self._check_data_sync(t0)

    def send_channelised_data_continuous(self, channel_id, number_of_samples=65536, timeout=0):
        """ Send continuous channelised data from all Tiles """
        self.stop_data_transmission()
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_channelised_data_continuous(channel_id=channel_id, number_of_samples=number_of_samples,
                                                  timeout=timeout, timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_channelised_data_narrowband(self, frequency, round_bits, number_of_samples=256, timeout=0):
        """ Send narrowband continuous channel data """
        # Check if feature is available
        if len(self.tiles[0].find_register("fpga1.lmc_gen.channelized_ddc_mode")) == 0:
            logging.warning("Downloaded firwmare does not support narrowband channels")
            return

        self.stop_data_transmission()
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_channelised_data_narrowband(frequency=frequency, round_bits=round_bits,
                                                  number_of_samples=number_of_samples,
                                                  timeout=timeout, timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def stop_data_transmission(self):
        """ Stop data transmission """
        logging.info("Stopping data transmission")
        for tile in self.tiles:
            tile.stop_data_transmission()

    def stop_integrated_data(self):
        """ Stop integrated data transmission """
        for tile in self.tiles:
            tile.stop_integrated_data()

    def _wait_available(self):
        """ Make sure all boards can send data """
        while any([tile.check_pending_data_requests() for tile in self.tiles]):
            logging.info("Waiting for pending data requests to finish")
            time.sleep(0.1)

    def _check_data_sync(self, t0):
        """ Check whether data synchronisation worked """
        delay = self._seconds * (1 / (1080 * 1e-9) / 256)
        timestamps = [tile.get_fpga_timestamp(Device.FPGA_1) for tile in self.tiles]
        logging.debug("Data sync check: timestamp={}, delay={}".format(str(timestamps), delay))
        return all([(t0 + delay) > t1 for t1 in timestamps])

    def test_wr_exec(self):
        import time
        start = time.time()
        ba = self.tiles[0].tpm.register_list['%s.pattern_gen.%s_data' % ('fpga1', "beamf")]['address']

        for n in range(1024):
            self.tiles[0][ba] = list(range(256))

        end = time.time()
        logging.debug("test_wr_exec: {}".format((end - start)))

    # ------------------------------------------- TEST FUNCTIONS ---------------------------------------

    def test_rd_exec(self):
        import time
        start = time.time()
        ba = self.tiles[0].tpm.register_list['%s.pattern_gen.%s_data' % ('fpga1', "beamf")]['address']

        for n in range(1024):
            self.tiles[0].tpm.read_register(ba, n=256)

        end = time.time()
        logging.debug("test_rd_exec: {}".format((end - start)))

    def err_reset(self):
        self['fpga1.dsp_regfile.error_clear'] = 0xFFFFFFFF
        self['fpga1.dsp_regfile.error_clear'] = 0x0
        self['fpga2.dsp_regfile.error_clear'] = 0xFFFFFFFF
        self['fpga2.dsp_regfile.error_clear'] = 0x0
        self['fpga1.beamf_ring.control.error_rst'] = 1
        self['fpga1.beamf_ring.control.error_rst'] = 0
        self['fpga2.beamf_ring.control.error_rst'] = 1
        self['fpga2.beamf_ring.control.error_rst'] = 0
        self['fpga1.regfile.eth10g_error'] = 0
        self['fpga2.regfile.eth10g_error'] = 0

    def error_check(self):
        logging.debug(self['fpga1.dsp_regfile.error_detected'])
        logging.debug(self['fpga2.dsp_regfile.error_detected'])
        logging.debug(self['fpga1.beamf_ring.error'])
        logging.debug(self['fpga2.beamf_ring.error'])
        logging.debug(self['fpga1.regfile.eth10g_error'])
        logging.debug(self['fpga2.regfile.eth10g_error'])

    def ddr3_check(self):
        try:
            while True:
                for n in range(len(self.tiles)):
                    if (self.tiles[n]['fpga1.ddr3_if.status'] & 0x100) != 256:
                        logging.info("Tile" + str(n) + " FPGA1 DDR Error Detected!")
                        logging.info(hex(self.tiles[n]['fpga1.ddr3_if.status']))
                        logging.info(time.asctime(time.localtime(time.time())))
                        time.sleep(5)

                    if (self.tiles[n]['fpga2.ddr3_if.status'] & 0x100) != 256:
                        logging.info("Tile" + str(n) + " FPGA2 DDR Error Detected!")
                        logging.info(hex(self.tiles[n]['fpga2.ddr3_if.status']))
                        logging.info(localtime=time.asctime(time.localtime(time.time())))
                        time.sleep(5)
        except KeyboardInterrupt:
            pass

    @staticmethod
    def check_adc_sysref():
        for adc in range(16):
            error = 0
            values = station['adc' + str(adc), 0x128]
            for i in range(len(values)):
                msb = (values[i] & 0xF0) >> 4
                lsb = (values[i] & 0x0F) >> 0
                if msb == 0 and lsb <= 7:
                    logging.warning('Possible setup error in tile %d adc %d' % (i, adc))
                    error = 1
                if msb >= 9 and lsb == 0:
                    logging.warning('Possible hold error in tile %d adc %d' % (i, adc))
                    error = 1
                if msb == 0 and lsb == 0:
                    logging.warning('Possible setup and hold error in tile %d adc %d' % (i, adc))
                    error = 1
            if error == 0:
                logging.debug('ADC %d sysref OK!' % adc)

    # ------------------------------------------- OVERLOADED FUNCTIONS ---------------------------------------

    def __getitem__(self, key):
        """ Read register across all tiles """
        return [tile.tpm[key] for tile in self.tiles]

    def __setitem__(self, key, value):
        """ Write register across all tiles """
        for tile in self.tiles:
            tile.tpm[key] = value


def apply_config_file(input_dict, output_dict):
    """ Recursively copy value from input_dict to output_dict"""
    for k, v in iteritems(input_dict):
        if type(v) is dict:
            apply_config_file(v, output_dict[k])
        elif k not in list(output_dict.keys()):
            logging.warning("{} not a valid configuration item. Skipping".format(k))
        else:
            output_dict[k] = v


def load_configuration_file(filepath):
    """ Load station configuration from configuration file """
    if filepath is not None:
        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            logging.error("Specified configuration file ({}) does not exist. Exiting".format(filepath))
            exit()

        # Configuration file defined, load and update default configuration
        with open(filepath, 'r') as f:
            c = yaml.load(f, Loader=yaml.FullLoader)
            apply_config_file(c, configuration)

            # Fix beam bandwidth and start frequency (in case they were written in scientific notation)
            configuration['observation']['bandwidth'] = \
                float(configuration['observation']['bandwidth'])
            configuration['observation']['start_frequency_channel'] = \
                float(configuration['observation']['start_frequency_channel'])
    else:
        logging.error("No configuration file specified. Exiting")
        exit()


def load_station_configuration(config_params):
    """ Combine configuration defined in configuration file with command-line arguments """

    # If a configuration file is defined, check if it exists and load it
    load_configuration_file(config_params.config)

    # Go through command line options and update where necessary
    if config_params.beam_bandwidth is not None:
        configuration['observation']['bandwidth'] = config_params.beam_bandwidth
    if config_params.beam_integ is not None:
        configuration['station']['beam_integration_time'] = config_params.beam_integ
    if config_params.beam_scaling is not None:
        configuration['station']['beamformer_scaling'] = config_params.beam_scaling
    if config_params.beamf_start is not None:
        configuration['station']['start_beamformer'] = config_params.beamf_start
    if config_params.bitfile is not None:
        configuration['station']['bitfile'] = config_params.bitfile
    if config_params.chan_trunc is not None:
        configuration['station']['channel_truncation'] = config_params.chan_trunc
    if config_params.channel_integ is not None:
        configuration['station']['channel_integration_time'] = config_params.channel_integ
    if config_params.enable_test is not None:
        configuration['station']['enable_test'] = config_params.enable_test
    # if config_params.use_internal_pps is True: # Not clear how to use the command line option wrt value set in config file
    #     configuration['station']['use_internal_pps'] = True
    if config_params.initialise is not None:
        configuration['station']['initialise'] = config_params.initialise
    if config_params.lmc_ip is not None:
        configuration['network']['lmc']['lmc_ip'] = config_params.lmc_ip
    if config_params.lmc_mac is not None:
        configuration['network']['lmc']['lmc_mac'] = config_params.lmc_mac
    if config_params.lmc_port is not None:
        configuration['network']['lmc']['lmc_port'] = config_params.lmc_port
    if config_params.port is not None:
        configuration['network']['lmc']['tpm_cpld_port'] = config_params.port
    if config_params.program is not None:
        configuration['station']['program'] = config_params.program
    if config_params.program_cpld is not None:
        configuration['station']['program_cpld'] = config_params.program_cpld
    if config_params.start_frequency_channel is not None:
        configuration['observation']['start_frequency_channel'] = config_params.start_frequency_channel
    if config_params.tiles is not None:
        configuration['tiles'] = config_params.tiles.split(',')
    if config_params.use_teng is not None:
        configuration['network']['lmc']['use_teng'] = config_params.use_teng

    return configuration


if __name__ == "__main__":
    import pyaavs.logger
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser.add_option("--config", action="store", dest="config",
                      type="str", default=None, help="Configuration file [default: None]")
    parser.add_option("--port", action="store", dest="port",
                      type="int", default=None, help="Port [default: None]")
    parser.add_option("--lmc_ip", action="store", dest="lmc_ip",
                      default=None, help="IP [default: None]")
    parser.add_option("--lmc_port", action="store", dest="lmc_port",
                      type="int", default=None, help="Port [default: None]")
    parser.add_option("--lmc-mac", action="store", dest="lmc_mac",
                      type="int", default=None, help="LMC MAC address [default: None]")
    parser.add_option("-f", "--bitfile", action="store", dest="bitfile",
                      default=None, help="Bitfile to use (-P still required) [default: None]")
    parser.add_option("-t", "--tiles", action="store", dest="tiles",
                      default=None, help="Tiles to add to station [default: None]")
    parser.add_option("-P", "--program", action="store_true", dest="program",
                      default=False, help="Program FPGAs [default: False]")
    parser.add_option("-I", "--initialise", action="store_true", dest="initialise",
                      default=False, help="Initialise TPM [default: False]")
    parser.add_option("-C", "--program_cpld", action="store_true", dest="program_cpld",
                      default=False, help="Update CPLD firmware (requires -f option) [default: False]")
    parser.add_option("-T", "--enable-test", action="store_true", dest="enable_test",
                      default=False, help="Enable test pattern [default: False]")
    # parser.add_option("--use_internal_pps", action="store_true", dest="use_internal_pps",
    #                   default=False, help="Enable internal PPS generator ['default: False]")
    parser.add_option("--use_teng", action="store_true", dest="use_teng",
                      default=None, help="Use 10G for LMC [default: None]")
    parser.add_option("--chan-trunc", action="store", dest="chan_trunc",
                      default=None, type="int", help="Channeliser truncation [default: None]")
    parser.add_option("-B", "--beamf_start", action="store_true", dest="beamf_start",
                      default=False, help="Start network beamformer [default: False]")
    parser.add_option("--channel-integration-time", action="store", dest="channel_integ",
                      type="float", default=None, help="Integrated channel integration time [default: None]")
    parser.add_option("--beam-integration-time", action="store", dest="beam_integ",
                      type="float", default=None, help="Integrated beam integration time [default: None]")
    parser.add_option("--beamformer-scaling", action="store", dest="beam_scaling",
                      type="int", default=None, help="Beamformer scaling [default: None]")
    parser.add_option("--beam-start_frequency", action="store", dest="start_frequency_channel",
                      type="float", default=None, help="Beamformer scaling [default: None]")
    parser.add_option("--beam-bandwidth", action="store", dest="beam_bandwidth",
                      type="float", default=None, help="Beamformer scaling [default: None]")
    parser.add_option("--fft_sign_invert", action="store_true", dest="fft_sign_invert",
                      default=False, help="Conjugate FFT output [default: False]")

    (conf, args) = parser.parse_args(argv[1:])

    # Set current thread name
    threading.current_thread().name = "Station"

    # Load station configuration
    configuration = load_station_configuration(conf)

    # Create station
    station = Station(configuration)

    # Connect station (program, initialise and configure if required)
    station.connect()

    if conf.fft_sign_invert:
        station['fpga1.dsp_regfile.channelizer_config.fft_conjugate'] = 1
        station['fpga2.dsp_regfile.channelizer_config.fft_conjugate'] = 1
