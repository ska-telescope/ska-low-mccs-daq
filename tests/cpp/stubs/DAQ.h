#pragma once
#include <cstdio>

// Test stub for the DAQ library LOG macro used by TccDoubleBuffer.cpp.

#define INFO  0
#define WARN  1
#define ERROR 2

// NOLINTNEXTLINE(cppcoreguidelines-macro-usage)
#define LOG(level, fmt, ...) \
    std::fprintf(stderr, "[%s] " fmt "\n", \
        (level) == ERROR ? "ERROR" : (level) == WARN ? "WARN" : "INFO", \
        ##__VA_ARGS__)
