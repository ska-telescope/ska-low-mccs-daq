# -*- coding: utf-8 -*
#
# This file is part of the SKA Low MCCS project
#
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
"""
This module contains pytest fixtures other test setups.

These are common to all ska-low-mccs tests: unit, integration and
functional (BDD).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Generator

import pytest
import tango
from filelock import FileLock

from tests.harness import get_bandpass_daq_name, get_lmc_daq_name


def pytest_sessionstart(session: pytest.Session) -> None:
    """
    Pytest hook; prints info about tango version.

    :param session: a pytest Session object
    """
    print(tango.utils.info())


@pytest.fixture(scope="session", name="logger")
def logger_fixture() -> logging.Logger:
    """
    Fixture that returns a default logger.

    :return: a logger
    """
    debug_logger = logging.getLogger()
    debug_logger.setLevel(logging.DEBUG)
    return debug_logger


@pytest.fixture(name="daq_id", scope="session")
def daq_id_fixture() -> int:
    """
    Return the daq id of this daq receiver.

    :return: the daq id of this daq receiver.
    """
    return 1


@pytest.fixture(name="lmc_daq_trl")
def lmc_daq_trl_fixture() -> str:
    """
    Return a DAQ TRL for testing purposes.

    :returns: A DAQ TRL.
    """
    return get_lmc_daq_name()


@pytest.fixture(name="bandpass_daq_trl")
def bandpass_daq_trl_fixture() -> str:
    """
    Return a DAQ TRL for testing purposes.

    :returns: A DAQ TRL.
    """
    return get_bandpass_daq_name()


@pytest.fixture(name="global_test_lock")
def global_test_lock_fixture(tmp_path_factory: pytest.TempPathFactory) -> Generator:
    """
    Create a cross-process lock file.

    :param tmp_path_factory: Get a tmp path

    :yields: The test lock.

    """
    shared_tmp_dir = tmp_path_factory.getbasetemp().parent
    lock_file_path = shared_tmp_dir / "exclusive_tests.lock"
    with FileLock(str(lock_file_path)):
        yield


# The PCAP filename
PCAP_NAME = "channel_integ_96_192.pcap"

# In CI the PCAP is injected into the job pod from the BAR "runner-artefacts"
# repository, via the KUBERNETES_POD_ANNOTATIONS_* variables on the
# python-test job in .gitlab-ci.yml. The injector unpacks the artefact's
# assets into this directory.
INJECTED_PCAP_DIR = Path("/mnt/artefact")

# Local runs use a copy of the PCAP that the developer has fetched from BAR.
LOCAL_PCAP_DIR = Path("tests/data/pcap-data")


def _find_pcap_file() -> Path | None:
    """
    Find the PCAP file, preferring the copy injected by the runner.

    :returns: The path to the PCAP file, or None if it was not found.

    """
    for directory in (INJECTED_PCAP_DIR, LOCAL_PCAP_DIR):
        pcap_path = directory / PCAP_NAME
        if pcap_path.is_file():
            return pcap_path
    return None


@pytest.fixture(name="pcap_filename")
def pcap_filename_fixture() -> str:
    """
    Get the PCAP filename.

    :returns: The PCAP filename

    """
    pcap_path = _find_pcap_file()

    if pcap_path is None:
        searched = ", ".join(
            str(directory / PCAP_NAME)
            for directory in (INJECTED_PCAP_DIR, LOCAL_PCAP_DIR)
        )
        message = (
            f"PCAP test data not found. Searched: {searched}. "
            f"Download {PCAP_NAME} from the BAR runner-artefacts repository "
            "and place it in tests/data/pcap-data."
        )
        # Under CI the PCAP should have been injected into the pod, so a
        # missing file means injection is broken.
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)

    return str(pcap_path)
