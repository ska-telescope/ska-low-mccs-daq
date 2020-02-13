import numpy

from enum import Enum

class FileTypes(Enum):
    Raw = 1
    Channel = 2
    Beamformed = 3
    Correlation = 4
    StationBeamformed = 5

class FileDAQModes(Enum):
    Void  = 1
    Burst = 2
    Integrated = 3
    Continuous = 4

# 8-bit complex numpy type
complex_8t = numpy.dtype([('real', numpy.int8), ('imag', numpy.int8)])
complex_16t = numpy.dtype([('real', numpy.int16), ('imag', numpy.int16)])

# Data type mape
DATA_TYPE_MAP = {b'complex': complex_8t,
                 b'complex16': complex_16t,
                 b'complex64': numpy.complex64,
                 b'uint16':  numpy.uint16,
		         b'int8' : numpy.int8,
		         b'uint8' : numpy.uint8,
                 b'uint32' : numpy.uint32}
