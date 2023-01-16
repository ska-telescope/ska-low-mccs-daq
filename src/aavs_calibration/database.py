import logging

import mongoengine

from aavs_calibration.models import CalibrationSolution, CalibrationCoefficient, Antenna, Station

DB_NAME = 'aavs'    # change name to create another database
HOST = '10.0.10.200'  # insert IP address or url here
PORT = 27017        # mongodb standard port


def connect(db_name='', host='', port=''):
    """ connect to standard db, if not otherwise specified """
    if not db_name:
        db_name = DB_NAME
    if not host:
        host = HOST
    if not port:
        port = PORT
    connection = mongoengine.connect(db_name, host=host, port=port)
    return connection.aavs


def purge_database():
    """ Drops all collections """
    Antenna.drop_collection()
    Station.drop_collection()
    CalibrationSolution.drop_collection()
    CalibrationCoefficient.drop_collection()


def purge_fits():
    """ Drops all calibration-related collections """
    CalibrationSolution.drop_collection()
    CalibrationCoefficient.drop_collection()


def purge_station(station_name):
    """ Drops antenna collection"""

    # Connect to database
    db = connect()

    # Grab all antenna for station and sort in order in which fits are provided
    station = Station.objects(name=station_name)

    if len(station) == 0:
        logging.warning("Station {} not found in calibration database".format(station_name))
        return False

    station_info = station.first()
    antennas = db.antenna.find({'station_id': station_info.id})

    # Delete station antennas
    for antenna in antennas:
        db.antenna.remove({'_id': antenna['_id']})

    # Delete station
    station.delete()

    return True


if __name__ == "__main__":
    connect()
    # purge_fits()
