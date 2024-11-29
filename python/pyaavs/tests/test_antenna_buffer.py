# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile import Tile
from pyaavs import station
from config_manager import ConfigManager

# Import required persisters
from pydaq.persisters.aavs_file import FileModes
from pydaq.persisters.raw import RawFormatFileManager, FileDAQModes
from pydaq.persisters import *

from matplotlib import pyplot as plt
from builtins import input
from sys import stdout

import test_requirements as tr
import test_functions as tf
import numpy as np
import os.path
import logging
import random
import time

nof_tiles = 1
nof_antennas = 16
tiles_processed = None
data_received = False
buffer_size_nof_samples = 8*1024*1024  # DAQ instantiates 16*buffer_size_nof_samples bytes, use this to calculate nof callbacks
nof_callback = 0
callback_received = 0


def data_callback(mode, filepath, tile):
    global data
    global nof_tiles
    global data_received
    global tiles_processed
    global nof_samples
    global callback_received
    global nof_callback

    if mode == "antenna_buffer":

        callback_received += 1
        if callback_received == nof_callback:
            callback_received = 0

            raw_file = RawFormatFileManager(root_path=os.path.dirname(filepath), daq_mode=FileDAQModes.Burst)
            data, _ = raw_file.read_data(n_samples=nof_samples)
            print(f"DEBUG:: nof_samples= {nof_samples}, data_shape = {data.shape}")

            data_received = True


class TestAntennaBuffer():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config

    def clean_up(self):
        daq.stop_daq()

    def check_pattern(self, fpga_id):

        global data
        global nof_samples

        # print(data.shape)

        for antenna in range(2):
            for pol in range(data.shape[1]):
                signal_data = np.reshape(data[antenna + 2 * fpga_id, pol], (nof_samples // 4, 4)).astype(np.uint8).astype(np.uint32)
                signal_data = (signal_data[:, 0] & 0xFF) | \
                              (signal_data[:, 1] << 8) | \
                              (signal_data[:, 2] << 16) | \
                              (signal_data[:, 3] << 24)

                if pol % 2 == 0:
                    seed = signal_data[0]
                else:
                    seed += 1233
                self._logger.info("Checking incremental 32 bit pattern for antenna %s, pol %s" % (antenna, pol))
                for sample in range(nof_samples // 4):
                    # exp_value = (seed + sample) & 0xFFFFFFFF
                    exp_value = np.uint32(seed + sample)
                    if exp_value != signal_data[sample]:
                        self._logger.error("Error detected, ramp pattern")
                        self._logger.error("Antenna index: " + str(antenna))
                        self._logger.error("Buffer position: " + str(sample))
                        self._logger.error("Expected value: " + str(exp_value))
                        self._logger.error("Received value: " + str(signal_data[sample]))
                        lo = max(sample-128, 0)
                        hi = min(sample+128, nof_samples // 4)
                        self._logger.error(signal_data[lo:hi])
                        self._logger.error("ANTENNA BUFFER TEST FAILED!")
                        return 1

        self._logger.info("Data pattern check OK!")
        return 0

    def execute(self, iterations=2, use_1g=0, single_tpm_id=0, fpga_id=0, timestamp_capture_duration=75, start_address=512*1024*1024):
        global tiles_processed
        global data_received
        global nof_tiles
        global nof_antennas
        global nof_samples
        global nof_callback

        self._logger.debug(f"FPGA ID = {fpga_id}")

        # Connect to tile (and do whatever is required)
        test_station = station.Station(self._station_config)
        test_station.connect()

        if test_station.tiles[0]['fpga1.dsp_regfile.feature.antenna_buffer_implemented'] == 0:
            self._logger.debug("Antenna Buffer not implemented in the FPGA firmware.")
            self._logger.error("ANTENNA BUFFER TEST FAILED!")
            return 1

        if single_tpm_id >= 0:
            if single_tpm_id >= len(test_station.tiles):
                self._logger.error("Required TPM Id for single TPM test does not belong to station.")
                return 1
            else:
                self._logger.info("Executing test on tile %d" % single_tpm_id)
                dut = test_station.tiles[single_tpm_id]
                tiles = [test_station.tiles[single_tpm_id]]
        else:
            # dut = test_station
            # tiles = test_station.tiles
            self._logger.error("Test on multiple TPM not supported yet.")
            self._logger.error("ANTENNA BUFFER TEST FAILED!")
            return 1

        nof_tiles = len(tiles)
        nof_antennas = self._station_config['test_config']['antennas_per_tile']

        if not tr.check_eth(self._station_config, "lmc", 1500, self._logger):
            return 1
        self.daq_eth_if = self._station_config['eth_if']['lmc']
        self.daq_eth_port = self._station_config['network']['lmc']['lmc_port']
        self._logger.info(f"Using Ethernet Interface {self.daq_eth_if} and UDP port {self.daq_eth_port}")

        temp_dir = "./temp_daq_test"
        data_received = False

        tf.remove_hdf5_files(temp_dir)

        self._logger.debug("Disable test and pattern generators...")
        self._logger.debug("Setting 0 delays...")
        for tile in tiles:
            tf.disable_test_generator_and_pattern(tile)
            tf.set_delay(tile, [0] * 32)
        time.sleep(0.2)

        self._logger.debug("Setting antenna buffer pattern...")
        dut.stop_integrated_data()
        beamformer_running = dut.beamformer_is_running()
        if beamformer_running:
            dut.stop_beamformer()

        dut.set_pattern(stage="jesd", pattern=range(1024), adders=[0] * 32, start=True)
        ab = dut.tpm.tpm_antenna_buffer[fpga_id]

        # Assign FPGA ID and Antennas IDs to be tested for each FPGA
        if fpga_id == 0:
            fpga = "fpga1"
            antenna_ids = [0, 1]
        else:
            fpga = "fpga2"
            antenna_ids = [8, 9]
        
        # Assign the Tx mode
        if use_1g:
            tx_mode='NSDN'
            receiver_frame_size = 1664
        else:
            tx_mode='SDN'
            receiver_frame_size = 8320

        """ Select antenna buffer Tx mode which will also assign the payload_length inside the method 
            Configuring the DDR Start Address - Test defualt is 512MiB"""
        dut.set_up_antenna_buffer(mode=tx_mode, 
                                  ddr_start_byte_address=start_address,
                                  max_ddr_byte_size=None
                                 )

        """ Start Antenna Buffer: Select antennas for buffering: selecting 2 antennas - 1 antenna per fpga """
        actual_buffer_byte_size = dut.start_antenna_buffer(antennas=antenna_ids,
                                 start_time=-1,
                                 timestamp_capture_duration=timestamp_capture_duration,
                                 continuous_mode=False
                                )

        # Base Write Address is the start_address/8 so should be 67,108,864
        base_addr = dut[f'{fpga}.antenna_buffer.ddr_write_start_addr']
        self._logger.info(f"DDR buffer base address is hex: {hex(base_addr)}")
        self._logger.info(f"Actual DDR buffer size is {actual_buffer_byte_size} bytes")
        nof_samples = actual_buffer_byte_size // 4  # 2 antennas, 2 pols

        self._logger.debug(f"fpga={fpga}, ant1={dut[f'{fpga}.antenna_buffer.input_sel.sel_antenna_id_0']}, ant2={dut[f'{fpga}.antenna_buffer.input_sel.sel_antenna_id_1']}")

        self._logger.debug(f"Nof Antenna= {ab._nof_antenna}, DDR timestampByteSize= {ab._ddr_timestamp_byte_size}, Actual DDR buffer size is {actual_buffer_byte_size} bytes")
        self._logger.debug(f"Nof DDR Frames = {ab._nof_ddr_timestamp}, ")

        # Test Pattern Generation
        dut['%s.pattern_gen.jesd_ramp1_enable' % fpga] = 0x5555
        dut['%s.pattern_gen.jesd_ramp2_enable' % fpga] = 0xAAAA

        # calculate actual DAQ buffer size in nof_raw_samples
        total_nof_samples = actual_buffer_byte_size // 4
        nof_callback = np.ceil(total_nof_samples / buffer_size_nof_samples)
        if nof_callback < 1:
            nof_callback = 1
        nof_callback = 2**int(np.log2(nof_callback))
        daq_nof_raw_samples = total_nof_samples / nof_callback
        self._logger.info("DAQ buffer size set to %f samples, using %d callbacks" % (daq_nof_raw_samples, nof_callback))

        iter = int(iterations)
        if iter == 0:
            return

        daq_config = {
            'receiver_interface': self.daq_eth_if,
            'receiver_ports': str(self.daq_eth_port),
            'directory': temp_dir,  # CHANGE THIS if required
            'nof_raw_samples': int(daq_nof_raw_samples),
            'nof_antennas': 4,
            'nof_beam_channels': 384,
            'nof_beam_samples': 32,
            'receiver_frame_size': receiver_frame_size,  # 8320 #1664
            'nof_tiles': len(tiles),
            'max_filesize': 8
        }
        # Configure the DAQ receiver and start receiving data
        daq.populate_configuration(daq_config)
        daq.initialise_daq()

        # Start whichever consumer is required and provide callback
        daq.start_antenna_buffer_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
        #
        # raw data synchronised
        #
        tf.remove_hdf5_files(temp_dir)

        self._logger.info("Executing %d test iterations" % iter)

        errors = 0
        k = 0
        while k != iter:

            data_received = False
            
            """ Read Antenna Buffer Data from DDR """
            dut.read_antenna_buffer()

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            if self.check_pattern(fpga_id) > 0:
                errors += 1
                break

            k += 1

            self._logger.info("Iteration %d PASSED!" % k)

        if beamformer_running:
            dut.start_beamformer()
        self.clean_up()
        return errors


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-i", "--iteration", action="store", dest="iteration",
                      default="16", help="Number of iterations [default: 16, infinite: -1]")
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    station_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_antenna_buffer.log',
                        filemode='w')
    # define a Handler which writes INFO messages or higher to the sys.stderr
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    # set a format which is simpler for console use
    formatter = logging.Formatter(logging_format)
    # tell the handler to use this format
    console.setFormatter(formatter)
    # add the handler to the root logger
    logging.getLogger('').addHandler(console)

    test_logger = logging.getLogger('TEST_ANTENNA_BUFFER')

    test_antenna_buffer = TestAntennaBuffer(station_config, test_logger)
    test_antenna_buffer.execute(conf.iteration)
