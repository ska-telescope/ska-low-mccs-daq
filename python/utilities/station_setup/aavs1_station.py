from aavs_calibration.definitions import AntennaType
from aavs_calibration.database import *
from urllib import urlopen

# Connect to database
db = connect()

# This is used to re-map ADC channels index to the RX
# number going into the TPM
# [Antenna number / RX]
antenna_preadu_mapping = {0: 1, 1: 2, 2: 3, 3: 4,
                          8: 5, 9: 6, 10: 7, 11: 8,
                          15: 9, 14: 10, 13: 11, 12: 12,
                          7: 13, 6: 14, 5: 15, 4: 16}

# Some global params
nof_antennas = 256

# Station name and location
station_name = "AAVS1"
lat, lon = -26.7040800497666666, 116.6702313536527778

# Order of TPMs
tpm_order = range(1, 17)
tpm_names = ["TPM {}".format(x) for x in tpm_order]


def populate_station():
    """ Reads antenna base locations from the Google Drive sheet and fills the data into the database """

    # Purge antennas from database
    # purge_station(station_name)

    # Antenna mapping placeholder

    # Read antenna location spreadsheet
    response = urlopen('https://docs.google.com/spreadsheets/d/e/2PACX-1vRIpaYPims9Qq9JEnZ3AfZtTaYJYWMsq2CWRgB-KKFAQOZo'
                       'EsV0NV2Gmz1fDfOJm7cjDAEBQWM4FgyP/pub?gid=220529610&single=true&output=tsv')

    html = response.read().split('\n')

    # Two antennas are not in-place, however we still get an input into the TPM
    switched_preadu_map = {y: x for x, y in antenna_preadu_mapping.iteritems()}

    # Antenna information placeholder
    antenna_information = []

    # Read all antenna rows from spreadsheet response
    for i in range(1, nof_antennas + 1):
        items = html[i].split('\t')
        # Parse antenna row
        try:
            base, tpm, rx = int(items[1]), int(items[7]), int(items[8])
            east, north, up = float(items[15].replace(',', '.')), float(items[17].replace(',', '.')), 0
            antenna_information.append({'base': base, 'tpm': tpm, 'rx': rx, 'east': east, 'north': north})
        except ValueError:
            pass

    # Add missing antennas in sheet
    antenna_information.append({'base': 3, 'tpm': 1, 'rx': 9, 'east': 17.525, 'north': -1.123})
    antenna_information.append({'base': 41, 'tpm': 11, 'rx': 9, 'east': 9.701, 'north': -14.627})

    # Check if station entry already exists
    if len(Station.objects(name=station_name)) == 0:
        Station(name=station_name,
                nof_antennas=256,
                antenna_type=AntennaType.SKALA2.name,
                tpms=tpm_order,
                latitude=lat,
                longitude=lon).save()

    # Grab station information
    station = Station.objects(name=station_name).first()

    for i, antenna in enumerate(antenna_information):
        # Fill data into database
        Antenna(antenna_station_id=(antenna['tpm'] - 1) * 16 + switched_preadu_map[antenna['rx']],
                station_id=station.id,
                x_pos=antenna['east'],
                y_pos=antenna['north'],
                base_id=antenna['base'],
                tpm_id=antenna['tpm'],
                tpm_rx=antenna['rx'],
                tpm_name=tpm_names[i / 16],
                status_x='',
                status_y='').save()


if __name__ == "__main__":
    populate_station()
