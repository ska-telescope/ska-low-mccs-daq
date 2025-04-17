#ifndef _DEFINITIONS_H
#define _DEFINITIONS_H

#include <arpa/inet.h>
#include <cstdlib>
#include <unistd.h>
#include <cstdio>
#include <cstdio>

#include "JSON.hpp"

using json = nlohmann::json;;

#ifndef likely
    #define likely(x)		__builtin_expect(!!(x), 1)
#endif

#ifndef unlikely
    #define unlikely(x)		__builtin_expect(!!(x), 0)
#endif

// ------------------------- ALIGNMENT HELPERS -------------------

// Get page size
#define PAGE_ALIGNMENT sysconf(_SC_PAGESIZE)

// Get cache line size
#ifdef _SC_LEVEL1_DCACHE_LINESIZE
    #define CACHE_ALIGNMENT sysconf(_SC_LEVEL1_DCACHE_LINESIZE)
#else
    #define CACHE_ALIGNMENT 64;
#endif

// Define byte alignment for aligned copies
#define BYTE_ALIGNMENT  sizeof(uint32_t)

// Check whether a pointer is aligned to BYTE_COUNT
#define is_aligned(POINTER, BYTE_COUNT) \
    (((uintptr_t)(const void *)(POINTER)) % (BYTE_COUNT) == 0)

inline uint64_t ntohll(uint64_t host_longlong)
{
    int x = 1;

    /* little endian */
    if(*(char *)&x == 1)
        return ((((uint64_t) ntohl(host_longlong)) << 32) + ntohl(host_longlong >> 32));

        /* big endian */
    else
        return host_longlong;
}

// Try to allocate aligned memory, and default to normal malloc if that fails
inline bool allocate_aligned(void **ptr, long alignment, size_t size)
{
    // Try allocating memory with posix_memalign
    if (posix_memalign(ptr, alignment, size) > 0)
    {
        if ((*ptr = malloc(size)) == nullptr)
            return false;
    }
    return true;
}

// --------------------------- NUMA ------------------------------

// TEMPORARY
#define NUMA_NODE  0

// ---------------------------- OTHER -----------------------------

// Structure representing complex 8-bit values
struct complex_8t
{
    signed char x;
    signed char y;
};

// Helper function to check whether a key is present in a JSON document
inline bool key_in_json(json document, std::string key)
{
    json::iterator it;
    it = document.find(key);
    return !(it == document.end() != false);
}

#endif // _DEFINITIONS_H