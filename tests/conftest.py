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
from typing import Set, cast

import pytest
import tango
import yaml


def pytest_sessionstart(session: pytest.Session) -> None:
    """
    Pytest hook; prints info about tango version.

    :param session: a pytest Session object
    """
    print(tango.utils.info())


with open("tests/testbeds.yaml", "r", encoding="utf-8") as stream:
    _testbeds: dict[str, set[str]] = yaml.safe_load(stream)


# TODO: https://github.com/pytest-dev/pytest-forked/issues/67
# We're stuck on pytest 6.2 until this gets fixed, and this version of
# pytest is not fully typehinted
def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    """
    Register custom markers to avoid pytest warnings.

    :param config: the pytest config object
    """
    all_tags: Set[str] = cast(Set[str], set()).union(*_testbeds.values())
    for tag in all_tags:
        config.addinivalue_line("markers", f"needs_{tag}")


# TODO: https://github.com/pytest-dev/pytest-forked/issues/67
# We're stuck on pytest 6.2 until this gets fixed, and this version of
# pytest is not fully typehinted
def pytest_addoption(parser) -> None:  # type: ignore[no-untyped-def]
    """
    Implement the add the `--testbed` option.

    Used to specify the context in which the test is running.
    This could be used, for example, to skip tests that
    have requirements not met by the context.

    :param parser: the command line options parser
    """
    parser.addoption(
        "--testbed",
        choices=_testbeds.keys(),
        default="test",
        help="Specify the testbed on which the tests are running.",
    )


# TODO: https://github.com/pytest-dev/pytest-forked/issues/67
# We're stuck on pytest 6.2 until this gets fixed, and this version of
# pytest is not fully typehinted
def pytest_collection_modifyitems(  # type: ignore[no-untyped-def]
    config,
    items: list[pytest.Item],
) -> None:
    """
    Modify the list of tests to be run, after pytest has collected them.

    This hook implementation skips tests that are marked as needing some
    tag that is not provided by the current test context, as specified
    by the "--testbed" option.

    For example, if we have a hardware test that requires the presence
    of a real TPM, we can tag it with "@needs_tpm". When we run in a
    "test" context (that is, with "--testbed test" option), the test
    will be skipped because the "test" context does not provide a TPM.
    But when we run in "pss" context, the test will be run because the
    "pss" context provides a TPM.

    :param config: the pytest config object
    :param items: list of tests collected by pytest
    """
    testbed = config.getoption("--testbed")
    available_tags = _testbeds.get(testbed, set())

    prefix = "needs_"
    for item in items:
        needs_tags = set(
            tag[len(prefix) :] for tag in item.keywords if tag.startswith(prefix)
        )
        unmet_tags = list(needs_tags - available_tags)
        if unmet_tags:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        f"Testbed '{testbed}' does not meet test needs: "
                        f"{unmet_tags}."
                    )
                )
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
