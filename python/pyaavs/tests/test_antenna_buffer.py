# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile_wrapper import Tile
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
buffer_size_nof_samples = 64*1024*1024  # DAQ instantiates 16*buffer_size_nof_samples bytes, use this to calculate nof callbacks
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

            data_received = True


class TestAntennaBuffer():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config

    def clean_up(self, test_station):
        daq.stop_daq()

    def check_pattern(self):

        global data
        global nof_samples

        # print(data.shape)

        for antenna in range(2):
            for pol in range(data.shape[1]):
                signal_data = np.reshape(data[antenna, pol], (nof_samples // 4, 4)).astype(np.uint8).astype(np.uint32)
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

    def execute(self, iterations=2, single_tpm_id=0, buffer_byte_size=64*1024*1024, start_address=512*1024*1024):
        global tiles_processed
        global data_received
        global nof_tiles
        global nof_antennas
        global nof_samples
        global nof_callback

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
        self._logger.info("Using Ethernet Interface %s" % self._station_config['eth_if'])

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
        tf.set_pattern(dut, stage="jesd", pattern=range(1024), adders=[0] * 64, start=True)
        ab = dut.tpm.tpm_antenna_buffer[0]
        ab.set_download("1G", 1536)
        actual_buffer_byte_size = ab.configure_ddr_buffer(ddr_start_byte_address=start_address,  # DDR buffer base address
                                                          byte_size=buffer_byte_size)
        base_addr = dut['fpga1.antenna_buffer.ddr_write_start_addr']
        self._logger.info("DDR buffer base address is %s" % hex(base_addr))
        self._logger.info("Actual DDR buffer size is %d bytes" % actual_buffer_byte_size)
        nof_samples = actual_buffer_byte_size // 4  # 2 antennas, 2 pols
        dut['fpga1.antenna_buffer.payload_rate_control.pause_length'] = 0x0
        dut['fpga1.antenna_buffer.input_sel.sel_antenna_id_0'] = 0x0
        dut['fpga1.antenna_buffer.input_sel.sel_antenna_id_1'] = 0x1
        dut['fpga1.pattern_gen.jesd_ramp1_enable'] = 0x5555
        dut['fpga1.pattern_gen.jesd_ramp2_enable'] = 0xAAAA

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

        # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
        # I'll change this to make it nicer
        self._logger.info("Configuring DAQ. Using Ethernet Interface " + self._station_config['eth_if'])
        daq_config = {
            'receiver_interface': self._station_config['eth_if'],  # CHANGE THIS if required
            'directory': temp_dir,  # CHANGE THIS if required
            'nof_raw_samples': int(daq_nof_raw_samples),
            'nof_antennas': 4,
            'nof_beam_channels': 384,
            'nof_beam_samples': 32,
            'receiver_frame_size': 1664,  # 8320 #1280
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
            # Send data from tile
            # ab.one_shot_buffer_read()
            # while True:
            #     print(ab.one_shot_buffer_write())
            #     time.sleep(0.2)

            ab.one_shot()

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            if self.check_pattern() > 0:
                errors += 1
                break

            k += 1

            self._logger.info("Iteration %d PASSED!" % k)

        self.clean_up(test_station)
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
