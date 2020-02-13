# from aavs_calibration.common import *

from matplotlib import pyplot as plt
from datetime import datetime, timedelta
import shutil
import logging

import numpy as np
import pytz
import h5py
import time
import aipy
import re
import os

antenna_locations = "/home/lessju/Desktop/antenna_locations.txt"
calibration_solutions = "/home/lessju/Desktop/calib_solutions.txt"


class AAVSImager:

    def __init__(self, correlation_file, station_name="AAVS1", calibrate=False):
        """ Class constructor"""

        # Check that correlation file is valid
        if not os.path.exists(correlation_file) or not os.path.isfile(correlation_file):
            logging.error("Invalid correlation file specified: {}".format(correlation_file))

        # Get station information
        # station = get_station_information(station_name)

        self._station_name = station_name
        self._aavs_station_latitude = np.deg2rad(-26.7040)  # station.latitude
        self._aavs_station_longitude = np.deg2rad(116.6702)  # station.longitude
        self._nof_antennas = 256
        self._nof_baselines = self._nof_antennas * (self._nof_antennas + 1) / 2

        # Load HDF file
        self._calibrate = calibrate
        self._correlation_file = correlation_file
        self._load_hdf_file()

        # Calibrate visibilities if required
        if calibrate:
            self.calibrate_visibilities()

        # Filename to store temporary uv file
        self._uv_filepath = "/tmp/aavs_uvfits.uv"

        # Generate antenna array and UV file
        self._antenna_array = self._generate_antenna_array()

        # Generate UV file
        self._generate_uv_file()

    def _load_hdf_file(self):
        """ Load HDF5 file """

        # Verify file
        filename = os.path.basename(os.path.abspath(self._correlation_file))
        pattern = r"correlation_burst_(?P<channel>\d+)_(?P<timestamp>\d+)_(?P<seconds>\d+)_(?P<part>\d+).hdf5"
        parts = re.match(pattern, filename).groupdict()

        if parts is None:
            logging.error("Invalid file specified: {}".format(self._correlation_file))
            exit()

        # Process timestamp
        sec = timedelta(seconds=int(parts['seconds']))
        date = datetime.strptime(parts['timestamp'], '%Y%m%d') + sec
        self._time = date.replace(tzinfo=pytz.timezone("Australia/Perth"))

        # Process frequency
        self._frequency = (400e6 / 512.0) * int(parts['channel']) * 1e-9

        # Load visibilities
        with h5py.File(self._correlation_file, 'r') as f:
            data = f['correlation_matrix']['data'][0, 0, :, 0]
            indices = np.triu_indices(self._nof_antennas)
            grid = np.zeros((self._nof_antennas, self._nof_antennas), dtype=np.complex64)
            grid[indices[0], indices[1]] = data[:]
            self._visibilities = grid

    def _get_antenna_positions(self):
        """ Return antenna positions """
        x, y = [], []
        with open(antenna_locations, 'r') as f:
            for antenna in f.read().split('\n')[:-1]:
                positions = antenna.split(',')
                x.append(float(positions[0]))
                y.append(float(positions[1]))

        return x, y, [0] * self._nof_antennas

    def _generate_antenna_array(self):
        # Read antenna locations file

        # Get antenna locations
        # base, x, y = get_antenna_positions(self._station_name)

        x, y, _ = self._get_antenna_positions()

        # Set frequencies and beam
        freqs = np.array([self._frequency])
        beam = aipy.phs.Beam(freqs)

        antennas = []
        for i in range(self._nof_antennas):
            antennas.append(aipy.phs.Antenna(x[i] / 0.299792458,
                                             y[i] / 0.299792458,
                                             0,
                                             beam))

        # Generate antenna array
        array = aipy.phs.AntennaArray(ants=antennas, location=(self._aavs_station_latitude,
                                                               self._aavs_station_longitude))

        # All done
        return array

    def _generate_uv_file(self):
        """ Generate a UV file for simulated AAVS1 data"""

        # If file exists, remove it
        if os.path.exists(self._uv_filepath):
            shutil.rmtree(self._uv_filepath)

        # Create myriad UV file
        uv = aipy.miriad.UV(self._uv_filepath, status='new')  # Start a new UV file
        uv['obstype'] = 'mixed-auto-cross'  # Miriad header item indicating data type
        uv['history'] = 'Created file'  # Record file creation for posterity

        uv.add_var('telescop', 'a')
        uv['telescop'] = 'VLA'
        uv.add_var('dec', 'r')
        uv['dec'] = 0.0

        # Create and initialize UV variables
        # a dict of variable data type is in a.miriad.data_types
        # This is not a complete list of variables, see MIRIAD programmer reference
        uv.add_var('epoch', 'r')  # Make a variable 'epoch', data type = real
        uv['epoch'] = 2000.  # Set epoch to 2000.
        uv.add_var('source', 'a')  # Source we are tracking, as a string
        uv['source'] = 'zenith'
        uv.add_var('latitud', 'd')  # Latitude of our array, as a double
        uv['latitud'] = self._aavs_station_latitude
        uv.add_var('longitu', 'd')  # Longitude of our array, as double
        uv['longitu'] = self._aavs_station_longitude
        uv.add_var('npol', 'i')  # Number of recorded polarizations, as int
        uv['npol'] = 1
        uv.add_var('nspect', 'i')  # Number of spectra recorded per antenna/baseline
        uv['nspect'] = 1
        uv.add_var('nants', 'i')  # Number of antennas in array
        uv['nants'] = self._nof_antennas
        uv.add_var('antpos', 'd')  # Positions (uvw) of antennas.  Expected to be 3*nants in length

        # Get antenna locations
        x, y, _ = self._get_antenna_positions()
        antenna_positions = np.array([[x[i], y[i], 0] for i in range(self._nof_antennas)])
        #antenna_positions /= 0.299792458

        # Transposition is a MIRIAD convention.  You can follow it or not.
        uv['antpos'] = antenna_positions.transpose().flatten()

        uv.add_var('sfreq', 'd')  # Freq of first channel in spectra (GHz)
        uv['sfreq'] = self._frequency
        uv.add_var('sdf', 'd')  # Delta freq between channels
        uv['sdf'] = .001
        uv.add_var('nchan', 'i')  # Number of channels in spectrum
        uv['nchan'] = 1
        uv.add_var('nschan', 'i')  # Number of channels in bandpass cal spectra
        uv['nschan'] = 1
        uv.add_var('inttime', 'r')  # Integration time (seconds)
        uv['inttime'] = 1.0

        # These variables will get updated every spectrum
        uv.add_var('time', 'd')
        uv.add_var('lst', 'd')
        uv.add_var('ra', 'd')
        uv.add_var('obsra', 'd')
        uv.add_var('baseline', 'r')
        uv.add_var('pol', 'i')

        # Now start generating data
        # Convert unix time to Julian date
        from astropy.time import Time
        times = [Time(self._time, format="datetime", scale="utc").jd]

        for cnt, t in enumerate(times):
            uv['lst'] = 0.  # Should be sidereal time from AntennaArray
            uv['ra'] = 0.  # RA of source you're pointing at
            for i, ai in enumerate(antenna_positions):
                for j, aj in enumerate(antenna_positions):
                    if j < i:
                        continue

                    crd = ai - aj  # Find uvw coordinate of baseline
                    preamble = (crd, t, (i, j))  # Set preamble to (uvw, julian date, baseline)
                    uv['pol'] = aipy.miriad.str2pol['xx']  # Fix polarization as 'xx'
                    data = np.array([self._visibilities[i, j]])  # Generate some data
                    flags = np.zeros((uv['nchan'],), dtype=np.int32)  # Generate some flags (zero = valid)
                    uv.write(preamble, data, flags)  # Write this entry to the UV file
        del uv

    def calibrate_visibilities(self):
        """ Calibrate visibilities using coefficients from database """

        # Get coefficients
        calib = np.loadtxt(calibration_solutions, delimiter=',')

        phase = np.deg2rad(calib[:, 0])
        coeffs = np.cos(phase) + 1j * np.sin(phase)

        for i in range(self._nof_antennas):
            for j in range(i, self._nof_antennas):
                self._visibilities[i, j] *= coeffs[i] * np.conj(coeffs[j])

    def plot_sky_image(self):
        """ Generate image of the sky"""
        uv = aipy.miriad.UV(self._uv_filepath)

        # Remove auto correlations
        uv.select('auto', 0, 0, include=False)

        srcs = aipy._src.misc.get_srcs(srcs=['Sun'])
        src = srcs[0]

        data, uvw, wgts = [], [], []
        for (_, t, (i, j)), d in uv.all():
            self._antenna_array.set_jultime(t)
          #  src.compute(self._antenna_array)

          #  try:
          #      d = self._antenna_array.phs2src(d, src, i, j)
          #      crd = self._antenna_array.gen_uvw(i, j, src=src)
          #  except Exception as e:
          #      print "Pointing Error", e
          #      continue

            crd = self._antenna_array.gen_uvw(i, j)
            uvw.append(np.squeeze(crd))
            data.append(d.compressed())
            wgts.append(np.array([1.] * len(data[-1])))

        data = np.concatenate(data)
        uvw = np.array(uvw)
        wgts = np.concatenate(wgts)

        plt.figure()
        im = aipy.img.Img(size=1600, res=0.5)
        uvw, data, wgts = im.append_hermitian(uvw.T, data, wgts=wgts)
        im.put(uvw, data, wgts=wgts)
        plt.imshow(im.image(center=(1600, 1600)))
        plt.show()


if __name__ == "__main__":
    visualiser = AAVSImager("/home/lessju/Desktop/correlation_burst_204_20190330_43624_0.hdf5", calibrate=True)
    visualiser.plot_sky_image()
