from datetime import datetime
from enum import Enum
import pytz


class AntennaType(Enum):
    """ Enumeration for antenna type """
    SKALA2 = 1
    SKALA4 = 2
    EDA = 4
    EDA2 = 8


class AntennaStatus(Enum):
    """ Enumeration for antenna status """
    ON = 1
    OFF = 2
    FAULTY = 4


class Polarisation(Enum):
    """ Enumeration for polarization identification """
    X = 1
    Y = 2
    ALL = 4


def convert_timestamp_to_datetime(timestamp):
    """
    converts timestamp to datetime
    :param timestamp: UNIX timestamp
    :return: datetime with UTC timezone
    """
    return datetime.utcfromtimestamp(timestamp).replace(tzinfo=pytz.UTC)


def convert_datetime_to_timestamp(dt):
    """
    converts datetime to timestamp
    :param dt: datetime, assumed to be UTC
    :return: UNIX timestamp
    """
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=pytz.UTC)
    return int((dt - datetime(1970, 1, 1, tzinfo=pytz.UTC)).total_seconds())
