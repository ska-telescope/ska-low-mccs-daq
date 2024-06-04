import ctypes
import json
import os
from ctypes.util import find_library

from enum import Enum


# AAVS DAQ library
# TODO: make this nicer

# ------------------------------ Enumerations --------------------------------


class Complex8t(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int8),
                ("y", ctypes.c_int8)]


class Complex16t(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int16),
                ("y", ctypes.c_int16)]


class Complex32t(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32),
                ("y", ctypes.c_int32)]


class DataType(Enum):
    """ DataType enumeration """
    RawData = 1
    ChannelisedData = 2
    BeamData = 3


class Result(Enum):
    """ Result enumeration """
    Success = 0
    Failure = -1
    ReceiverUninitialised = -2
    ConsumerAlreadyInitialised = -3


class LogLevel(Enum):
    """ Log level"""
    Fatal = 1
    Error = 2
    Warning = 3
    Info = 4
    Debug = 5

# ---------------------------- Wrap library calls ----------------------------


# Global store for interface objects
aavs_install_path = os.environ.get("AAVS_INSTALL", "/opt/aavs")
aavsdaq_library_path = f"{aavs_install_path}/lib/libaavsdaq.so".encode('ASCII')
aavsstationbeam_library_path = f"{aavs_install_path}/lib/libaavsstationbeam.so".encode('ASCII')
aavsdaq_library = None
aavsstationbeam_library = None

# Define consumer data callback wrapper
DATA_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_void_p), ctypes.c_double,
                                 ctypes.c_uint32, ctypes.c_uint32)

# Define logging callback wrapper
LOGGER_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p)


def find(name, path):
    """ Find a file in a path
    :param name: File name
    :param path: Path to search in """
    for root, dirs, files in os.walk(path):
        if name in files:
            return os.path.join(root, name)

    return None


def initialise_library(filepath=None):
    """ Wrap AAVS DAQ shared library functionality in ctypes
    :param filepath: Path to library path
    """
    global aavsdaq_library_path
    global aavsdaq_library

    # This only need to be done once
    if aavsdaq_library is not None:
        return None

    # Load AAVS DAQ shared library
    _library = None
    library_found = False
    if 'AAVS_INSTALL' in list(os.environ.keys()):
        # Check if library is in AAVS directory
        if os.path.exists("%s/lib/%s" % (os.environ['AAVS_INSTALL'], "libdaq.so")):
            _library = "%s/lib/%s" % (os.environ['AAVS_INSTALL'], "libdaq.so")
            library_found = True

    if not library_found:
        _library = find("libdaq.so", "/opt/aavs/lib")
        if _library is None:
            _library = find("libdaq.so", "/usr/local/lib")
        if _library is None:
            _library = find_library("daq")

    if _library is None:
        raise Exception("AAVS DAQ library not found")

    # Load library
    aavsdaq_library = ctypes.CDLL(_library)

    # Define attachLogger
    aavsdaq_library.attachLogger.argtypes = [LOGGER_CALLBACK]
    aavsdaq_library.attachLogger.restype = None

    # Define startReceiver function
    aavsdaq_library.startReceiver.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32,
                                              ctypes.c_uint32]
    aavsdaq_library.startReceiver.restype = ctypes.c_int

    aavsdaq_library.startReceiverThreaded.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32,
                                                      ctypes.c_uint32, ctypes.c_uint32]
    aavsdaq_library.startReceiverThreaded.restype = ctypes.c_int

    # Define stopReceiver function
    aavsdaq_library.stopReceiver.argtypes = []
    aavsdaq_library.stopReceiver.restype = ctypes.c_int

    # Define loadConsumer function
    aavsdaq_library.loadConsumer.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    aavsdaq_library.loadConsumer.restype = ctypes.c_int

    # Define initialiseConsumer function
    aavsdaq_library.initialiseConsumer.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    aavsdaq_library.initialiseConsumer.restype = ctypes.c_int

    # Define startConsumer function
    aavsdaq_library.startConsumer.argtypes = [ctypes.c_char_p, DATA_CALLBACK]
    aavsdaq_library.startConsumer.restype = ctypes.c_int

    # Define stopConsumer function
    aavsdaq_library.stopConsumer.argtypes = [ctypes.c_char_p]
    aavsdaq_library.stopConsumer.restype = ctypes.c_int

    # Locate aavsdaq.so
    if filepath is not None:
        aavsdaq_library_path = filepath
    else:
        aavs_install_path = os.environ.get("AAVS_INSTALL", "/opt/aavs")
        aavsdaq_library_path = find("libaavsdaq.so", f"{aavs_install_path}/lib")
        if aavsdaq_library_path is None:
            aavsdaq_library_path = find("libaavsdaq.so", "/usr/local/lib")
        if aavsdaq_library_path is None:
            aavsdaq_library_path = find_library("aavsdaq")

    aavsdaq_library_path = aavsdaq_library_path.encode()

def initialise_station_beam_library(filepath=None):
    """ Wrap AAVS DAQ shared library functionality in ctypes
    :param filepath: Path to library path
    """
    global aavstationbeam_library_path
    global aavsstationbeam_library

    # This only need to be done once
    if aavsstationbeam_library is not None:
        return None

    # Load AAVS DAQ shared library
    _library = None
    library_found = False
    if 'AAVS_INSTALL' in list(os.environ.keys()):
        # Check if library is in AAVS directory
        if os.path.exists("%s/lib/%s" % (os.environ['AAVS_INSTALL'], "libaavsstationbeam.so")):
            _library = "%s/lib/%s" % (os.environ['AAVS_INSTALL'], "libaavsstationbeam.so")
            library_found = True

    if not library_found:
        _library = find("libaavsstationbeam.so", "/opt/aavs/lib")
        if _library is None:
            _library = find("libaavsstationbeam.so", "/usr/local/lib")
        if _library is None:
            _library = find_library("daq")

    if _library is None:
        raise Exception("AAVS Station Beam library not found")

    aavstationbeam_library_path = _library.encode()

    # Load library
    aavsstationbeam_library = ctypes.CDLL(_library)

    # Define start capture
    aavsstationbeam_library.start_capture.argtypes = [ctypes.c_char_p]
    aavsstationbeam_library.start_capture.restype = ctypes.c_int

    # Define stop capture
    aavsstationbeam_library.stop_capture.argtypes = []
    aavsstationbeam_library.stop_capture.restype = ctypes.c_int


# ------------- Function wrappers to library ---------------------------


def call_attach_logger(logging_callback):
    """ Attach logger
    :param logging_callback: Function which will process logs """
    global aavsdaq_library
    aavsdaq_library.attachLogger(logging_callback)


def call_start_receiver(interface, ip, frame_size, frames_per_block, nof_blocks):
    """ Start network receiver thread
    :param ip: IP address
    :param interface: Interface name
    :param frame_size: Maximum frame size
    :param frames_per_block: Frames per block
    :param nof_blocks: Number of blocks
    :return: Return code
    """
    global aavsdaq_library
    return aavsdaq_library.startReceiver(interface, ip, frame_size, frames_per_block, nof_blocks)

def call_start_receiver_threaded(interface, ip, frame_size, frames_per_block, nof_blocks, nof_threads):
    """ Start network receiver thread
    :param ip: IP address
    :param interface: Interface name
    :param frame_size: Maximum frame size
    :param frames_per_block: Frames per block
    :param nof_blocks: Number of blocks
    :param nof_threads: Number of threads
    :return: Return code
    """
    global aavsdaq_library
    return aavsdaq_library.startReceiverThreaded(interface, ip, frame_size, frames_per_block, nof_blocks, nof_threads)

def call_stop_receiver():
    """ Stop network receiver thread """
    global aavsdaq_library
    return aavsdaq_library.stopReceiver()


def call_add_receiver_port(port):
    """ Add receive port to receiver
    :param port: Port number
    :return: Return code
    """
    global aavsdaq_library
    return aavsdaq_library.addReceiverPort(port)


def start_consumer(consumer, configuration, callback=None):
    """ Start consumer
    :param consumer: String representation of consumer
    :param configuration: Dictionary containing consumer configuration
    :param callback: Callback function
    :return: Return code """
    global aavsdaq_library

    # Change str type
    consumer = consumer.encode()

    # Load consumer
    res = aavsdaq_library.loadConsumer(aavsdaq_library_path, consumer)
    if res != Result.Success.value:
        return Result.Failure

    # Generate JSON from configuration and initialise consumer
    res = aavsdaq_library.initialiseConsumer(consumer, json.dumps(configuration).encode())
    if res != Result.Success.value:
        return Result.Failure

    # Start consumer
    res = aavsdaq_library.startConsumer(consumer, callback)
    if res != Result.Success.value:
        return Result.Failure

    return Result.Success


def stop_consumer(consumer):
    """ Stop raw data consumer
    :return: Return code
    """
    
    # Change str type
    consumer = consumer.encode()

    if aavsdaq_library.stopConsumer(consumer) == Result.Success.value:
        return Result.Success
    else:
        return Result.Failure


def call_start_raw_station_acqusition(configuration):
    """ Start receiving raw station beam data """
    if aavsstationbeam_library.start_capture(json.dumps(configuration).encode()) == Result.Success.value:
        return Result.Success
    else:
        return Restult.Failure


def call_stop_raw_station_acquisition():
    """ Stop receiving raw station beam data """
    if aavsstationbeam_library.stop_capture() == Result.Success.value:
        return Result.Success
    else:
        return Result.Failure
