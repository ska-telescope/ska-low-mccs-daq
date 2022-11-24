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

ifneq ($(strip $(CI_JOB_ID)),)
  K8S_TEST_IMAGE_TO_TEST = $(CI_REGISTRY_IMAGE)/$(NAME):$(VERSION)-dev.c$(CI_COMMIT_SHORT_SHA)
endif

python-post-format:
	$(PYTHON_RUNNER) docformatter -r -i --wrap-summaries 88 --wrap-descriptions 72 --pre-summary-newline $(PYTHON_LINT_TARGET)

python-post-lint:
	$(PYTHON_RUNNER) mypy --config-file mypy.ini src/ tests/

docs-pre-build:
	python3 -m pip install -r docs/requirements.txt


K8S_TEST_OVERRIDES =
ifdef KUBE_NAMESPACE
K8S_TEST_OVERRIDES += --set namespace=$(KUBE_NAMESPACE)
endif
ifdef K8S_TEST_RUNNER_IMAGE
K8S_TEST_OVERRIDES += --set image=$(K8S_TEST_RUNNER_IMAGE)
endif

ifdef CI_COMMIT_SHORT_SHA
TEST_RUNNER_RELEASE = k8s-test-runner-$(CI_COMMIT_SHORT_SHA)
else
TEST_RUNNER_RELEASE = k8s-test-runner
endif

k8s-do-test:
	helm install $(TEST_RUNNER_RELEASE) charts/k8s-test-runner $(K8S_TEST_OVERRIDES) 
	kubectl -n $(KUBE_NAMESPACE) wait --for=condition=ready pods k8s-test-runner
	kubectl -n $(KUBE_NAMESPACE) cp tests/ k8s-test-runner:/app
	kubectl -n $(KUBE_NAMESPACE) exec k8s-test-runner -- pytest
	kubectl -n $(KUBE_NAMESPACE) cp k8s-test-runner:build/ ./build/
	helm uninstall $(TEST_RUNNER_RELEASE)

.PHONY: k8s-test python-post-format python-post-lint docs-pre-build
