#
# Project makefile for a SKA low MCCS DAQ project.
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.

PROJECT = ska-low-mccs-daq
#KUBE_NAMESPACE=ska-low-mccs-spshw
KUBE_NAMESPACE=dp-mccs-adam-p
HELM_RELEASE=test2
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

########################################################################
# K8S
########################################################################
include .make/k8s.mk
include .make/raw.mk
include .make/xray.mk

_remote_tracking_branch = $(shell git status -sb | head -1 | sed 's/\.\.\./\n/' | tail -1)
_gitlab_tag = $(VERSION)-dev.c$(shell git rev-parse --short=8 $(_remote_tracking_branch))

K8S_CHART_PARAMS = \
  --set global.minikube=false \
  --set $(PROJECT).image.registry=registry.gitlab.com/ska-telescope/mccs/ska-low-mccs-daq \
  --set $(PROJECT).image.tag=$(_gitlab_tag)


# K8S_FACILITY ?= k8s-test
# K8S_CHART_PARAMS += --values chart-values/values-$(K8S_FACILITY).yaml

# ifdef CI_REGISTRY_IMAGE
# K8S_CHART_PARAMS += \
# 	--set image.registry=$(CI_REGISTRY_IMAGE) \
# 	--set image.tag=$(VERSION)-dev.c$(CI_COMMIT_SHORT_SHA)
# endif


# JUNITXML_REPORT_PATH ?= build/reports/functional-tests.xml
# CUCUMBER_JSON_PATH ?= build/reports/cucumber.json
# JSON_REPORT_PATH ?= build/reports/report.json

# K8S_TEST_RUNNER_PYTEST_OPTIONS = -v --true-context \
# 	--junitxml=$(JUNITXML_REPORT_PATH) \
# 	--cucumberjson=$(CUCUMBER_JSON_PATH) \
# 	--json-report --json-report-file=$(JSON_REPORT_PATH)

# K8S_TEST_RUNNER_PYTEST_TARGET = tests/functional
# K8S_TEST_RUNNER_PIP_INSTALL_ARGS = -r tests/functional/requirements.txt

# K8S_TEST_RUNNER_CHART_REGISTRY ?= https://artefact.skao.int/repository/helm-internal
# K8S_TEST_RUNNER_CHART_NAME ?= ska-low-mccs-k8s-test-runner
# K8S_TEST_RUNNER_CHART_TAG ?= 0.8.0


# K8S_TEST_RUNNER_CHART_OVERRIDES =

# ifdef PASS_PROXY_CONFIG
# FACILITY_HTTP_PROXY ?= $(http_proxy)
# FACILITY_HTTPS_PROXY ?= $(https_proxy)
# endif

# ifdef FACILITY_HTTP_PROXY
# K8S_TEST_RUNNER_CHART_OVERRIDES += --set global.http_proxy=$(FACILITY_HTTP_PROXY)
# endif

# ifdef FACILITY_HTTPS_PROXY
# K8S_TEST_RUNNER_CHART_OVERRIDES += --set global.https_proxy=$(FACILITY_HTTPS_PROXY)
# endif

# ifdef K8S_TEST_RUNNER_IMAGE_REGISTRY
# K8S_TEST_RUNNER_CHART_OVERRIDES += --set image.registry=$(K8S_TEST_RUNNER_IMAGE_REGISTRY)
# endif

# ifdef K8S_TEST_RUNNER_IMAGE_NAME
# K8S_TEST_RUNNER_CHART_OVERRIDES += --set image.image=$(K8S_TEST_RUNNER_IMAGE_NAME)
# endif

# ifdef K8S_TEST_RUNNER_IMAGE_TAG
# K8S_TEST_RUNNER_CHART_OVERRIDES += --set image.tag=$(K8S_TEST_RUNNER_IMAGE_TAG)
# endif

# ifdef CI_COMMIT_SHORT_SHA
# K8S_TEST_RUNNER_CHART_RELEASE = k8s-test-runner-$(CI_COMMIT_SHORT_SHA)
# else
# K8S_TEST_RUNNER_CHART_RELEASE = k8s-test-runner
# endif

# K8S_TEST_RUNNER_PIP_INSTALL_COMMAND =
# ifdef K8S_TEST_RUNNER_PIP_INSTALL_ARGS
# K8S_TEST_RUNNER_PIP_INSTALL_COMMAND = pip install ${K8S_TEST_RUNNER_PIP_INSTALL_ARGS}
# endif

# K8S_TEST_RUNNER_WORKING_DIRECTORY ?= /home/tango

# k8s-do-test:
# 	helm -n $(KUBE_NAMESPACE) upgrade --install --repo $(K8S_TEST_RUNNER_CHART_REGISTRY) \
# 		$(K8S_TEST_RUNNER_CHART_RELEASE) $(K8S_TEST_RUNNER_CHART_NAME) \
# 		--version $(K8S_TEST_RUNNER_CHART_TAG) $(K8S_TEST_RUNNER_CHART_OVERRIDES) 
# 	kubectl -n $(KUBE_NAMESPACE) wait pod ska-low-mccs-k8s-test-runner \
# 		--for=condition=ready --timeout=$(K8S_TIMEOUT)
# 	kubectl -n $(KUBE_NAMESPACE) cp tests/ ska-low-mccs-k8s-test-runner:$(K8S_TEST_RUNNER_WORKING_DIRECTORY)/tests
# 	@kubectl -n $(KUBE_NAMESPACE) exec ska-low-mccs-k8s-test-runner -- bash -c \
# 		"cd $(K8S_TEST_RUNNER_WORKING_DIRECTORY) && \
# 		mkdir -p build/reports && \
# 		$(K8S_TEST_RUNNER_PIP_INSTALL_COMMAND) && \
# 		pytest $(K8S_TEST_RUNNER_PYTEST_OPTIONS) $(K8S_TEST_RUNNER_PYTEST_TARGET)" ; \
# 	EXIT_CODE=$$? ; \
# 	kubectl -n $(KUBE_NAMESPACE) cp ska-low-mccs-k8s-test-runner:$(K8S_TEST_RUNNER_WORKING_DIRECTORY)/build/ ./build/ ; \
# 	helm  -n $(KUBE_NAMESPACE) uninstall $(K8S_TEST_RUNNER_CHART_RELEASE) ; \
# 	exit $$EXIT_CODE

# .PHONY: k8s-do-test

###############################################
# PRIVATE
###############################################

-include PrivateRules.mak
include .make/k8s.mk