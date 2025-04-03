//
// Created by lessju on 03/06/2024.
//

#include "DAQ.h"

#ifndef AAVS_DAQ_ACQUIRE_STATION_BEAM_H
#define AAVS_DAQ_ACQUIRE_STATION_BEAM_H

extern "C" {
    RESULT start_capture(const char* json_string);
    RESULT stop_capture();
}

#endif //AAVS_DAQ_ACQUIRE_STATION_BEAM_H
