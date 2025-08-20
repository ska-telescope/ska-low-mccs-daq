// tests/tensor_ctor_test.cpp
#include <iostream>
#include <cudawrappers/cu.hpp>
#include "TensorCorrelatorData.h"

// No thread, no buffer use. We just construct and destroy the object.
int main()
{
    try
    {
        cu::init();                     // required before using cudawrappers
        const uint32_t nfine = 1;       // your code uses 1 channel per launch
        const uint16_t R = 256;         // receivers
        const uint32_t Ntime = 1835008; // must be divisible by 256
        const uint8_t P = 2;            // pols

        // You don't start the thread, so a nullptr DoubleBuffer is fine for this test.
        TensorCrossCorrelator tcc(/*double_buffer*/ nullptr, nfine, R, Ntime, P);
        std::cout << "TensorCrossCorrelator constructed OK.\n";
        return 0;
    }
    catch (const std::exception &e)
    {
        std::cerr << "Exception: " << e.what() << "\n";
        return 1;
    }
}
