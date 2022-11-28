#
# Project makefile for a SKA low MCCS DAQ project. 
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.

PROJECT = ska-low-mccs-daq

HELM_CHARTS_TO_PUBLISH = ska-low-mccs-daq

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


# THIS IS SPECIFIC TO THIS REPO
K8S_TEST_RUNNER_IMAGE = ska-low-mccs-daq-test-runner

ifndef CI_COMMIT_SHORT_SHA
K8S_TEST_RUNNER_TAG = 0.1.2
endif

# THIS SHOULD BE UPSTREAMED
K8S_TEST_RUNNER_HELM_CHART_REPO ?= https://artefact.skao.int/repository/helm-internal
K8S_TEST_RUNNER_HELM_CHART_NAME ?= ska-low-mccs-k8s-test-runner
K8S_TEST_RUNNER_HELM_CHART_TAG ?= 0.2.0

K8S_TEST_OVERRIDES =
ifdef K8S_TEST_RUNNER_REGISTRY
K8S_TEST_OVERRIDES += --set image.registry=$(K8S_TEST_RUNNER_REGISTRY)
else
ifdef CI_REGISTRY_IMAGE
K8S_TEST_OVERRIDES += --set image.registry=$(CI_REGISTRY_IMAGE)
endif
endif

ifdef K8S_TEST_RUNNER_IMAGE
K8S_TEST_OVERRIDES += --set image.image=$(K8S_TEST_RUNNER_IMAGE)
endif

ifdef K8S_TEST_RUNNER_TAG
K8S_TEST_OVERRIDES += --set image.tag=$(K8S_TEST_RUNNER_TAG)
else
ifdef CI_COMMIT_SHORT_SHA
K8S_TEST_OVERRIDES += --set image.tag=$(VERSION)-dev.c$(CI_COMMIT_SHORT_SHA)
endif
endif

ifdef CI_COMMIT_SHORT_SHA
TEST_RUNNER_RELEASE = k8s-test-runner-$(CI_COMMIT_SHORT_SHA)
else
TEST_RUNNER_RELEASE = k8s-test-runner
endif

k8s-do-test:
	helm -n $(KUBE_NAMESPACE) install --repo $(K8S_TEST_RUNNER_HELM_CHART_REPO) $(TEST_RUNNER_RELEASE) $(K8S_TEST_RUNNER_HELM_CHART_NAME) --version $(K8S_TEST_RUNNER_HELM_CHART_TAG) $(K8S_TEST_OVERRIDES) 
	kubectl -n $(KUBE_NAMESPACE) wait pod ska-low-mccs-k8s-test-runner --for=condition=ready --timeout=$(K8S_TIMEOUT)
	kubectl -n $(KUBE_NAMESPACE) cp tests/ ska-low-mccs-k8s-test-runner:/app
	kubectl -n $(KUBE_NAMESPACE) exec ska-low-mccs-k8s-test-runner -- pytest
	kubectl -n $(KUBE_NAMESPACE) cp ska-low-mccs-k8s-test-runner:build/ ./build/
	helm  -n $(KUBE_NAMESPACE) uninstall $(TEST_RUNNER_RELEASE)

.PHONY: k8s-test python-post-format python-post-lint docs-pre-build
