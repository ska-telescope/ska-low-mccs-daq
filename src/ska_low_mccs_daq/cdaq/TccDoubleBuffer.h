//
// Created by Tom Moynihan on 22/08/2025.
//
#pragma once
#include "DoubleBuffer.h"
#include <cudawrappers/nvrtc.hpp>
#include <cudawrappers/cu.hpp>

class TccDoubleBuffer final : public DoubleBuffer
{
public:
  TccDoubleBuffer(uint16_t nof_antennas, uint32_t nof_samples,
                  uint8_t nof_pols, uint8_t nbuffers = 4);

protected:
  void copy_data(uint32_t producer_index,
                 uint16_t start_antenna, uint16_t nof_included_antennas,
                 uint64_t start_sample_index, uint32_t samples,
                 uint16_t *data_ptr, double timestamp) override;

private:
  std::vector<std::unique_ptr<cu::HostMemory>> pinned_;
};
