//
// Created by Tom Moynihan on 22/08/2025.
//
#include "TccDoubleBuffer.h"

void TccDoubleBuffer::copy_data(uint32_t producer_index,
                                      uint16_t start_antenna, uint16_t nof_included_antennas,
                                      uint64_t start_sample_index, uint32_t samples,
                                      uint16_t *data_ptr, double timestamp)
{
    // Target layout: [M][R][P][T], T=16; elements are still uint16_t holding {re_i8, im_i8}
    constexpr int TPB = 16;
    uint16_t *base = double_buffer[producer_index].data;

    for (uint32_t i = 0; i < samples; ++i) {
        const uint64_t ti = start_sample_index + i;
        const uint64_t m  = ti / TPB;  // block index
        const uint64_t t  = ti % TPB;  // time-in-block

        const uint64_t mt_off = m * (uint64_t)nof_antennas * nof_pols * TPB + t;

        for (uint16_t j = 0; j < nof_included_antennas; ++j) {
            const uint16_t r = start_antenna + j;
            for (uint8_t p = 0; p < nof_pols; ++p) {
                const uint64_t idx = (((uint64_t)r * nof_pols + p) * TPB) + mt_off;
                base[idx] = *data_ptr++;  // exact bits copied; no conversion
            }
        }
    }

    if (start_antenna == 0)
        this->double_buffer[producer_index].read_samples += samples;
    this->double_buffer[producer_index].nof_packets++;

    if (this->double_buffer[producer_index].ref_time > timestamp ||
        this->double_buffer[producer_index].ref_time == 0)
        this->double_buffer[producer_index].ref_time = timestamp;
}
