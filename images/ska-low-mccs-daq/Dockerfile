FROM artefact.skao.int/ska-tango-images-pytango-builder:9.3.32 AS buildenv
FROM artefact.skao.int/ska-tango-images-pytango-runtime:9.3.19 AS runtime

USER root

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive TZ="United_Kingdom/London" apt-get install -y \
    build-essential ca-certificates cmake libcap2-bin git make tzdata

# Install AAVS DAQ
RUN git clone https://gitlab.com/ska-telescope/aavs-system.git /app/aavs-system/
# Copy a version of deploy.sh that does not setcap. (Causes [bad interpreter: operation not permitted] error)
RUN ls /app/
RUN cp /app/deploy.sh /app/aavs-system/

WORKDIR /app/aavs-system/
RUN ["/bin/bash", "-c", "source /app/aavs-system/deploy.sh"]

# Expose the DAQ port to UDP traffic.
EXPOSE 4660/udp

WORKDIR /app/

RUN poetry config virtualenvs.create false && poetry install --only main
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10
USER tango
