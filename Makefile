#
# Project makefile for a SKA low MCCS DAQ project. 
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.

PROJECT = ska-low-mccs-daq

HELM_CHARTS_TO_PUBLISH = ska-low-mccs-daq ska-tango-util

PYTHON_SWITCHES_FOR_ISORT = --skip-glob=*/__init__.py
PYTHON_SWITCHES_FOR_BLACK = --line-length 88
PYTHON_TEST_FILE = tests
PYTHON_VARS_AFTER_PYTEST = --forked

## Paths containing python to be formatted and linted
PYTHON_LINT_TARGET = src/ska_low_mccs_daq tests/

DOCS_SOURCEDIR=./docs/src
DOCS_SPHINXOPTS= -n -W --keep-going

# Can't use . here because ociImageBuild overrides it.
OCI_IMAGE_BUILD_CONTEXT?=$(shell pwd)

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

K8S_TEST_RUNNER_ADD_ARGS = --overrides='{"securityContext": {"capabilities": {"add": ["NET_RAW", "IPC_LOCK", "SYS_NICE", "SYS_ADMIN", "KILL", "SYS_TIME"]}}}'

ifneq ($(strip $(CI_JOB_ID)),)
  K8S_TEST_IMAGE_TO_TEST = $(CI_REGISTRY_IMAGE)/$(NAME):$(VERSION)-dev.c$(CI_COMMIT_SHORT_SHA)
endif

ifeq ($(MAKECMDGOALS),k8s-test)
PYTHON_VARS_AFTER_PYTEST += --testbed local
PYTHON_TEST_FILE = tests/functional
endif

# Add this for typehints & static type checking
python-post-format:
	$(PYTHON_RUNNER) docformatter -r -i --wrap-summaries 88 --wrap-descriptions 72 --pre-summary-newline $(PYTHON_LINT_TARGET)

python-post-lint:
	$(PYTHON_RUNNER) mypy --config-file mypy.ini src/ tests/

docs-pre-build:
	python3 -m pip install -r docs/requirements.txt


KUBE_NAMESPACE ?= ska-low-mccs-daq

k8s-do-test:
	kubectl -n $(KUBE_NAMESPACE) apply -f k8s-test-runner.yaml
	kubectl -n $(KUBE_NAMESPACE) wait --for=condition=ready pods k8s-test-runner
	kubectl -n $(KUBE_NAMESPACE) cp tests/ k8s-test-runner:/app
	kubectl -n $(KUBE_NAMESPACE) exec k8s-test-runner -- pytest
	kubectl -n $(KUBE_NAMESPACE) cp k8s-test-runner:build/ ./build/
	kubectl -n $(KUBE_NAMESPACE) delete pod k8s-test-runner

.PHONY: k8s-test python-post-format python-post-lint docs-pre-build
