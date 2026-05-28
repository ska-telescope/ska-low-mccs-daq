//
// Created by Tom Moynihan on 22/08/2025.
//
#pragma once
#include "DoubleBuffer.h"
#include <cudawrappers/nvrtc.hpp>
#include <cudawrappers/cu.hpp>
#include <atomic>
#include <memory>

class TccDoubleBuffer final : public DoubleBuffer
{
public:
  TccDoubleBuffer(uint16_t nof_antennas, uint32_t nof_samples,
                  uint8_t nof_pols, uint8_t nbuffers = 4);

  // Returns the highest M-block index such that every antenna has written
  // all M-blocks [0, safe_m) into buf_idx. Safe to H2D-copy up to this point.
  uint32_t safe_m(int buf_idx) const;

  // Resets watermarks for the newly-exposed consumer slot so safe_m() cannot
  // return stale values from the previous fill of this ring-buffer slot.
  void release_buffer() override;

protected:
  void copy_data(uint32_t producer_index,
                 uint16_t start_antenna, uint16_t nof_included_antennas,
                 uint64_t start_sample_index, uint32_t samples,
                 uint16_t *data_ptr, double timestamp) override;

private:
  std::vector<std::unique_ptr<cu::HostMemory>> pinned_;
  uint8_t times_per_block = 16; // Fixed by TCC for complex 8 bit samples

  // antenna_hi_[buf * nof_antennas + r] = highest M-block (+1) written for
  // antenna r in buffer slot buf. Used to compute the H2D streaming watermark.
  std::unique_ptr<std::atomic<uint32_t>[]> antenna_hi_;
};
