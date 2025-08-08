//
// Created by lessju on 03/06/2024.
//

#include "DAQ.h"

#ifndef AAVS_DAQ_ACQUIRE_STATION_BEAM_H
#define AAVS_DAQ_ACQUIRE_STATION_BEAM_H

typedef struct external_station_metadata {
    unsigned nof_packets;
    unsigned buffer_counter;
} ExternalStationMetadata;
typedef void (*ExternalStationCallback)(external_station_metadata * metadata);

extern "C" {
    RESULT start_capture(const char* json_string, DiagnosticCallback diagnostic_callback = nullptr, ExternalStationCallback external_callback = nullptr);
    RESULT stop_capture();
}

#endif //AAVS_DAQ_ACQUIRE_STATION_BEAM_H
