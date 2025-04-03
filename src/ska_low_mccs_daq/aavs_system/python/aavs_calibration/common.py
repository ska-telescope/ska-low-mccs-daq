from builtins import next
import logging

from aavs_calibration import database
from aavs_calibration.definitions import *
from aavs_calibration.models import CalibrationSolution, Station, CalibrationCoefficient

import numpy as np
import pymongo

# Connect to database (once for thread safety)
db = database.connect()


def change_antenna_status(station_id, base_id, polarisation, status):
    """ Change the status of an antenna """

    # Query to find and update depends on polarisation
    if polarisation == Polarisation.X:
        r = db.antenna.find_one_and_update({'station_id': station_id, 'base_id': base_id},
                                           {"$set": {"status_x": status.name}})
    elif polarisation == Polarisation.Y:
        r = db.antenna.find_one_and_update({'station_id': station_id, 'base_id': base_id},
                                           {"$set": {"status_x": status.name}})
    else:
        r = db.antenna.find_one_and_update({'station_id': station_id, 'base_id': base_id},
                                           {"$set": {"status_x": status.name, "status_y": status.name}})

    return r


def get_station_list():
    """ Get the list of station stored in the database """
    station = Station.objects()
    station_names = []
    for s in station:
        station_names.append(s.name)
    return station_names

def get_antenna_tile_names(station):
    """ Get the names of the tiles to which antennas are connected """
    
    # Get station info
    station = get_station_information(station)
    if station is None:
        logging.warning("Could not find station {}".format(station))

    # Get info
    tile_names = []
    for item in db.antenna.find({'station_id': station.id},
                                {'tpm_name': 1, '_id': 0}).sort("antenna_station_id", pymongo.ASCENDING):
        tile_names.append(item['tpm_name'])

    return tile_names

def get_antenna_positions(station):
    """ Get antenna positions for a given station id"""

    # Get station info
    station = get_station_information(station)
    if station is None:
        logging.warning("Could not find station {}".format(station))

    # Create lists with base_id, x and y pos and return
    base, x, y = [], [], []
    for item in db.antenna.find({'station_id': station.id},
                                {'base_id': 1, 'x_pos': 1, 'y_pos': 1, '_id': 0}).sort("antenna_station_id",
                                                                                       pymongo.ASCENDING):
        base.append(item['base_id'])
        x.append(item['x_pos'])
        y.append(item['y_pos'])

    return base, x, y


def get_station_information(station):
    """ Get station information """

    # Get station info
    station = Station.objects(name=station)
    if len(station) == 0:
        return None

    return station.first()


def add_new_calibration_solution(station, acquisition_time, solution, comment="",
                                 delay_x=None, phase_x=None, delay_y=None, phase_y=None):
    """ Add a new calibration fit to the database.
    :param station: Station identifier
    :param acquisition_time: The time at which the data was acquired
    :param solution: A 4D array containing the computed solutions. The array should be
                     in antenna/pol/frequency/(amp/pha), where for the last dimension
                     index 0 is amplitude and index 1 is phase.
    :param comment: Any user-defined comment to add to the fit"
    :param delay_x: Computed solution gradient for X pol, all antennas
    :param phase_x: Computed solution intercept for X pol, all antennas
    :param delay_y: Computed solution gradient for Y pol, all antennas
    :param phase_y: Computed solution intercept for Y pol, all antennas"""

    # Convert timestamps
    acquisition_time = convert_timestamp_to_datetime(acquisition_time)
    fit_time = datetime.utcnow()

    # Grab all antenna for station and sort in order in which fits are provided
    station = Station.objects(name=station)

    if len(station) == 0:
        logging.warning("Station {} not found in calibration database, not adding new calibration solutions")

    station_info = station.first()
    antennas = db.antenna.find({'station_id': station_info.id}).sort("antenna_station_id", pymongo.ASCENDING)

    # Sanity checks on delay and phase values
    if delay_x is not None and len(delay_x) != antennas.count():
        logging.warning("Number of delay and phase values does not match number of antennas. Ignoring")
        delay_x = delay_y = phase_x = phase_y = [None] * antennas.count()
    elif delay_y is None:
        delay_x = delay_y = phase_x = phase_y = [None] * antennas.count()

    # Loop over all antennas and save solutions to database
    for antenna in antennas:
        # Use base index to select correct antenna coefficients
        base_index = antenna['base_id'] - 1

        # Create X and Y fit solutions
        CalibrationSolution(acquisition_time=acquisition_time,
                            fit_time=fit_time,
                            pol=0,
                            antenna_id=antenna['_id'],
                            fit_comment=comment,
                            flags='',
                            amplitude=solution[base_index, 0, :, 0],
                            phase=solution[base_index, 0, :, 1],
                            phase_0=phase_x[base_index],
                            delay=delay_x[base_index]).save()

        CalibrationSolution(acquisition_time=acquisition_time,
                            fit_time=fit_time,
                            pol=1,
                            antenna_id=antenna['_id'],
                            fit_comment=comment,
                            flags='',
                            amplitude=solution[base_index, 1, :, 0],
                            phase=solution[base_index, 1, :, 1],
                            phase_0=phase_y[base_index],
                            delay=delay_y[base_index]).save()


def add_coefficient_download(station, download_time, coefficients):
    """ Add a new calibration download entry to the database.
    :param station: Station identifier
    :param download_time: Time at which coefficients were downloaded to the station
    :param coefficients: A 3D array containing the complex coefficients downloaded to the station.
                         The array should be in antenna/pol/frequency order."""

    # Convert timestamps
    download_time = convert_timestamp_to_datetime(download_time)

    # Grab all antenna for station and sort in order in which fits are provided
    station = Station.objects(name=station)

    if len(station) == 0:
        logging.warning("Station {} not found in calibration database, not adding new downloaded coefficients")

    station_info = station.first()
    antennas = db.antenna.find({'station_id': station_info.id}).sort("antenna_station_id", pymongo.ASCENDING)

    for a, antenna in enumerate(antennas):
        CalibrationCoefficient(antenna_id=antenna['_id'],
                               pol=0,
                               calibration_coefficients_real=coefficients[a, 0, :].real,
                               calibration_coefficients_imag=coefficients[a, 0, :].imag,
                               download_time=download_time).save()

        CalibrationCoefficient(antenna_id=antenna['_id'],
                               pol=1,
                               calibration_coefficients_real=coefficients[a, 1, :].real,
                               calibration_coefficients_imag=coefficients[a, 1, :].imag,
                               download_time=download_time).save()


def get_latest_calibration_solution(station, include_delays=False):
    """ Get the latest calibration solution
    :param station: Station identifier
    :param include_delays: Include phase delays in return"""

    # Grab all antenna for station and sort in order in which fits are provided
    station = Station.objects(name=station)

    if len(station) == 0:
        logging.warning("Station {} not found in calibration database, not grabbing calibration solutions")

    station_info = station.first()
    antennas = db.antenna.find({'station_id': station_info.id}).sort("antenna_station_id", pymongo.ASCENDING)

    # Generate arrays to store amp and phase
    amplitudes = np.zeros((antennas.count(), 2, 512))
    phases = np.zeros((antennas.count(), 2, 512))

    phase0, delays = None, None
    if include_delays:
        phase0 = np.zeros((antennas.count(), 2))
        delays = np.zeros((antennas.count(), 2))

    # Loop over all antennas
    for antenna in antennas:

        # Grab values for polarisation X
        results = db.calibration_solution.aggregate([
            {'$sort': {'acquisition_time': -1, 'fit_time': -1}},
            {'$match': {'antenna_id': antenna['_id'], 'pol': 0}},
            {'$limit': 1}])

        # If there are no entries for this antenna/pol, set to 0
        try:
            entry = next(results)

            amplitudes[antenna['antenna_station_id'], 0, :] = entry['amplitude']
            phases[antenna['antenna_station_id'], 0, :] = entry['phase']

            if include_delays:
                delays[antenna['antenna_station_id'], 0] = entry['delay']
                phase0[antenna['antenna_station_id'], 0] = entry['phase_0']

        except StopIteration:
            pass

        # Grab values for polarisation Y
        results = db.calibration_solution.aggregate([
            {'$sort': {'acquisition_time': -1, 'fit_time': -1}},
            {'$match': {'antenna_id': antenna['_id'], 'pol': 1}},
            {'$limit': 1}])

        # If there are not entries for this antenna/pol, set to 0
        try:
            entry = next(results)

            amplitudes[antenna['antenna_station_id'], 1, :] = entry['amplitude']
            phases[antenna['antenna_station_id'], 1, :] = entry['phase']

            if include_delays:
                delays[antenna['antenna_station_id'], 1] = entry['delay']
                phase0[antenna['antenna_station_id'], 1] = entry['phase_0']
        except StopIteration:
            pass

    if include_delays:
        return amplitudes, phases, phase0, delays
    else:
        return amplitudes, phases


def get_calibration_solution(station, timestamp):
    """ Get the calibration coefficients closest to the provided timestamp
    :param station: The station identifier
    :param timestamp: Timestamp closest to which coefficients are required"""

    # Grab all antenna for station and sort in order in which firs are provided
    station = Station.objects(name=station)

    if len(station) == 0:
        logging.warning("Station {} not found in calibration database, not grabbing calibration solutions")
        return

    station_info = station.first()
    antennas = db.antenna.find({'station_id': station_info.id}).sort("antenna_station_id", pymongo.ASCENDING)

    # Generate arrays to store amp and phase
    amplitudes = np.zeros((antennas.count(), 2, 512))
    phases = np.zeros((antennas.count(), 2, 512))

    # Create datetime object from timestamp
    if type(timestamp) is float:
        timestamp = datetime.utcfromtimestamp(timestamp)
    elif type(timestamp) is not datetime:
        logging.warning("Invalid timestamp type, not grabbing calibration solutions")
        return

    # Get the acquisition time closest to the provided timestamp and
    # latest fit time for that acquisition
    result = db.calibration_solution.aggregate([
        {
            '$project': {
                'acquisition_time': 1,
                'fit_time': 1,
                'difference': {'$abs': {'$subtract': [timestamp, "$acquisition_time"]}} }
        },
        {'$sort': {'difference': 1}},
        {'$limit': 1}
    ])

    try:
        entry = next(result)
        acquisition_time = entry['acquisition_time']
        fit_time = entry['fit_time']
        logging.info("Using calibration solution acquired at {}, fitted on {}".format(acquisition_time, fit_time))
    except StopIteration:
        logging.error("No solutions found in database")
        return None, None

    # Loop over antennas
    for antenna in antennas:

        # Grab solution for current antenna for pol X
        solution = CalibrationSolution.objects(acquisition_time=acquisition_time,
                                               fit_time=fit_time,
                                               antenna_id=antenna['_id'],
                                               pol=0)

        if len(solution) != 1:
            continue

        entry = solution.first()
        amplitudes[antenna['antenna_station_id'], 0, :] = entry.amplitude
        phases[antenna['antenna_station_id'], 0, :] = entry.phase

        # Grab solution for current antenna for pol Y
        solution = CalibrationSolution.objects(acquisition_time=acquisition_time,
                                               fit_time=fit_time,
                                               antenna_id=antenna['_id'],
                                               pol=1)

        if len(solution) != 1:
            continue

        entry = solution.first()
        amplitudes[antenna['antenna_station_id'], 1, :] = entry.amplitude
        phases[antenna['antenna_station_id'], 1, :] = entry.phase

    return amplitudes, phases


def get_latest_coefficient_download(station):
    """ Get the latest downloaded calibration coefficients to the station
    :param station: The station identifier  """

    # Grab all antenna for station and sort in order in which fits are provided
    station = Station.objects(name=station)

    if len(station) == 0:
        logging.warning("Station {} not found in calibration database, not adding new calibration solutions")

    station_info = station.first()
    antennas = db.antenna.find({'station_id': station_info.id}).sort("antenna_station_id", pymongo.ASCENDING)

    # Generate arrays to store amp and phase
    coefficients = np.empty((antennas.count(), 2, 512), dtype=np.complex64)

    # Loop over all antennas
    for antenna in antennas:
        # Grab values for polarisation X
        results = db.calibration_coefficient.aggregate([
            {'$sort': {'download_time': -1}},
            {'$match': {'antenna_id': antenna['_id'], 'pol': 0}},
            {'$limit': 1}])
        entry = next(results)

        values = np.array(entry['calibration_coefficients_real']) + np.array(
            entry['calibration_coefficients_real']) * 1j
        coefficients[antenna['antenna_station_id'], 0, :] = values

        # Grab values for polarisation Y
        results = db.calibration_coefficient.aggregate([
            {'$sort': {'download_time': -1}},
            {'$match': {'antenna_id': antenna['_id'], 'pol': 1}},
            {'$limit': 1}])
        entry = next(results)

        values = np.array(entry['calibration_coefficients_real']) + np.array(
            entry['calibration_coefficients_real']) * 1j
        coefficients[antenna['antenna_station_id'], 0, :] = values

    return coefficients


if __name__ == "__main__":
    from numpy.random import random
    import time

    #
    # add_coefficient_download("AAVS1", time.time(), random((256, 2, 512)) + random((256, 2, 512)) * 1j)
    # print get_latest_coefficient_download("AAVS1")
    # exit()

    # solutions = random((256, 2, 512, 2)) * 360 - 180
    # delay = random(256) * 180
    # phase = np.zeros(256)
    #
    # t0 = time.time()
    # add_new_calibration_solution("AAVS1", time.time(), solutions, delay_x=delay, delay_y=delay,
    #                              phase_x=phase, phase_y=phase)
    # print("Persisted in {}".format(time.time() - t0))

    # print get_latest_calibration_solution("AAVS1", True)

    # t0 = time.time()
    # get_calibration_solution('AAVS1', datetime.now())
    # print(time.time() - t0)

    # print get_station_list()

    base, x, y = get_antenna_positions("EDA2")
    print(base, x, y)
