# -*- coding: utf-8 -*-
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
import unittest

import _pytest
import pytest
import tango


def pytest_sessionstart(session: pytest.Session) -> None:
    """
    Pytest hook; prints info about tango version.

    :param session: a pytest Session object
    """
    print(tango.utils.info())


# TODO: https://github.com/pytest-dev/pytest-forked/issues/67
# We're stuck on pytest 6.2 until this gets fixed,
# and this version of pytest is not fully typehinted,
# so we have to typehint against a private class for now.
def pytest_addoption(
    parser: _pytest.config.argparsing.Parser,  # type: ignore[name-defined]
) -> None:
    """
    Add a command line option to pytest.

    This is a pytest hook, here implemented to add the `--true-context`
    option, used to indicate that a true Tango subsystem is available,
    so there is no need for the test harness to spin up a Tango test
    context.

    :param parser: the command line options parser
    """
    parser.addoption(
        "--true-context",
        action="store_true",
        default=False,
        help=(
            "Tell pytest that you have a true Tango context and don't "
            "need to spin up a Tango test context"
        ),
    )

    # This is a pytest hook, here implemented to add the `--true-context`
    # option, used to indicate that a true Tango subsystem is available,
    # so there is no need for the test harness to spin up a Tango test
    # context.

    parser.addoption(
        "--true-context",
        action="store_true",
        default=False,
        help=(
            "Tell pytest that you have a true Tango context and don't "
            "need to spin up a Tango test context"
        ),
    )


@pytest.fixture(name="initial_mocks")
def initial_mocks_fixture() -> dict[str, unittest.mock.Mock]:
    """
    Fixture that registers device proxy mocks prior to patching.

    By default no initial mocks are registered, but this fixture can be
    overridden by test modules/classes that need to register initial
    mocks.

    :return: an empty dictionary
    """
    return {}


@pytest.fixture(scope="session", name="logger")
def logger_fixture() -> logging.Logger:
    """
    Fixture that returns a default logger.

    :return: a logger
    """
    return logging.getLogger()
