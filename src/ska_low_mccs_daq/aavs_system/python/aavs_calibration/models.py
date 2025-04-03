from builtins import str
from mongoengine import Document, IntField, FloatField, StringField, ObjectIdField, ListField, DateTimeField
from aavs_calibration.definitions import *


class Station(Document):
    """ Stores static data about a station """

    # Station name
    name = StringField(unique=True, required=True)

    # Number of antennas in station
    nof_antennas = IntField(required=True)

    # Antenna type
    antenna_type = StringField(required=True)

    # List of TPM pertaining to station
    tpms = ListField(required=True)

    # Longitude and Latitude of station center
    longitude = FloatField()
    latitude = FloatField()


class Antenna(Document):
    """ Stores static data about an antenna and the status for both pols """

    # Antenna index (ADC input) within the station
    antenna_station_id = IntField(required=True)

    # Antenna station identifier
    station_id = ObjectIdField(required=True)

    # Meters from the station center in x direction
    x_pos = FloatField(required=True)

    # Meters from the station center in y direction
    y_pos = FloatField(required=True)

    # Meters from the station center in y direction
    z_pos = FloatField()

    # Base id where antenna is located
    base_id = IntField()

    # TPM identifier to which antenna is connected
    tpm_id = IntField(required=True)

    # Name of TPM to which antenna is connected
    tpm_name = StringField()

    # PREADU RX input
    tpm_rx = IntField()

    # Status of X and Y signals
    status_x = StringField()
    status_y = StringField()

    def __str__(self):
        return 'id: ' + str(self.antenna_station_id).rjust(2) \
               + ' x: ' + str(self.x_pos).rjust(4) \
               + ' y: ' + str(self.y_pos).rjust(4) \
               + ' tpm: ' + str(self.tpm_id).rjust(1) \
               + ' rx: ' + str(self.tpm_rx).rjust(2)


class CalibrationSolution(Document):
    """ Stores data of a fit for a pol of an antenna """

    # UNIX timestamp, use function get_acquisition_time to get datetime instead of timestamp
    acquisition_time = DateTimeField(required=True)

    # Polarisation. 0 for X and 1 for Y
    pol = IntField(required=True, min_value=0, max_value=1)

    # Internal database id of the antenna
    antenna_id = ObjectIdField(required=True)

    # UNIX timestamp, use function get_fit_time to get datetime instead of timestamp
    fit_time = DateTimeField(required=True)

    # Amplitude for each frequency channel
    amplitude = ListField(required=True)

    # Phase for each frequency channel
    phase = ListField(required=True)

    # Compute phase_0 and delay for entire frequency range for given antenna/polarisation
    phase_0 = FloatField()
    delay = FloatField()

    # Placeholder for comments and flags
    fit_comment = StringField()
    flags = StringField()

    # Create an index on fit_time and acquisition_time, in descending order (later one first)
    meta = {'indexes': [{'fields': ['-fit_time', '-acquisition_time']}]}

    def get_acquisition_time(self):
        """ Returns datetime of the timestamp including time zone info """
        return convert_timestamp_to_datetime(self.acquisition_time)

    def set_acquisition_time(self, dt):
        """ Converts datetime to timestamp and saves it to the db"""
        self.acquisition_time = convert_datetime_to_timestamp(dt)
        self.save()

    def get_fit_time(self):
        """ Returns datetime of the timestamp including time zone info """
        return convert_timestamp_to_datetime(self.fit_time)

    def set_fit_time(self, dt):
        """ Converts datetime to timestamp and saves it to the db"""
        self.fit_time = convert_datetime_to_timestamp(dt)
        self.save()

    def __str__(self):
        return 'id: ' + str(self.antenna_id).rjust(2) + ' fit_time: ' + str(self.fit_time)


class CalibrationCoefficient(Document):
    """ Stores coefficient for a calibration per pol and per antenna """

    # Internal database id of the antenna
    antenna_id = ObjectIdField(required=True)

    # Polarisation. 0 for X and 1 for Y
    pol = IntField(required=True)

    # List of complex coefficients, use set_calibrations to store and get_calibrations to retrieve
    calibration_coefficients_real = ListField(required=True)
    calibration_coefficients_imag = ListField(required=True)

    # UNIX timestamp, use function to get_download_time to get datetime with timezone info
    download_time = DateTimeField(required=True)

    def get_download_time(self):
        """ Returns datetime of the timestamp including time zone info """
        return convert_timestamp_to_datetime(self.download_time)

    def set_download_time(self, dt):
        """ Converts datetime to timestamp and saves it to the db"""
        self.download_time = convert_datetime_to_timestamp(dt)


class FibreDelay(Document):
    """ Store fibre delay measurements through fibre loopback """

    # Frequency at which signal was generated
    frequency = FloatField(required=True)

    # Delay between reference and test signal
    delay = FloatField(required=True)

    # Time at which measurement was taken
    measurement_time = DateTimeField(required=True)
