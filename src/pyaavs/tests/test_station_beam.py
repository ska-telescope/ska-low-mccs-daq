# station = [
# #"tpm-1",
# "tpm-1", "tpm-2", "tpm-3", "tpm-4",
# "tpm-5", "tpm-6", "tpm-7", "tpm-8",
# "tpm-9", "tpm-10", "tpm-11", "tpm-12",
# "tpm-13", "tpm-14",
# "tpm-15", "tpm-16",
# ]

first_channel = 200


def set_pattern(station, stage, pattern, adders, frame_adder, nof_tpms, start):
    print("Setting " + stage + " data pattern")
    for tile in station.tiles:
        tile['fpga1.pattern_gen.beamf_left_shift'] = 0
        tile['fpga2.pattern_gen.beamf_left_shift'] = 0
        for i in range(2):
            print
            tile.tpm.tpm_pattern_generator[i].set_pattern(pattern, stage)
            tile.tpm.tpm_pattern_generator[i].set_signal_adder(adders[i*64:(i+1)*64], stage)
            if start:
                tile.tpm.tpm_pattern_generator[i].start_pattern(stage)
    print("Waiting PPS event to set frame_adder register")
    station.tiles[0].wait_pps_event()
    for tile in station.tiles:
        tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_clear'] = 1
        tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_clear'] = 1
        if frame_adder > 0:
            tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_enable'] = 1
            tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_enable'] = 1
            tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_adder'] = frame_adder
            tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_adder'] = frame_adder

            tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_lo'] = 0
            tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_lo'] = 0

            tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_hi'] = int(127 / nof_tpms)
            tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_hi'] = int(127 / nof_tpms)
    station.tiles[0].wait_pps_event()
    for tile in station.tiles:
        tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_clear'] = 0
        tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_clear'] = 0
    print("Beamformer Pattern Set!")

def remove_files():
    # create temp directory
    if not os.path.exists(temp_dir):
        print("Creating temp folder: " + temp_dir)
        os.system("mkdir " + temp_dir)
    os.system("rm " + temp_dir + "/*.hdf5")

if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %test_antenna_delays [options]")
    parser.add_option("--config", action="store", dest="config",
                      type="str", default=None, help="Configuration file [default: None]")
    # parser.add_option("-P", "--program", action="store_true", dest="program",
    #                   default=False, help="Program FPGAs [default: False]")
    # parser.add_option("-I", "--initialise", action="store_true", dest="initialise",
    #                   default=False, help="Initialise TPM [default: False]")
    # parser.add_option("-i", "--receiver_interface", action="store", dest="receiver_interface",
    #                   default="eth0", help="Receiver interface [default: eth0]")
    # parser.add_option("-D", "--generate-plots", action="store_true", dest="generate_plots",
    #                   default=False, help="Generate diagnostic plots [default: False]")
    (opts, args) = parser.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    str_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(str_format)
    log.addHandler(ch)
    remove_files()

    # Check if a config file is specified
    if opts.config is None:
        logging.error("No station configuration file was defined. Exiting")
        exit()
    elif not os.path.exists(opts.config) or not os.path.isfile(opts.config):
        logging.error("Specified config file does not exist or is not a file. Exiting")
        exit()

    # Update global config
    station_config_file = opts.config
    # receiver_interface = opts.receiver_interface
    # initialise_tile = opts.initialise
    # program_tile = opts.program

    # Load station configuration file
    station.load_configuration_file(station_config_file)

    # Override parameters
    station_config = station.configuration
    station_config['station']['program'] = False #program_tile
    station_config['station']['initialise'] = False #initialise_tile
    # station_config['station']['channel_truncation'] = 5  # Increase channel truncation factor
    # station_config['station']['start_beamformer'] = True

    # Define station beam parameters (using configuration for test pattern generator)
    # station_config['observation']['start_frequency_channel'] = beam_start_frequency
    # station_config['observation']['bandwidth'] = beam_bandwidth

    # Check number of antennas to delay
    # nof_antennas = len(station_config['tiles']) * antennas_per_tile

    # Create station
    test_station = station.Station(station_config)

    # Initialise station
    test_station.connect()

    if not test_station.properly_formed_station:
        logging.error("Station not properly formed, exiting")
        exit()

    iter = 0
    pattern = [0]*1024
    adders = [0]*64 + [0]*64
    frame_adder = 1

    for tile in test_station.tiles:
        tile['fpga1.beamf_ring.csp_scaling'] = 0
        tile['fpga2.beamf_ring.csp_scaling'] = 0

    while True:
        # Starting pattern generator
        random.seed(iter)
        for n in range(1024):
            if frame_adder > 0:
                pattern[n] = 0
            elif int(iter % 2) == 0:
                pattern[n] = n
            else:
                pattern[n] = random.randrange(0, 255, 1)

        print("Setting pattern:")
        print(pattern[0:15])
        print("Setting frame adder: " + str(frame_adder))

        set_pattern(test_station, "beamf", pattern, adders, frame_adder, len(test_station.tiles), True)

        time.sleep(1)

        spead_rx_inst = spead_rx(4660)
        spead_rx_inst.run_test(len(test_station.tiles), pattern, adders, frame_adder, first_channel, 1000000000000)
        spead_rx_inst.close_socket()
        del spead_rx_inst

        iter += 1

        print("Iteration " + str(iter) + " with no errors!")



