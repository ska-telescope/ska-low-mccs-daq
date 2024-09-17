from pyaavs import station
from config_manager import ConfigManager
from time import sleep
import test_functions as tf
import numpy as np
import logging
# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
# Import required persisters
from pydaq.persisters import *


data_received = False
data = []
nof_antennas_per_tile = 16

def integrated_data_callback(mode, filepath, tile):
    """
    DAQ Callback for integrated course channel data.
    Reads hdf5 file to array.
    """
    global tiles_processed
    global data_received
    global data
    global beam_int_tiles_processed
    global beam_int_data_received
    global beam_int_data

    if mode == "integrated_channel":
        tiles_processed[tile] = 1
        if np.all(tiles_processed >= 1):
            data = np.zeros((512, nof_tiles * nof_antennas_per_tile, 2, 1), dtype=np.uint32)
            channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath), daq_mode=FileDAQModes.Integrated)
            for tile_id in list(range(nof_tiles)):
                tile_data, timestamps = channel_file.read_data(antennas=range(16), polarizations=[0, 1], n_samples=1, tile_id=tile_id)
                data[:, tile_id * nof_antennas_per_tile:(tile_id + 1) * nof_antennas_per_tile, :, :] = tile_data
            data_received = True
            

class TestBandpass:
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self.errors = 0
        self.tiles_with_errors = []
    
    def check_integrated_channel(self, data):
        """
        Assume no input to the ADC.
        Verify integrated course channel data for each antenna and polarisation is 0.
        """
        ch, ant, pol, sam = data.shape
        for c in range(ch):
            for a in range(ant):
                for p in range(pol):
                    for i in range(1):
                        if data[c, a, p, i] != 0:
                            if c != 0:  # Ignore gain in channel 0
                                tpm_id = a // nof_antennas_per_tile
                                
                                self._logger.error(f"Data Error! TPM{tpm_id}, Frequency Channel: {c} ({c*25/32:.2f} MHz), Antenna: {a}, Polarization: {p}, Sample index: {i}. Received data: {data[c, a, p, i]}")
                                self.errors += 1
                                self.tiles_with_errors.append(tpm_id) if tpm_id not in self.tiles_with_errors else self.tiles_with_errors
        return

    def clean_up(self):
        daq.stop_daq()
        if self.errors > 0:
            self._logger.error(f"Bandpass Test FAILED! {self.errors} Errors")
            self._logger.error(f"Bandpass Test FAILED! {', '.join([f'TPM{i}' for i in self.tiles_with_errors])}")
            return 1
        self._logger.info("Bandpass Test PASSED!")
        return 0

    def execute(self, integration_time=1):
        global tiles_processed
        global data_received
        global data
        global nof_tiles
        global nof_antennas_per_tile

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._logger.info("Executing Bandpass test")
	
        nof_tiles = len(self._test_station.tiles) 
        config_int_time = self._station_config['station']['channel_integration_time']
        integration_time = integration_time or config_int_time  # If None, use config time
        
        temp_dir = "./temp_daq_test"
        # Determine receiver port
        # If both LMC and LMC integrated share the same interface, then data will be on LMC port not integrated port
        integ_dst_port = self._station_config['network']['lmc']['integrated_data_port']
        if not (self._station_config['network']['lmc']['use_teng'] ^ self._station_config['network']['lmc']['use_teng_integrated']):
            integ_dst_port = self._station_config['network']['lmc']['lmc_port']
            
        # Initialise DAQ.
        daq_config = {
                'receiver_interface': self._station_config['eth_if'],
                'receiver_ports': str(integ_dst_port),
                'directory': temp_dir,
                'nof_beam_channels': 384,
                'nof_beam_samples': 1,
                'receiver_frame_size': 9000,
                'nof_tiles': nof_tiles
            }
        # Configure the DAQ receiver and start receiving data
        daq.populate_configuration(daq_config)
        daq.initialise_daq()

        self.errors = 0
        
        for n, tile in enumerate(self._test_station.tiles):
            
            # Stop Station Beam
            tile.stop_beamformer()
            
            # Set Integration Time
            self._logger.info(f"Configuring {integration_time} second integration time for TPM{n}.")
            tile.configure_integrated_channel_data(integration_time)
            
            for preadu_index, preadu in enumerate(tile.tpm.tpm_preadu):
                self._logger.info(f"Checking for preaADU for TPM{n}, preADU{preadu_index}...")
                preadu.switch_off()
                preadu.switch_on()
                sleep(0.5)  # Sleep required to ensure preADUs are detected correctly after power on
                if preadu.is_present:
                    self._logger.info(f"TPM{n} preADU{preadu_index} detected! Configuring attenuation to 0.")
                    preadu.set_attenuation(0)
                    preadu.write_configuration()
                else:
                    self._logger.info(f"TPM{n} preADU{preadu_index} not detected! Skipping configuring preADU attenuation")
        
        tf.remove_hdf5_files(temp_dir)
        data_received = False
        tiles_processed = np.zeros(nof_tiles)

	# Data Capture
        daq.start_integrated_channel_data_consumer(callback=integrated_data_callback)
        while True:
            if data_received:
                daq.stop_integrated_channel_data_consumer()
                self.check_integrated_channel(data)
                break
            time.sleep(0.1)

        tf.remove_hdf5_files(temp_dir)
        for tile in self._test_station.tiles:
            # Revert Integration Time
            self._logger.info(f"Configuring {config_int_time} second integration time for TPM{n}.")
            tile.configure_integrated_channel_data(config_int_time)
        return self.clean_up()


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-t", "--integration_time", action="store", dest="integration_time",
                      default="1", help="Course channel power integration time in seconds [default: 1]")

    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_bandpass.log',
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

    test_logger = logging.getLogger('TEST_BANDPASS')

    test_inst = TestBandpass(tpm_config, test_logger)
    test_inst.execute(int(conf.integration_time))
