import math
import datetime
import time
import numpy as np

# Data type mape
FILE_NAME_MAP = {b'type': 0,
                 b'mode': 1,
                 b'objectid': 2,
                 b'time1':  3,
		         b'time2' : 4,
		         b'partition' : 5}


def complex_imaginary(value):
    """
    Returns the imaginary part of a complex tuple value.
    :param value: A complex number tuple (real and imaginary parts)
    :return:
    """
    return value[1]


def complex_real(value):
    """
    Returns the real part of a complex tuple value.
    :param value: A complex number tuple (real and imaginary parts)
    :return:
    """
    return value[0]


def complex_phase(value):
    """
    Returns the phase of a complex tuple value.
    :param value: A complex number tuple (real and imaginary parts)
    :return:
    """
    return math.atan2(value[1], value[0])


def complex_abs(value):
    """
    Returns the absolute (amplitude) of a complex tuple value as the square root of the PSD
    :param value: A complex number tuple (real and imaginary parts)
    :return:
    """
    return math.sqrt((value[0] ** 2) + (value[1] ** 2))


def complex_power(value):
    """
    Returns the power of a complex tuple value.
    :param value: A complex number tuple (real and imaginary parts)
    :return:
    """
    return (value[0] ** 2) + (value[1] ** 2)


def range_array(start_idx, end_idx):
    """
    Creates an array with a range of values (integers)
    :param start_idx: Start of range
    :param end_idx: End of range
    :return:
    """
    return range(start_idx, end_idx)


def step_range(low, up, leng):
    """
    This method returns a range from low to up, with a particular step size dependent on how many items should be
    in the range..
    :param low: Range start.
    :param up: Range limit.
    :param leng: Number of items in the range.
    :return: A range of values.
    """
    return np.linspace(low, up, leng, dtype=np.float128)
    # step = ((up - low) * 1.0 / leng)
    # return [low + i * step for i in range(leng)]


def get_date_time(timestamp=None):
    """
    Returns a string date/time from a UNIX timestamp.
    :param timestamp: A UNIX timestamp.
    :return: A date/time string of the form yyyymmdd_secs
    """
    if timestamp is None:
        timestamp = 0

    datetime_object = datetime.datetime.fromtimestamp(timestamp)
    hours = datetime_object.hour
    minutes = datetime_object.minute
    seconds = datetime_object.second
    full_seconds = seconds + (minutes * 60) + (hours * 60 * 60)
    full_seconds_formatted = format(full_seconds, '05')
    base_date_string = datetime.datetime.fromtimestamp(timestamp).strftime('%Y%m%d')
    full_date_string = base_date_string + '_' + str(full_seconds_formatted)
    return str(full_date_string)


def get_timestamp(date_time_string):
    """
    Returns a UNIX timestamp from a data/time string.
    :param date_time_string: A date/time string of the form %Y%m%d_seconds
    :return: A UNIX timestamp (seconds)
    """
    time_parts = date_time_string.split('_')
    d = datetime.datetime.strptime(time_parts[0], "%Y%m%d")  # "%d/%m/%Y %H:%M:%S"
    timestamp = time.mktime(d.timetuple())
    timestamp += int(time_parts[1])
    return timestamp
