from pyaavs import station
from config_manager import ConfigManager

from functools import reduce
import test_functions as tf
import logging


class TestPreadu:
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self.errors = 0

    def clean_up(self):
        if self.errors > 0:
            self._logger.error(f"preadu Test FAILED! {self.errors} Errors")
            return 1
        self._logger.info("preadu Test PASSED!")
        return 0

    def execute(self, placeholder=None):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._logger.info("Executing preadu test")

        self.errors = 0
        
        for n, tile in enumerate(self._test_station.tiles):

            for preadu_index, preADU in enumerate(tile.tpm.tpm_preadu):

                self._logger.info(f"Starting tile {n}, preadu {preadu_index} test")

                preADU.switch_off()
                preADU.switch_on()

                if preADU.check_preadu_exists():
                    self._logger.info(f"preadu detected! tile: {n}, preADU: {preadu_index}")

                    # ---- preADU read/write test ----

                    attenuation_values = [21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36]

                    # Write attenuation values into the preADU
                    for channel, attenuation in enumerate(attenuation_values):
                        preADU.set_attenuation(attenuation, [channel])
                    preADU.write_configuration()

                    # Set software representation to something else,
                    # To ensure tests fail if read_configuration doesn't work
                    preADU.set_attenuation(15)

                    # Updates software representation with the preADU attenuation values
                    preADU.read_configuration()

                    for index, channel_filter in enumerate(preADU.channel_filters):
                        if preADU.get_attenuation()[index] != attenuation_values[index]:
                            self._logger.error(f"preadu channel {index}, preadu read/write is not working, got: {preADU.get_attenuation()[index]}, expected: {attenuation_values[index]}, tile: {n}, preADU: {preadu_index}")
                            self.errors += 1
                        else:
                            self._logger.info(f"preadu channel {index}, preadu read/write is working")

                    # ---- eep non-volatile memory read/write test ----

                    # Write attenuation values into the eep non-volatile memory
                    for channel, attenuation in enumerate(attenuation_values):
                        preADU.set_attenuation(attenuation, [channel])
                    preADU.eep_write()

                    # Set software representation to something else,
                    # To ensure tests fail if eep_read doesn't work
                    preADU.set_attenuation(15)

                    # Updates software representation with the eep non-volatile memory attenuation values
                    preADU.eep_read()

                    for index, channel_filter in enumerate(preADU.channel_filters):
                        if preADU.get_attenuation()[index] != attenuation_values[index]:
                            self._logger.error(f"preadu channel {index}, non-volatile memory read/write is not working, got: {preADU.get_attenuation()[index]}, expected: {attenuation_values[index]}, tile: {n}, preADU: {preadu_index}")
                            self.errors += 1
                        else:
                            self._logger.info(f"preadu channel {index}, eep non-volatile memory read/write is working")

                    # if tmp is 1.2 run passband tests
                    if tile.tpm_version() == "tpm_v1_2":

                        # ---- disable_channels passband test ----

                        preADU.disable_channels()
                        preADU.write_configuration()

                        # Set software representation to something else,
                        # To ensure tests fail if read_configuration doesn't work

                        preADU.set_attenuation(15)

                        # Updates software representation with the preADU attenuation values
                        preADU.read_configuration()

                        for index, channel_filter in enumerate(preADU.channel_filters):
                            if preADU.channel_filters[index] != 0x0:
                                self._logger.error(
                                    f"preadu channel {index}, disable channels passband not working, got: {preADU.channel_filters[index]}, expected: 0x0, tile: {n}, preADU: {preadu_index}")
                                self.errors += 1
                            else:
                                self._logger.info(f"preadu channel {index}, disable channels passband is working")

                        # ---- low passband test ----

                        preADU.select_low_passband()
                        preADU.enable_channels()  # writes internal channel filters to the passband
                        preADU.write_configuration()

                        # Set software representation to something else,
                        # To ensure tests fail if read_configuration doesn't work
                        preADU._passband = 0x0
                        preADU.set_attenuation(15)

                        # Updates software representation with the preADU attenuation values
                        preADU.read_configuration()

                        for index, channel_filter in enumerate(preADU.channel_filters):
                            received_passband = preADU.get_passband()[index]
                            if received_passband != 0x5:
                                self._logger.error(
                                    f"preadu channel {index}, low passband not working, got: {received_passband}, expected: 0x5, tile: {n}, preADU: {preadu_index}")
                                self.errors += 1
                            else:
                                self._logger.info(f"preadu channel {index}, low passband is working")

                        # ---- high passband test ----

                        preADU.select_high_passband()
                        preADU.enable_channels()  # writes internal channel filters to the passband
                        preADU.write_configuration()

                        # Set software representation to something else,
                        # To ensure tests fail if read_configuration doesn't work
                        preADU._passband = 0x0
                        preADU.set_attenuation(15)

                        # Updates software representation with the preADU attenuation values
                        preADU.read_configuration()

                        for index, channel_filter in enumerate(preADU.channel_filters):
                            received_passband = preADU.get_passband()[index]
                            if received_passband != 0x3:
                                self._logger.error(
                                    f"preadu channel {index}, high passband not working, got: {received_passband}, expected: 0x3, tile: {n}, preADU: {preadu_index}")
                                self.errors += 1
                            else:
                                self._logger.info(f"preadu channel {index}, high passband is working")

                else:  # if check_preadu_exists is false
                    self._logger.error(f"preadu not detected! Will not run test. tile: {n}, preADU: {preadu_index}")
                    self.errors += 1

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
