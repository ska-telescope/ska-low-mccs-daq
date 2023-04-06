# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""Module to test cuda install."""
from numba import cuda


@cuda.jit
def hello_cuda() -> None:
    """Test CUDA."""
    print("Hello CUDA!")


def main() -> None:
    """Test CUDA also."""
    hello_cuda[1, 1]()
    cuda.synchronize()


if __name__ == "__main__":
    main()
