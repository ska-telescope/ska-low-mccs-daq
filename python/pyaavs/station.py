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
import socket
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
                     'qsfp_detection': "auto",
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
    :param tile_number: TPM to associate tile to """

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

    nof_tiles = len(config['tiles'])
    this_tile_ip = socket.gethostbyname(config['tiles'][tile_number])
    next_tile_ip = socket.gethostbyname(config['tiles'][(tile_number + 1) % nof_tiles])

    src_ip_40g_fpga1 = f"10.0.1.{this_tile_ip.split('.')[3]}"
    src_ip_40g_fpga2 = f"10.0.2.{this_tile_ip.split('.')[3]}"
    dst_ip_40g_fpga1 = f"10.0.1.{next_tile_ip.split('.')[3]}"
    dst_ip_40g_fpga2 = f"10.0.2.{next_tile_ip.split('.')[3]}"
    src_port_40g=config['network']['csp_ingest']['src_port']
    dst_port_40g=config['network']['csp_ingest']['dst_port']
    is_first = tile_number == 0
    is_last = tile_number == nof_tiles - 1

    if tile_number == nof_tiles - 1:
        if config['network']['csp_ingest']['dst_ip'] != "0.0.0.0":
            dst_ip_40g_fpga1=config['network']['csp_ingest']['dst_ip']
            dst_ip_40g_fpga2=config['network']['csp_ingest']['dst_ip']

    # get pps delay for current tile
    pps_delay = 0
    if config['station'].get('pps_delays', None) is not None:
        logging.info("Loading PPS delays")
        if type(config['station']['pps_delays']) is int:
            pps_delay = config['station']['pps_delays']
        elif len(config['station']['pps_delays']) != nof_tiles:
            logging.warning("Incorrect number of PPS delays specified, must match number of TPMs. Ignoring")
        else:
            pps_delay = config['station']['pps_delays'][tile_number]

    # get time delays for current tile
    time_delays = 0
    if config['time_delays'] is not None:
        if len(config['time_delays']) != nof_tiles:
            logging.warning("Incorrect number of time delays specified, must match number of TPMs. Ignoring")
        else:
            logging.info("Setting a delay of {}ns to tile {}".format(config['time_delays'][tile_number], tile_number))
            time_delays = configuration['time_delays'][tile_number]

    try:
        threading.current_thread().name = config['tiles'][tile_number]
        logging.info("Initialising Tile {}".format(config['tiles'][tile_number]))
        threading.current_thread().name = config['tiles'][tile_number]

        # Create station instance and initialise
        station_tile = create_tile_instance(config, tile_number)
        station_tile.initialise(
            station_id=config['station']['id'],
            tile_id=tile_number,
            lmc_use_40g=config['network']['lmc']['use_teng'],
            lmc_dst_ip=config['network']['lmc']['lmc_ip'],
            lmc_dst_port=config['network']['lmc']['lmc_port'],
            lmc_integrated_use_40g=config['network']['lmc']['use_teng_integrated'],
            lmc_integrated_dst_ip=config['network']['lmc']['lmc_ip'],
            src_ip_fpga1=src_ip_40g_fpga1,
            src_ip_fpga2=src_ip_40g_fpga2,
            dst_ip_fpga1=dst_ip_40g_fpga1,
            dst_ip_fpga2=dst_ip_40g_fpga2,
            src_port=src_port_40g,
            dst_port=dst_port_40g,
            qsfp_detection=config['station']['qsfp_detection'],
            enable_test=config['station']['enable_test'],
            use_internal_pps=config['station']['use_internal_pps'],
            pps_delay=pps_delay,
            time_delays=time_delays,
            is_first_tile=is_first,
            is_last_tile=is_last
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

            logging.info("Initializing tile and station beamformer")
            start_channel = int(round(self.configuration['observation']['start_frequency_channel'] / (400e6 / 512.0)))
            nof_channels = max(int(round(self.configuration['observation']['bandwidth'] / (400e6 / 512.0))), 8)

            if self.configuration['station']['start_beamformer']:
                logging.info("Station beamformer enabled")
                self._slack.info("Station beamformer enabled with start frequency {:.2f} MHz and bandwidth {:.2f} MHz".format(
                    self.configuration['observation']['start_frequency_channel'] * 1e-6,
                    self.configuration['observation']['bandwidth'] * 1e-6))

            # configure beamformer
            if self.tiles[0].tpm.tpm_test_firmware[0].tile_beamformer_implemented and \
                    self.tiles[0].tpm.tpm_test_firmware[0].station_beamformer_implemented:
                for i, tile in enumerate(self.tiles):
                    # Initialise beamformer
                    tile.initialise_beamformer(start_channel, nof_channels)

                    # Define SPEAD header
                    # TODO: Insert proper values here
                    if i == len(self.tiles) - 1:
                        tile.define_spead_header(station_id=self._station_id,
                                                 subarray_id=0,
                                                 nof_antennas=self.configuration['station']['number_of_antennas'],
                                                 ref_epoch=-1,
                                                 start_time=0)

                    # Start beamformer
                    if self.configuration['station']['start_beamformer']:
                        logging.info("Starting station beamformer")
                        tile.start_beamformer(start_time=0, duration=-1)

                        # Set beamformer scaling
                        for tile in self.tiles:
                            for station_beamf in tile.tpm.station_beamf:
                                station_beamf.set_csp_rounding(
                                    self.configuration['station']['beamformer_scaling']
                                )

            # If in testing mode, override tile-specific test generators
            if self.configuration['station']['enable_test']:
                for tile in self.tiles:
                    for gen in tile.tpm.test_generator:
                        gen.channel_select(0x0000)
                        gen.disable_prdg()

                for tile in self.tiles:
                    for gen in tile.tpm.test_generator:
                        gen.set_tone(0, 100 * 400e6 / 512, 1)
                        gen.set_tone(1, 100 * 400e6 / 512, 0)
                        gen.channel_select(0xFFFF)

            # if self['fpga1.regfile.feature.xg_eth_implemented'] == 1:
            #     for tile in self.tiles:
            #         tile.reset_eth_errors()
            #     time.sleep(1)
            #     for tile in self.tiles:
            #         tile.check_arp_table()

            # If initialising, synchronise all tiles in station
            logging.info("Synchronising station")
            self._check_pps_sampling_synchronisation()
            self._check_time_synchronisation()
            self._start_acquisition()

            # Setting PREADU values
            att_value = self.configuration['station']['default_preadu_attenuation']
            if not (self.configuration['station']['enable_test'] or att_value == -1):
                # Set default preadu attenuation
                time.sleep(1)
                logging.info("Setting default PREADU attenuation to {}".format(att_value))
                for tile in self.tiles:
                    tile.set_preadu_attenuation(att_value)

                # If equalization is required, do it
                if self.configuration['station']['equalize_preadu'] != 0:
                    logging.info("Equalizing PREADU signals to ADU RMS {}".format(
                        self.configuration['station']['equalize_preadu'])
                    )
                    self._slack.info("Station gains are being equalized to ADU RMS {}".format(
                        self.configuration['station']['equalize_preadu'])
                    )
                    for tile in self.tiles:
                        tile.equalize_preadu_gain(self.configuration['station']['equalize_preadu'])

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

    def _check_time_synchronisation(self):
        """ Check UTC time synchronisation across tiles and FPGAs. Re-write UTC time when check fails """
        pps_detect = self['fpga1.pps_manager.pps_detected']
        logging.debug("FPGA1 PPS detection register is ({})".format(pps_detect))
        pps_detect = self['fpga2.pps_manager.pps_detected']
        logging.debug("FPGA2 PPS detection register is ({})".format(pps_detect))

        # Repeat operation until Tiles are synchronised, synchronise all tiles to the first tile
        max_attempts = 5
        for n in range(max_attempts):
            # Read the current time on first tile
            self.tiles[0].wait_pps_event()

            # PPS edge detected, read time from first tile
            curr_time = self.tiles[0].get_fpga_time(Device.FPGA_1)

            times = set()
            for tile in self.tiles:
                times.add(tile.get_fpga_time(Device.FPGA_1))
                times.add(tile.get_fpga_time(Device.FPGA_2))

            if len(times) == 1:
                logging.info("Tiles in station synchronised, time is %d" % curr_time)
                break
            else:
                logging.info("Re-Synchronising tiles in station with time %d" % curr_time)
                for tile in self.tiles:
                    tile.set_fpga_time(Device.FPGA_1, curr_time)
                    tile.set_fpga_time(Device.FPGA_2, curr_time)
            if n == max_attempts - 1:
                logging.error("Not possible to synchronise station UTC time across tiles")

    def _start_acquisition(self):

        # Check if ARP table is populated before starting
        for tile in self.tiles:
            tile.reset_eth_errors()
            tile.check_arp_table()

        # Start data acquisition on all boards
        delay = 2
        t0 = self.tiles[0].get_fpga_time(Device.FPGA_1)
        for tile in self.tiles:
            tile.start_acquisition(start_time=t0, delay=delay)

        t1 = self.tiles[0].get_fpga_time(Device.FPGA_1)
        if t0 + delay <= t1:
            logging.error("Start data acquisition not synchronised! Rerun initialisation")
            exit()

        logging.info("Waiting for start acquisition")
        wait_timeout = 2000
        for n in range(wait_timeout):
            rd_vld = self['fpga1.dsp_regfile.stream_status.channelizer_vld'] + \
                     self['fpga2.dsp_regfile.stream_status.channelizer_vld']
            if all(rd_vld):
                break
            else:
                time.sleep(0.001)
                if n == wait_timeout - 1:
                    logging.error("Start data acquisition timeout! Rerun initialisation")
                    exit()

    def _check_pps_sampling_synchronisation(self):
        """ Post tile configuration synchronization """

        # Station synchronisation loop
        max_delay_skew = 4
        sync_loop = 0
        max_sync_loop = 5
        while sync_loop < max_sync_loop:

            self.tiles[0].wait_pps_event()

            sync_loop += 1

            # get the PPS delay from tile
            measured_delay = [tile.get_pps_delay() for tile in self.tiles]

            # check if there is too much skew
            synced = True
            for n in range(len(self.tiles) - 1):
                if abs(measured_delay[0] - measured_delay[n + 1]) > max_delay_skew:
                    synced = False

            if synced:
                # if skew is not too much, the tiles are synchronised
                phase1 = [hex(tile['fpga1.pps_manager.sync_phase']) for tile in self.tiles]
                phase2 = [hex(tile['fpga2.pps_manager.sync_phase']) for tile in self.tiles]
                logging.debug("Final FPGA1 clock phase ({})".format(phase1))
                logging.debug("Final FPGA2 clock phase ({})".format(phase2))

                logging.info("Finished PPS sampling synchronisation check ({})".format(measured_delay))
                return measured_delay
            else:
                # if skew is too much, repeat the synchronisation using the first tile as reference
                logging.warning("Resynchronizing station ({})".format(measured_delay))
                for n in range(len(self.tiles)):
                    self.tiles[n].set_pps_sampling(measured_delay[0], 4)

        logging.error("Station PPS sampling synchronisation check failed!")

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

    def send_raw_data(self, sync=False):
        """ Send raw data from all Tiles """
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_raw_data(sync=sync, timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_raw_data_synchronised(self):
        """ Send synchronised raw data from all Tiles """
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_raw_data_synchronised(timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_channelised_data(self, number_of_samples=1024, first_channel=0, last_channel=511):
        """ Send channelised data from all Tiles """
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_channelised_data(number_of_samples=number_of_samples, first_channel=first_channel,
                                       last_channel=last_channel,
                                       timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_beam_data(self):
        """ Send beam data from all Tiles """
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_beam_data(timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_channelised_data_continuous(self, channel_id, number_of_samples=65536):
        """ Send continuous channelised data from all Tiles """
        self.stop_data_transmission()
        self._wait_available()
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.send_channelised_data_continuous(channel_id=channel_id, number_of_samples=number_of_samples,
                                                  timestamp=t0, seconds=self._seconds)
        return self._check_data_sync(t0)

    def send_channelised_data_narrowband(self, frequency, round_bits, number_of_samples=256):
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
                                                  timestamp=t0, seconds=self._seconds)
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

    # ------------------------------------ MULTICHANNEL TX DATA OPERATIONS -----------------------------
    def set_multi_channel_tx(self, instance_id, channel_id, destination_id):
        """ Set multichannel transmitter instance
        :param instance_id: Transmitter instance ID
        :param channel_id: Channel ID
        :param destination_id: 40G destination ID"""
        for tile in self.tiles:
            tile.set_multi_channel_tx(instance_id, channel_id, destination_id)

    def start_multi_channel_tx(self, instances, seconds=0.2):
        """ Start multichannel data transmission from the TPM
        :param instances: 64 bit integer, each bit addresses the corresponding TX transmitter
        :param seconds: synchronisation delay ID"""
        t0 = self.tiles[0].get_fpga_timestamp(Device.FPGA_1)
        for tile in self.tiles:
            tile.start_multi_channel_tx(instances, t0, seconds=1)

    def stop_multi_channel_tx(self):
        """ Stop multichannel TX data transmission """
        for tile in self.tiles:
            tile.stop_multi_channel_tx()

    def set_multi_channel_dst_ip(self, dst_ip, destination_id):
        for tile in self.tiles:
            tile.set_multi_channel_dst_ip(dst_ip, destination_id)

    # ------------------------------------------- TEST FUNCTIONS ---------------------------------------

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
    if config_params.qsfp_detection is not None:
        configuration['station']['qsfp_detection'] = config_params.qsfp_detection
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
    parser.add_option("--qsfp_detection", action="store", dest="qsfp_detection",
                      default=None, help="Force QSFP cable detection: auto, qsfp1, qsfp2, all, none [default: auto]")
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
