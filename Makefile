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
PYTHON_VARS_AFTER_PYTEST = --forked -n 16

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
K8S_HELMFILE = helmfile.d/helmfile.yaml.gotmpl

ifdef CI_COMMIT_SHORT_SHA
K8S_HELMFILE_ENV ?= stfc-ci
else
K8S_HELMFILE_ENV ?= minikube
endif


include .make/k8s.mk

# THIS IS SPECIFIC TO THIS REPO
ifdef CI_REGISTRY_IMAGE
K8S_CHART_PARAMS = \
	--selector chart=ska-low-mccs-daq \
	--selector chart=ska-tango-base \
	--set image.registry=$(CI_REGISTRY_IMAGE) \
	--set image.tag=$(VERSION)-dev.c$(CI_COMMIT_SHORT_SHA) \
	--set ska-tango-devices.deviceServerTypes.daq.image.registry=$(CI_REGISTRY_IMAGE) \
	--set ska-tango-devices.deviceServerTypes.daq.image.tag=$(VERSION)-dev.c$(CI_COMMIT_SHORT_SHA) \
	--set global.exposeAllDS=false \
	--set global.minikube=false
endif

JUNITXML_REPORT_PATH ?= build/reports/functional-tests.xml
CUCUMBER_JSON_PATH ?= build/reports/cucumber.json
JSON_REPORT_PATH ?= build/reports/report.json

K8S_TEST_RUNNER_PYTEST_OPTIONS = -v --true-context \
    --junitxml=$(JUNITXML_REPORT_PATH) \
    --cucumberjson=$(CUCUMBER_JSON_PATH) \
	--json-report --json-report-file=$(JSON_REPORT_PATH)

K8S_TEST_RUNNER_PYTEST_TARGET = tests/functional
K8S_TEST_RUNNER_PIP_INSTALL_ARGS = -r tests/functional/requirements.txt

# ALL THIS SHOULD BE UPSTREAMED
K8S_TEST_RUNNER_CHART_REGISTRY ?= https://artefact.skao.int/repository/helm-internal
K8S_TEST_RUNNER_CHART_NAME ?= ska-low-mccs-k8s-test-runner
K8S_TEST_RUNNER_CHART_TAG ?= 0.9.0

K8S_TEST_RUNNER_CHART_OVERRIDES = --set global.tango_host=databaseds-tango-base:10000  # TODO: This should be the default in the k8s-test-runner
ifdef K8S_TEST_RUNNER_IMAGE_REGISTRY
K8S_TEST_RUNNER_CHART_OVERRIDES += --set image.registry=$(K8S_TEST_RUNNER_IMAGE_REGISTRY)
endif

ifdef K8S_TEST_RUNNER_IMAGE_NAME
K8S_TEST_RUNNER_CHART_OVERRIDES += --set image.image=$(K8S_TEST_RUNNER_IMAGE_NAME)
endif

ifdef K8S_TEST_RUNNER_IMAGE_TAG
K8S_TEST_RUNNER_CHART_OVERRIDES += --set image.tag=$(K8S_TEST_RUNNER_IMAGE_TAG)
endif

ifdef CI_COMMIT_SHORT_SHA
K8S_TEST_RUNNER_CHART_RELEASE = k8s-test-runner-$(CI_COMMIT_SHORT_SHA)
else
K8S_TEST_RUNNER_CHART_RELEASE = k8s-test-runner
endif

K8S_TEST_RUNNER_PIP_INSTALL_COMMAND =
ifdef K8S_TEST_RUNNER_PIP_INSTALL_ARGS
K8S_TEST_RUNNER_PIP_INSTALL_COMMAND = pip install ${K8S_TEST_RUNNER_PIP_INSTALL_ARGS}
endif

K8S_TEST_RUNNER_WORKING_DIRECTORY ?= /home/tango

k8s-do-test:
	helm -n $(KUBE_NAMESPACE) install --repo $(K8S_TEST_RUNNER_CHART_REGISTRY) \
		$(K8S_TEST_RUNNER_CHART_RELEASE) $(K8S_TEST_RUNNER_CHART_NAME) \
		--version $(K8S_TEST_RUNNER_CHART_TAG) $(K8S_TEST_RUNNER_CHART_OVERRIDES)
	kubectl -n $(KUBE_NAMESPACE) wait pod ska-low-mccs-k8s-test-runner \
		--for=condition=ready --timeout=$(K8S_TIMEOUT)
	kubectl -n $(KUBE_NAMESPACE) cp tests/ ska-low-mccs-k8s-test-runner:$(K8S_TEST_RUNNER_WORKING_DIRECTORY)/tests
	@kubectl -n $(KUBE_NAMESPACE) exec ska-low-mccs-k8s-test-runner -- bash -c \
		"cd $(K8S_TEST_RUNNER_WORKING_DIRECTORY) && \
		mkdir -p build/reports && \
		$(K8S_TEST_RUNNER_PIP_INSTALL_COMMAND) && \
		pytest $(K8S_TEST_RUNNER_PYTEST_OPTIONS) $(K8S_TEST_RUNNER_PYTEST_TARGET)" ; \
    EXIT_CODE=$$? ; \
	kubectl -n $(KUBE_NAMESPACE) cp ska-low-mccs-k8s-test-runner:$(K8S_TEST_RUNNER_WORKING_DIRECTORY)/build/ ./build/ ; \
	helm  -n $(KUBE_NAMESPACE) uninstall $(K8S_TEST_RUNNER_CHART_RELEASE) ; \
	echo $$EXIT_CODE > build/status
	exit $$EXIT_CODE

telmodel-deps:
	pip install --extra-index-url https://artefact.skao.int/repository/pypi-internal/simple ska-telmodel check-jsonschema

k8s-pre-install-chart: telmodel-deps
k8s-pre-uninstall-chart: telmodel-deps


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
