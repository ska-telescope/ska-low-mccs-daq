#
# Project makefile for a SKA low MCCS DAQ project. 
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.

PROJECT = ska-low-mccs-daq

HELM_CHARTS_TO_PUBLISH = ska-low-mccs-daq

PYTHON_SWITCHES_FOR_ISORT = --skip-glob=*/__init__.py
PYTHON_SWITCHES_FOR_BLACK = --line-length 88
PYTHON_TEST_FILE = testing/src/tests
PYTHON_VARS_AFTER_PYTEST = --forked

## Paths containing python to be formatted and linted
PYTHON_LINT_TARGET = src/ska_low_mccs_daq testing/src/tests/

DOCS_SOURCEDIR=./docs/src
DOCS_SPHINXOPTS= -n -W --keep-going

# include makefile to pick up the standard Make targets, e.g., 'make build'
include .make/oci.mk
include .make/k8s.mk
include .make/python.mk
include .make/raw.mk
include .make/base.mk
include .make/docs.mk
include .make/helm.mk

# include your own private variables for custom deployment configuration
-include PrivateRules.mak

# Add this for typehints & static type checking
python-post-format:
	$(PYTHON_RUNNER) docformatter -r -i --wrap-summaries 88 --wrap-descriptions 72 --pre-summary-newline $(PYTHON_LINT_TARGET)

python-post-lint:
	$(PYTHON_RUNNER) mypy --config-file mypy.ini src/ testing/src/

docs-pre-build:
	python3 -m pip install -r docs/requirements.txt

.PHONY: python-post-format python-post-lint docs-pre-build
