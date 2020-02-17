from aavs_calibration.definitions import AntennaType
from aavs_calibration.database import *

# Connect to database
db = connect()

# Some global params
nof_antennas = 256

# Station name and location
station_name = "UKPHASE0"
lat, lon = -26.70408005, 116.6702313527777778

# TPM order in configuration file
tpm_order = [24]


def populate_station():
    """ Create database entries for UK phase 0 setup """

    # Purge existent station (to be removed)
    # purge_station(station_name)

    # Check if station entry already exists and if not create it
    if len(Station.objects(name=station_name)) == 0:
        Station(name=station_name,
                nof_antennas=1,
                antenna_type=AntennaType.SKALA4.name,
                tpms=tpm_order,
                latitude=lat,
                longitude=lon).save()

    # Grab station information
    station = Station.objects(name=station_name).first()

    # Fill data into database
    for i in range(16):
        Antenna(antenna_station_id=i,
                station_id=station.id,
                tpm_name="TPM-{}".format(tpm_order[i / 16]),
                x_pos=0,
                y_pos=0,
                base_id=0,
                tpm_id=0,
                tpm_rx=0,
                status_x='',
                status_y='').save()


if __name__ == "__main__":
    populate_station()
