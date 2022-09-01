from __future__ import print_function
from __future__ import division
from builtins import range
from builtins import object
from past.utils import old_div
import ctypes
import logging
import os
import re
from ctypeslib.contrib.pythonhdr import Py_ssize_t
from ctypes.util import find_library
from datetime import timedelta
from datetime import datetime as dt
import time
import numpy as np

from pydaq.persisters import FileDAQModes, ChannelFormatFileManager


class Complex8t(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int8),
                ("y", ctypes.c_int8)]


class StandaloneCorrelator(object):

    def __init__(self, nof_antennas, nof_samples):
        self._library = None
        self._nof_antennas = nof_antennas
        self._nof_samples = nof_samples

        # Initialise shared library
        self._initialise_library()

        # Initialise xGPU
        self._library.initialise_correlator(nof_antennas, nof_samples)
        logging.info("Initialised correlator")

    def process_file(self, filepath):
        """ Correlate all data in file """
        filepath = os.path.abspath(os.path.expanduser(filepath))
        if not (os.path.exists(conf.file) and os.path.isfile(filepath)):
            logging.error("Specified file does not exist or is not a file. Exiting")
            return

        # Extract directory from filename
        directory = os.path.dirname(os.path.abspath(filepath))
        filename = os.path.basename(os.path.abspath(filepath))

        # Extract file name parts
        try:
            pattern = r"(?P<type>\w+)_(?P<mode>\w+)_(?P<tile>\d+)_(?P<timestamp>\d+_\d+)_(?P<part>\d+).hdf5"
            parts = re.match(pattern, filename).groupdict()
        except:
            logging.error("Invalid filepath specified, exiting")
            return

        tile = int(parts['tile'])

        # Process timestamp and tile id
        try:
            time_parts = parts['timestamp'].split('_')
            sec = timedelta(seconds=int(time_parts[1]))
            date = dt.strptime(time_parts[0], '%Y%m%d') + sec
            timestamp = time.mktime(date.timetuple())
        except Exception as e:
            logging.warning("Could not convert date in filename to a timestamp: {}".format(e.message))
            return None

        if parts['type'] != 'channel' or parts['mode'] != 'cont':
            logging.error("Invalid filetype specified. Exiting")

        # Create reader
        channel_reader = ChannelFormatFileManager(root_path=directory,
                                                  daq_mode=FileDAQModes.Continuous)

        # Read data (channel/antennas/pols/samples)
        data, timestamps = channel_reader.read_data(timestamp=timestamp,
                                                    tile_id=tile,
                                                    n_samples=self._nof_samples)

        logging.info("Read data")

        # Re-arrange data to required ordering
        data = np.transpose(data, (1, 0, 2, 3))
        data = np.transpose(data, (0, 1, 3, 2))
        data = np.transpose(data, (2, 1, 0, 3))

        # Format data as required for xGPU
        gpu_data = np.column_stack((data['real'].flatten(), data['imag'].flatten())).flatten()

        # Format data as required for CPU
        cpu_data = (data['real'] + 1j * data['imag']).astype(np.complex64)

        # Correlate using xGPU
        gpu_result = self.correlate_xgpu(gpu_data)

        # Correlate using CPU
        cpu_result = self.correlate_numpy(cpu_data)

        import matplotlib.pyplot as plt
        plt.scatter(list(range(len(cpu_result[:, 0]))), cpu_result[:, 0], marker='x', label='CPU XX')
        plt.scatter(list(range(len(gpu_result[:, 0]))), gpu_result[:, 0], marker='+', label='GPU XX')
        plt.scatter(list(range(len(cpu_result[:, 3]))), cpu_result[:, 3], marker='x', label='CPU YY')
        plt.scatter(list(range(len(gpu_result[:, 3]))), gpu_result[:, 3], marker='+', label='GPU YY')
        plt.xlabel('Baseline')
        plt.ylabel('Normalised value')
        plt.legend()
        plt.show()

    def correlate_xgpu(self, data):
        """ Data must be in the following format:
                [time][channel][antenna][polarization][complexity]"""
        logging.info("Correlating on GPU")
        nof_baselines = int((self._nof_antennas + 1) * 0.5 * self._nof_antennas)
        
        # Call xGPU
        result = self._library.correlate(data.ctypes.data_as(ctypes.POINTER(ctypes.c_int8)))
        
        # Interpret correlated results
        buffer_from_memory = ctypes.pythonapi.PyBuffer_FromMemory
        buffer_from_memory.restype = ctypes.py_object

        values = buffer_from_memory(result, Py_ssize_t(np.dtype(np.complex64).itemsize * nof_baselines * 4))
        values = np.frombuffer(values, np.complex64)

        # Convert from lower triangular to upper triangular form        
        values = np.conj(values).reshape(nof_baselines, 4)
        grid = np.zeros((self._nof_antennas, self._nof_antennas, 4), dtype=np.complex64) 

        counter = 0
        for i in range(self._nof_antennas):
            for j in range(i + 1):
                grid[j, i, :] = values[counter, :]
                counter += 1
        
        values = np.zeros((nof_baselines, 4), dtype=np.complex64)
        
        counter = 0
        for i in range(self._nof_antennas):
            for j in range(i, self._nof_antennas):
                values[counter, :] = grid[i, j, :]
                counter += 1

        return old_div(values, self._nof_samples)

    def correlate_numpy(self, data):
        """ Data must be in the following format:
                [time][channel][antenna][polarization][complexity]
                Compute in lower triangular form to match xGPU output"""

        logging.info("Correlating on CPU")

        nof_baselines = int((self._nof_antennas + 1) * 0.5 * self._nof_antennas)
        output = np.zeros((nof_baselines, 4), dtype=np.complex64)

        counter = 0
        for i in range(self._nof_antennas):
            for j in range(i, self._nof_antennas):
                output[counter, 0] = np.correlate(data[:, 0, i, 0], data[:, 0, j, 0])[0]
                output[counter, 1] = np.correlate(data[:, 0, i, 0], data[:, 0, j, 1])[0]
                output[counter, 2] = np.correlate(data[:, 0, i, 1], data[:, 0, j, 0])[0]
                output[counter, 3] = np.correlate(data[:, 0, i, 1], data[:, 0, j, 1])[0]
                counter += 1

        return old_div(output, self._nof_samples)

    def _initialise_library(self, filepath=None):
        """ Wrap AAVS DAQ shared library functionality in ctypes
        :param filepath: Path to library path
        """

        # This only need to be done once
        if self._library is not None:
            return None

        # Load AAVS DAQ shared library
        _library = None
        library_found = False
        if 'AAVS_INSTALL' in list(os.environ.keys()):
            # Check if library is in AAVS directory
            if os.path.exists("%s/lib/%s" % (os.environ['AAVS_INSTALL'], "libaavsdaq.so")):
                _library = "%s/lib/%s" % (os.environ['AAVS_INSTALL'], "libaavsdaq.so")
                library_found = True

        if not library_found:
            if filepath is None:
                _library = self._find("libaavsdaq.so", "/opt/aavs/lib")
                if _library is None:
                    _library = self._find("libaavsdaq.so", "/usr/local/lib")
                if _library is None:
                    _library = find_library("aavsdaq")

            else:
                _library = filepath

        if _library is None:
            raise Exception("AAVS DAQ library not found")

        print(_library)

        # Load library
        self._library = ctypes.CDLL(_library)

        # Define initialise_correlator
        self._library.initialise_correlator.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        self._library.initialise_correlator.restype = ctypes.c_int

        # Define correlate
        self._library.correlate.argtypes = [ctypes.POINTER(ctypes.c_int8)]
        self._library.correlate.restype = ctypes.POINTER(ctypes.c_float)
        
        logging.info("Initialised library")

    @staticmethod
    def _find(name, path):
        """ Find a file in a path
        :param name: File name
        :param path: Path to search in """
        for root, dirs, files in os.walk(path):
            if name in files:
                return os.path.join(root, name)

        return None


if __name__ == "__main__":
    # Use OptionParse to get command-line arguments
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %offline_gpu_correlator [options]")
    parser.add_option("-a", "--nof_antennas", action="store", dest="nof_antennas",
                      type="int", default=16, help="Number of antennas [default: 16]")
    parser.add_option("-s", "--nof_samples", action="store", dest="nof_samples",
                      type="int", default=1048576, help="Number of channels [default: 1048576]")
    parser.add_option("-f", "--file", action="store", dest="file",
                      default=None, help="File to plot [default: None]")
    conf, args = parser.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.DEBUG)
    str_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    from sys import stdout

    ch = logging.StreamHandler(stdout)
    ch.setFormatter(str_format)
    log.addHandler(ch)

    # File sanity checks
    if conf.file is None:
        logging.error("A filepath must be specified. Exiting")
        exit()

    # Initialise correlator
    corr = StandaloneCorrelator(conf.nof_antennas, conf.nof_samples)
    corr.process_file(conf.file)
