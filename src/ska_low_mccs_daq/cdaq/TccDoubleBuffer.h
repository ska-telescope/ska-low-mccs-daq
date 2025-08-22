//
// Created by Tom Moynihan on 22/08/2025.
//
#include "DoubleBuffer.h"

struct TccDoubleBuffer : public DoubleBuffer {
    using DoubleBuffer::DoubleBuffer; // inherit ctor
protected:
    void copy_data(uint32_t producer_index,
                   uint16_t start_antenna, uint16_t nof_included_antennas,
                   uint64_t start_sample_index, uint32_t samples,
                   uint16_t *data_ptr, double timestamp) override;
};