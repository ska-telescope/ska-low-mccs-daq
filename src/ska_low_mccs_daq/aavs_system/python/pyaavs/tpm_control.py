#! /usr/bin/env python

from sys import exit
import logging
import os

from pyaavs.tile import Tile

__author__ = 'Alessio Magro'


# Define CSP ingest network parameters. Destination MAC, IP and UDP port for each 10G lane of the TPM
csp_ingest_network = {0: {"mac": 0x0,
                          "ip": "0.0.0.0",
                          "port": 0xF0D1},
                      1: {"mac": 0x0,
                          "ip": "0.0.0.0",
                          "port": 0xF0D1},
                      2: {"mac": 0x0,
                          "ip": "0.0.0.0",
                          "port": 0xF0D1},
                      3: {"mac": 0x0,
                          "ip": "0.0.0.0",
                          "port": 0xF0D1},
                      4: {"mac": 0x0,
                          "ip": "0.0.0.0",
                          "port": 0xF0D1},
                      5: {"mac": 0x0,
                          "ip": "0.0.0.0",
                          "port": 0xF0D1},
                      6: {"mac": 0x0,
                          "ip": "0.0.0.0",
                          "port": 0xF0D1},
                      7: {"mac": 0x0,
                          "ip": "0.0.0.0",
                          "port": 0xF0D1},
                      }

# Mac address for LMC interface
# lmc_mac = 0x248A078F9D38  # AAVS
# lmc_mac = 0x5065f385ac72  # Malta
# lmc_mac = 0xe41d2d214890  # Oxford 40G
lmc_mac = 0x248a07463b5e #Oxford 100G

for n in range(8):
    csp_ingest_network[n]['mac'] = lmc_mac
    # csp_ingest_network[n]['ip'] = "10.0.10.200"  # AAVS
    # csp_ingest_network[n]['ip'] = "10.0.10.250" # Malta
    # csp_ingest_network[n]['ip'] = "10.0.10.40" # Oxford 40G
    csp_ingest_network[n]['ip'] = "10.0.10.100" # Oxford 100G
    csp_ingest_network[n]['port'] = 4660

if __name__ == "__main__":

    # Use OptionParse to get command-line arguments
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %test_tpm [options]")
    parser.add_option("--ip", action="store", dest="ip",
                      default="10.0.10.2", help="IP [default: 10.0.10.2]")
    parser.add_option("--port", action="store", dest="port",
                      type="int", default="10000", help="Port [default: 10000]")
    parser.add_option("--lmc_ip", action="store", dest="lmc_ip",
                      default="10.0.10.200", help="IP [default: 10.0.10.200]")
    parser.add_option("--lmc_port", action="store", dest="lmc_port",
                      type="int", default="4660", help="Port [default: 4660]")
    parser.add_option("-a", "--nof_antennas", action="store", dest="nof_antennas",
                      type="int", default=16, help="Number of antennas [default: 16]")
    parser.add_option("-c", "--nof_channels", action="store", dest="nof_channels",
                      type="int", default=512, help="Number of channels [default: 512]")
    parser.add_option("-b", "--nof_beams", action="store", dest="nof_beams",
                      type="int", default=1, help="Number of beams [default: 1]")
    parser.add_option("-p", "--nof_pols", action="store", dest="nof_polarisations",
                      type="int", default=2, help="Number of polarisations [default: 2]")
    parser.add_option("-f", "--bitfile", action="store", dest="bitfile",
                      default=None, help="Bitfile to use (-P still required)")
    parser.add_option("-P", "--program", action="store_true", dest="program",
                      default=False, help="Program FPGAs [default: False]")
    parser.add_option("-C", "--program-cpld", action="store_true", dest="program_cpld",
                      default=False, help="Program CPLD (cannot be used with other options) [default: False]")
    parser.add_option("-T", "--test", action="store_true", dest="test",
                      default=False, help="Load test firmware (-P still required) [default: False]")
    parser.add_option("-I", "--initialise", action="store_true", dest="initialise",
                      default=False, help="Initialise TPM [default: False]")
    parser.add_option("-S", "--simulation", action="store_true", dest="simulation",
                      default=False, help="Connect to TPM in simulation mode [default: False]")
    parser.add_option("-A", "--enable-ada", action="store_true", dest="enable_ada",
                      default=False, help="Enable ADAs [default: True]")
    parser.add_option("", "--channel-integration-time", action="store", dest="channel_integ",
                      type="float", default=-1, help="Integrated channel integration time [default: -1 (disabled)]")
    parser.add_option("", "--beam-integration-time", action="store", dest="beam_integ",
                      type="float", default=-1, help="Integrated beam integration time [default: -1 (disabled)]")
    parser.add_option("--ada-gain", action="store", dest="ada_gain",
                      default=15, type="int", help="ADA gain [default: 15]")
    parser.add_option("--chan-trunc-scale", action="store", dest="chan_trun",
                      default=2, type="int", help="Channelsier truncation scale [range: 0-7, default: 2]")
    parser.add_option("", "--use_teng", action="store_true", dest="use_teng",
                      default=False, help="Use 10G for LMC (default: False)")

    (conf, args) = parser.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    line_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(line_format)
    log.addHandler(ch)

    # Create Tile
    tile = Tile(ip=conf.ip, port=conf.port, lmc_ip=conf.lmc_ip, lmc_port=conf.lmc_port)

    # Program CPLD
    if conf.program_cpld:
        if conf.bitfile is not None:
            if os.path.exists(conf.bitfile) and os.path.isfile(conf.bitfile):
                logging.info("Using CPLD bitfile {}".format(conf.bitfile))
                tile.program_cpld(conf.bitfile)
                exit(0)
            else:
                logging.error("Could not load bitfile {}, check filepath".format(conf.bitfile))
        else:
            logging.error("No CPLD bitfile specified")
            exit(-1)

    # Program FPGAs if required
    if conf.program:
        logging.info("Programming FPGAs")
        if conf.bitfile is not None:
            logging.info("Using bitfile %s" % conf.bitfile)
            if os.path.exists(conf.bitfile) and os.path.isfile(conf.bitfile):
                tile.program_fpgas(bitfile=conf.bitfile)
            else:
                logging.error("Could not load bitfile %s, check filepath" % conf.bitfile)
                exit(-1)
        else:
            logging.error("No bitfile specified")
            exit(-1)

    # Initialise TPM if required
    if conf.initialise:
        logging.info("Initialising TPM")
        tile.initialise(enable_ada=conf.enable_ada, enable_test=conf.test)

        # Set ada gain if enabled
        if conf.enable_ada:
            tile.tpm.tpm_ada.set_ada_gain(conf.ada_gain)

        # Configure all 10G cores to transmit to the CSP ingests address
        #for core_id in range(8):
        #    tile.configure_10g_core(core_id,
        #                            dst_mac=csp_ingest_network[core_id]['mac'],
        #                            dst_ip=csp_ingest_network[core_id]['ip'],
        #                            dst_port=csp_ingest_network[core_id]['port'])

        # Configure LMC data lanes, in case overwrites 10G lane 3 configuration with LMC destination
        if conf.use_teng:
            logging.info("Using 10G for LMC traffic")
            tile.set_lmc_download("10g", 8192, lmc_mac=lmc_mac)
            tile.set_lmc_integrated_download("10g", 1024, 2048, lmc_mac=lmc_mac)
        else:

            logging.info("Using 1G for LMC traffic")
            tile.set_lmc_download("1g")
            tile.set_lmc_integrated_download("1g", 1024, 2048)

        # Set channeliser truncation
        logging.info("Configuring channeliser and beamformer")
        tile.set_channeliser_truncation(conf.chan_trun)

        # Configure continuous transmission of integrated channel and beam data
        tile.stop_integrated_data()

        if conf.channel_integ != -1:
            tile.configure_integrated_channel_data(conf.channel_integ)

        if conf.beam_integ != -1:
            tile.configure_integrated_beam_data(conf.beam_integ)

        # Initialise beamformer
        logging.info("Initialising beamformer")
        tile.initialise_beamformer(2, 384)
        tile.set_first_last_tile(True, True)
        tile.define_spead_header(0, 0, 16, -1, 0)
        tile.start_beamformer(start_time=0, duration=-1)

        # Perform synchronisation
        # tile.post_synchronisation()
        tile.set_pps_sampling(20,4)
        tile.check_fpga_synchronization()

        logging.info("Setting data acquisition")
        tile.start_acquisition()

    # Connect to board
    tile.connect()

