#pragma once
#include <cstdlib>
#include <cstring>

// Test stub - replaces pinned GPU memory with plain heap allocation so that
// TccSplitRing unit tests run without a CUDA device.

#define CU_MEMHOSTALLOC_WRITECOMBINED 0x04u

namespace cu {

inline void init() {}

class HostMemory {
    void  *ptr_;
public:
    HostMemory(size_t bytes, unsigned /*flags*/) {
        const size_t aligned = (bytes + 63u) & ~63ull;
        ptr_ = std::aligned_alloc(64, aligned);
        std::memset(ptr_, 0, aligned);
    }
    ~HostMemory() { std::free(ptr_); }
    HostMemory(const HostMemory &) = delete;
    HostMemory &operator=(const HostMemory &) = delete;
    operator void *() const { return ptr_; }
};

} // namespace cu
