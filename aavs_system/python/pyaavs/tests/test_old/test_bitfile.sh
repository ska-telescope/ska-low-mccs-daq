#!/bin/sh

sudo python test_daq.py
sudo python test_adc.py -i 4
sudo python test_channelizer.py -f 110 -l 118
sudo python test_tile_beamformer.py -f 202 -l 205

