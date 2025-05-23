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

PYTHON_SWITCHES_FOR_BLACK = --exclude=src/ska_low_mccs_daq/pydaq
PYTHON_SWITCHES_FOR_ISORT = --skip-glob=src/ska_low_mccs_daq/pydaq
PYTHON_SWITCHES_FOR_PYLINT = --ignore-paths=src/ska_low_mccs_daq/pydaq
PYTHON_SWITCHES_FOR_FLAKE8 = --exclude=src/ska_low_mccs_daq/pydaq

python-post-lint:
	mypy --exclude src/ska_low_mccs_daq/pydaq/ --config-file mypy.ini src/ tests

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
K8S_HELMFILE_ENV ?= minikube

include .make/k8s.mk

###############################################
# HELM
###############################################

include .make/helm.mk

HELM_CHARTS_TO_PUBLISH = ska-low-mccs-daq


####################
# Helmfile
####################
helmfile-lint:
	SKIPDEPS=""
	for environment in minikube aa0.5-production aavs3-production aavs3-minikube arcetri gmrt low-itf low-itf-minikube oxford psi-low psi-low-minikube ral ral-minikube; do \
        echo "Linting helmfile against environment '$$environment'" ; \
		helmfile -e $$environment lint $$SKIPDEPS; \
		EXIT_CODE=$$? ; \
		if [ $$EXIT_CODE -gt 0 ]; then \
		echo "Linting of helmfile against environment '$$environment' FAILED." ; \
		break ; \
		fi ; \
		SKIPDEPS="--skip-deps" ; \
	done
	exit $$EXIT_CODE

.PHONY: helmfile-lint


###############################################
# PRIVATE
###############################################

-include PrivateRules.mak
