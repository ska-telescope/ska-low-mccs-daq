from pyaavs import station
from config_manager import ConfigManager
from time import sleep
import logging            

class TestTemplate:
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self.errors = 0
        self.tiles_with_errors = []
    
    def clean_up(self):
        if self.errors > 0:
            self._logger.error(f"Template Test FAILED! {self.errors} Errors")
            return 1
        self._logger.info("Template Test PASSED!")
        return 0

    def execute(self, duration=20):
        global nof_tiles

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self._logger.info("Executing Template test")
        nof_tiles = len(self._test_station.tiles) 
        self.errors = 0
        
        for n, tile in enumerate(self._test_station.tiles):
            self._logger.info(tile)

    
        return self.clean_up()


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-d", "--duration", action="store", dest="duration",
                      default="20", help="Test duration in seconds [default: 20, infinite: -1]")
    (conf, args) = parser.parse_args(argv[1:])

    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_template.log',
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

    test_logger = logging.getLogger('TEST_TEMPLATE')

    test_inst = TestTemplate(tpm_config, test_logger)
    test_inst.execute(int(conf.duration))
