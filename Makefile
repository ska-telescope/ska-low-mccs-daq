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
DOCS_SPHINXOPTS= -W --keep-going

docs-pre-build:
	poetry config virtualenvs.create false
	poetry install --no-root --only docs

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
# K8S
###############################################
K8S_USE_HELMFILE = true
K8S_HELMFILE = helmfile.d/helmfile.yaml
K8S_HELMFILE_ENV ?= default

include .make/k8s.mk

###############################################
# HELM
###############################################

include .make/helm.mk

HELM_CHARTS_TO_PUBLISH = ska-low-mccs-daq


###############################################
# PRIVATE
###############################################

-include PrivateRules.mak
