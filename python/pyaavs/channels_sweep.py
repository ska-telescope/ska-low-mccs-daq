#! /usr/bin/env python

# sends send_channelised_data_continous command for range of channels , default is to send the command every 10 seconds which allows to collect 3 correlation matrices per channel
# send to separate HDF5 files (see suggested daq_receiver.py command below )
# to be used in conjunction with script :
# python /opt/aavs/bin/daq_receiver.py -i eth3:1 -K -d . -t 16 --correlator_samples=1835008 --nof_channels=1 --max-filesize_gb=0
# to collected correlated data 
# 

from pyaavs import station
import pyaavs.logging

import logging
import time

if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser.add_option("--config", action="store", dest="config",
                      type="str", default=None, help="Configuration file [default: None]")

    # specify channels to sweep and how long to stay on a single channel :
    parser.add_option("--start-channel", "--start_channel", action="store", dest="start_channel",
                      type="int", default=0, help="Start channel [default: %default]")
    parser.add_option("--end-channel", "--end_channel", "--stop_channel", "--stop-channel", action="store",
                      dest="stop_channel",
                      type="int", default=512, help="Stop channel [default: %default]")
    parser.add_option("--time_per_channel", "--inttime", "--dwell-time", action="store", dest="time_per_channel",
                      type="int", default=15, help="Time on channel in seconds [default: %default seconds]")

    (conf, args) = parser.parse_args(argv[1:])

    # Connect to station
    station.load_configuration_file(conf.config)
    aavs_station = station.Station(station.configuration)
    aavs_station.connect()

    # running a loop over specified channel range :
    logging.info("Running a loop over channels %d - %d" % (conf.start_channel, conf.stop_channel))
    for channel in range(conf.start_channel, conf.stop_channel):
        aavs_station.send_channelised_data_continuous(channel)
        logging.info("Staying on channel %d for %d seconds ..." % (channel, conf.time_per_channel))
        time.sleep(conf.time_per_channel)
