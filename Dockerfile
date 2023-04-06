FROM artefact.skao.int/ska-tango-images-pytango-builder:9.3.35 AS buildenv
FROM artefact.skao.int/ska-tango-images-pytango-runtime:9.3.22 AS runtime

USER root

# Commit SHAs to use.
# When updating AAVS_SYSTEM_SHA, also update aavs_system in pyproject.toml
ENV AAVS_SYSTEM_SHA=498662646fcbb50c4995a1246f207852e2430006
ENV AAVS_DAQ_SHA=65c8339543ff94818ccc9335583168c9b7f877f4
ENV PYFABIL_SHA=1aa0dc954fb701fd2a7fed03df21639fc4c50560

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive TZ="United_Kingdom/London" apt-get install -y \
    build-essential ca-certificates cmake libcap2-bin git make tzdata nvidia-cuda-toolkit nvidia-utils-525

# Install AAVS DAQ
RUN git clone https://gitlab.com/ska-telescope/aavs-system.git /app/aavs-system/
WORKDIR /app/aavs-system
RUN git reset --hard ${AAVS_SYSTEM_SHA}
# Copy a version of deploy.sh that does not setcap. (Causes [bad interpreter: operation not permitted] error)
RUN cp /app/deploy.sh /app/aavs-system/
RUN ["/bin/bash", "-cC", "source /app/aavs-system/deploy.sh"]
# Expose the DAQ port to UDP traffic.
EXPOSE 4660/udp
WORKDIR /app/

RUN poetry config virtualenvs.create false && poetry install --only main
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10
USER tango
