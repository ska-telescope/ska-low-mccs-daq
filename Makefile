#
# Project makefile for a SKA low MCCS DAQ project.
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.

PROJECT = ska-low-mccs-daq

include .make/base.mk

###############################################
# DOCS
###############################################
include .make/docs.mk

DOCS_SOURCEDIR=./docs/src
DOCS_SPHINXOPTS= -n -W --keep-going

docs-pre-build:
	python3 -m pip install -r docs/requirements.txt

.PHONY: docs-pre-build


###############################################
# PYTHON
###############################################

include .make/python.mk

PYTHON_LINE_LENGTH = 88
PYTHON_TEST_FILE = tests
PYTHON_VARS_AFTER_PYTEST = --forked

python-post-lint:
	mypy --config-file mypy.ini src/ tests

.PHONY: python-post-lint


###############################################
# OCI
###############################################

include .make/oci.mk


###############################################
# HELM
###############################################

include .make/helm.mk

HELM_CHARTS_TO_PUBLISH = ska-low-mccs-daq


###############################################
# PRIVATE
###############################################

-include PrivateRules.mak
