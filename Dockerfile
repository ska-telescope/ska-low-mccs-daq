FROM artefact.skao.int/ska-tango-images-pytango-builder:9.3.32 AS buildenv
FROM artefact.skao.int/ska-tango-images-pytango-runtime:9.3.19 AS runtime

# create ipython profile to so that itango doesn't fail if ipython hasn't run yet
#RUN ipython profile create
USER root

RUN apt-get update && apt-get install ca-certificates -y
RUN python3 -m pip install poetry
RUN poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock* ./
COPY ./pyfabil-1.0-py3-none-any.whl ./aavs_system-1.0-py3-none-any.whl ./

RUN apt-get -y install build-essential make cmake libcap2-bin git

# Install AAVS DAQ
RUN git clone https://gitlab.com/ska-telescope/aavs-system.git /app/aavs-system/
# Copy a version of deploy.sh that does not setcap. (Causes [bad interpreter: operation not permitted] error)
COPY ./deploy.sh /app/aavs-system/
WORKDIR /app/aavs-system/

RUN DEBIAN_FRONTEND=noninteractive TZ="United_Kingdom/London" apt-get -y install tzdata
RUN ["/bin/bash", "-c", "source /app/aavs-system/deploy.sh"]

# Expose the DAQ port to UDP traffic.
EXPOSE 4660/udp

WORKDIR /app/

RUN poetry install --only main
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10
USER tango
