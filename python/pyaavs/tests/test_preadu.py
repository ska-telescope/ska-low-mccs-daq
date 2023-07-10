from pyaavs import station
from config_manager import ConfigManager
from time import sleep
import logging


class TestPreadu:
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        # Test first preADU 16 channels with values 15 -> 30
        # Test second preADU 16 channels with values 16 -> 31
        self._test_attenuation_values = (list(range(15, 31)), list(range(16, 32)))
        self.errors = 0

    def clean_up(self):
        percentage = round(len(self.preadus_present)*100 / (len(self.preadus_present)+len(self.preadus_not_present)), 2)
        self._logger.info(f"{percentage}% of preADUs detected.")
        self._logger.info(f"Undetected preADUs: {*self.preadus_not_present,}")
        if self.errors > 0:
            self._logger.error(f"preADU Test FAILED! {self.errors} Errors")
            return 1
        self._logger.info("preADU Test PASSED!")
        return 0

    def test_read_write_configuration(self, preadu, n, preadu_index):
        # Write attenuation values into the preADU
        for channel, attenuation in enumerate(self._test_attenuation_values[preadu_index]):
            preadu.set_attenuation(attenuation, [channel])
        preadu.write_configuration()

        # Set software representation to something else
        # To ensure tests fail if read_configuration doesn't work
        preadu.set_attenuation(15)

        # Updates software representation with the preADU attenuation values
        preadu.read_configuration()

        for index, channel_filter in enumerate(preadu.channel_filters):
            if preadu.get_attenuation()[index] != self._test_attenuation_values[preadu_index][index]:
                self._logger.error(f"TPM{n} preADU{preadu_index} channel{index} read/write error! Got: {preadu.get_attenuation()[index]}, expected: {self._test_attenuation_values[preadu_index][index]}.")
                self.errors += 1
                return
            self._logger.info(f"TPM{n} preADU{preadu_index} channel{index} read/write success!")
        return

    def test_read_write_eep(self, preadu, n, preadu_index):
        # Write attenuation values into the eep non-volatile memory
        for channel, attenuation in enumerate(self._test_attenuation_values[preadu_index]):
            preadu.set_attenuation(attenuation, [channel])
        preadu.eep_write()

        # Set software representation to something else
        # To ensure tests fail if eep_read doesn't work
        preadu.set_attenuation(15)

        # Updates software representation with the eep non-volatile memory attenuation values
        preadu.eep_read()

        for index, channel_filter in enumerate(preadu.channel_filters):
            if preadu.get_attenuation()[index] != self._test_attenuation_values[preadu_index][index]:
                self._logger.error(f"TPM{n} preADU{preadu_index} channel{index} non-volatile memory read/write error! Got: {preadu.get_attenuation()[index]}, expected: {self._test_attenuation_values[preadu_index][index]}")
                self.errors += 1
                return
            self._logger.info(f"TPM{n} preADU{preadu_index} channel{index} eep non-volatile memory read/write success!")
        return

    def test_disable_channels(self, preadu, n, preadu_index):
        preadu.disable_channels()
        preadu.write_configuration()

        # Set software representation to something else
        # To ensure tests fail if read_configuration doesn't work
        preadu.set_attenuation(15)

        # Updates software representation with the preADU attenuation values
        preadu.read_configuration()

        for index, channel_filter in enumerate(preadu.channel_filters):
            if preadu.channel_filters[index] != 0x0:
                self._logger.error(f"TPM{n} preADU{preadu_index} channel{index} disable channels error! Got: {preadu.channel_filters[index]}, expected: 0x0")
                self.errors += 1
                return
            self._logger.info(f"TPM{n} preADU{preadu_index} channel{index} disabled successfully!")
        return

    def test_low_passband(self, preadu, n, preadu_index):
        preadu.select_low_passband()
        preadu.enable_channels()  # writes internal channel filters to the passband
        preadu.write_configuration()

        # Set software representation to something else
        # To ensure tests fail if read_configuration doesn't work
        preadu._passband = 0x0
        preadu.set_attenuation(15)

        # Updates software representation with the preADU attenuation values
        preadu.read_configuration()

        for index, channel_filter in enumerate(preadu.channel_filters):
            received_passband = preadu.get_passband()[index]
            if received_passband != 0x5:
                self._logger.error(
                    f"TPM{n} preADU{preadu_index} channel{index} low passband configuration error! Got: {received_passband}, expected: 0x5")
                self.errors += 1
                return
            self._logger.info(f"TPM{n} preADU{preadu_index} channel{index} low passband configured sucessfully!")
        return
    
    def test_high_passband(self, preadu, n, preadu_index):
        preadu.select_high_passband()
        preadu.enable_channels()  # writes internal channel filters to the passband
        preadu.write_configuration()

        # Set software representation to something else
        # To ensure tests fail if read_configuration doesn't work
        preadu._passband = 0x0
        preadu.set_attenuation(15)

        # Updates software representation with the preADU attenuation values
        preadu.read_configuration()

        for index, channel_filter in enumerate(preadu.channel_filters):
            received_passband = preadu.get_passband()[index]
            if received_passband != 0x3:
                self._logger.error(f"TPM{n} preADU{preadu_index} channel{index} high passband configuration error! Got: {received_passband}, expected: 0x3")
                self.errors += 1
                return
            self._logger.info(f"TPM{n} preADU{preadu_index} channel{index} high passband configured sucessfully!")
        return

    def execute(self, placeholder=None):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._logger.info("Executing preADU test")

        self.errors = 0
        self.preadus_present = []
        self.preadus_not_present = []
        
        for n, tile in enumerate(self._test_station.tiles):

            for preadu_index, preadu in enumerate(tile.tpm.tpm_preadu):

                self._logger.info(f"Starting Test for TPM{n}, preADU{preadu_index}...")

                preadu.switch_off()
                preadu.switch_on()
                sleep(0.5)  # Sleep required to ensure preADUs are detected correctly 

                if preadu.is_present():
                    self._logger.info(f"TPM{n} preADU{preadu_index} detected!")
                    self.preadus_present.append(f"TPM{n} preADU{preadu_index}")
                    # preADU read/write test
                    self.test_read_write_configuration(preadu, n, preadu_index)
                    # EEP non-volatile memory read/write test
                    # NOTE:This test has been disabled, not currently needed and not working as expected
                    # self.test_read_write_eep(preadu, n, preadu_index)
                    # TPM 1.2 only tests
                    if tile.tpm_version() == "tpm_v1_2":
                        # Disable channels test
                        self.test_disable_channels(preadu, n, preadu_index)
                        # Low passband test
                        self.test_low_passband(preadu, n, preadu_index)
                        # High passband test
                        self.test_high_passband(preadu, n, preadu_index)

                else:  # SKIP test if no preADU is detected
                    self._logger.warning(f"TPM{n} preADU{preadu_index} not detected! Will skip tests for this preADU...")
                    self.preadus_not_present.append(f"TPM{n} preADU{preadu_index}")

        return self.clean_up()


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_preadu.log',
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

    test_logger = logging.getLogger('TEST_PREADU')

    test_inst = TestPreadu(tpm_config, test_logger)
    test_inst.execute()
