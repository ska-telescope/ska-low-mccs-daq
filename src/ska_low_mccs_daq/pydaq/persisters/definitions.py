from enum import Enum

import numpy


class FileTypes(Enum):
    Raw = 1
    Channel = 2
    Beamformed = 3
    Correlation = 4
    StationBeamformed = 5


class FileDAQModes(Enum):
    Void = 1
    Burst = 2
    Integrated = 3
    Continuous = 4
    Null = 5


class FileModes(Enum):
    Read = 1
    Write = 2


# 8-bit complex numpy type
complex_8t = numpy.dtype([("real", numpy.int8), ("imag", numpy.int8)])
complex_16t = numpy.dtype([("real", numpy.int16), ("imag", numpy.int16)])

# Data type map
DATA_TYPE_MAP = {
    "complex": complex_8t,
    "complex16": complex_16t,
    "complex64": numpy.complex64,
    "uint16": numpy.uint16,
    "int8": numpy.int8,
    "uint8": numpy.uint8,
    "uint32": numpy.uint32,
    "double": numpy.double,
}
