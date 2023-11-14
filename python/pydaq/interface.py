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
aavsdaq_library = f"{aavs_install_path}/lib/libaavsdaq.so".encode('ASCII')
library = None

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
    global aavsdaq_library
    global library

    # This only need to be done once
    if library is not None:
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
    library = ctypes.CDLL(_library)

    # Define attachLogger
    library.attachLogger.argtypes = [LOGGER_CALLBACK]
    library.attachLogger.restype = None

    # Define startReceiver function
    library.startReceiver.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_uint32]
    library.startReceiver.restype = ctypes.c_int

    library.startReceiverThreaded.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32,
                                              ctypes.c_uint32, ctypes.c_uint32]
    library.startReceiverThreaded.restype = ctypes.c_int

    # Define stopReceiver function
    library.stopReceiver.argtypes = []
    library.stopReceiver.restype = ctypes.c_int

    # Define loadConsumer function
    library.loadConsumer.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    library.loadConsumer.restype = ctypes.c_int

    # Define initialiseConsumer function
    library.initialiseConsumer.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    library.initialiseConsumer.restype = ctypes.c_int

    # Define startConsumer function
    library.startConsumer.argtypes = [ctypes.c_char_p, DATA_CALLBACK]
    library.startConsumer.restype = ctypes.c_int

    # Define stopConsumer function
    library.stopConsumer.argtypes = [ctypes.c_char_p]
    library.stopConsumer.restype = ctypes.c_int

    # Locate aavsdaq.so
    if filepath is not None:
        aavsdaq_library = filepath
    else:
        aavs_install_path = os.environ.get("AAVS_INSTALL", "/opt/aavs")
        aavsdaq_library = find("libaavsdaq.so", f"{aavs_install_path}/lib")
        if aavsdaq_library is None:
            aavsdaq_library = find("libaavsdaq.so", "/usr/local/lib")
        if aavsdaq_library is None:
            aavsdaq_library = find_library("aavsdaq")

    aavsdaq_library = aavsdaq_library.encode()
    
# ------------- Function wrappers to library ---------------------------


def call_attach_logger(logging_callback):
    """ Attach logger
    :param logging_callback: Function which will process logs """
    global library
    library.attachLogger(logging_callback)


def call_start_receiver(interface, ip, frame_size, frames_per_block, nof_blocks):
    """ Start network receiver thread
    :param ip: IP address
    :param interface: Interface name
    :param frame_size: Maximum frame size
    :param frames_per_block: Frames per block
    :param nof_blocks: Number of blocks
    :return: Return code
    """
    global library
    return library.startReceiver(interface, ip, frame_size, frames_per_block, nof_blocks)

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
    global library
    return library.startReceiverThreaded(interface, ip, frame_size, frames_per_block, nof_blocks, nof_threads)

def call_stop_receiver():
    """ Stop network receiver thread """
    global library
    return library.stopReceiver()


def call_add_receiver_port(port):
    """ Add receive port to receiver
    :param port: Port number
    :return: Return code
    """
    global library
    return library.addReceiverPort(port)


def start_consumer(consumer, configuration, callback=None):
    """ Start consumer
    :param consumer: String representation of consumer
    :param configuration: Dictionary containing consumer configuration
    :param callback: Callback function
    :return: Return code """
    global library

    # Change str type
    consumer = consumer.encode()

    # Load consumer
    res = library.loadConsumer(aavsdaq_library, consumer)
    if res != Result.Success.value:
        return Result.Failure

    # Generate JSON from configuration and initialise consumer
    res = library.initialiseConsumer(consumer, json.dumps(configuration).encode())
    if res != Result.Success.value:
        return Result.Failure

    # Start consumer
    res = library.startConsumer(consumer, callback)
    if res != Result.Success.value:
        return Result.Failure

    return Result.Success


def stop_consumer(consumer):
    """ Stop raw data consumer
    :return: Return code
    """
    
    # Change str type
    consumer = consumer.encode()

    if library.stopConsumer(consumer) == Result.Success.value:
        return Result.Success
    else:
        return Result.Failure
