FROM ubuntu:22.04

# Commit SHAs to use.
# When updating AAVS_SYSTEM_SHA, also update aavs_system in pyproject.toml
ENV AAVS_SYSTEM_SHA=498662646fcbb50c4995a1246f207852e2430006
ENV AAVS_DAQ_SHA=65c8339543ff94818ccc9335583168c9b7f877f4
ENV PYFABIL_SHA=1aa0dc954fb701fd2a7fed03df21639fc4c50560

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive TZ="United_Kingdom/London" apt-get install -y \
    build-essential ca-certificates cmake curl libcap2-bin git make python3 sudo tzdata

ENV POETRY_HOME=/opt/poetry
ENV POETRY_VERSION=1.3.2
RUN curl -sSL https://install.python-poetry.org | python3 - --yes

RUN ln -sfn /usr/bin/python3 /usr/bin/python && \
    ln -sfn /opt/poetry/bin/poetry /usr/local/bin/poetry

# Install AAVS DAQ
RUN git clone https://gitlab.com/ska-telescope/aavs-system.git /app/aavs-system/
WORKDIR /app/aavs-system
RUN git reset --hard ${AAVS_SYSTEM_SHA}
# Copy a version of deploy.sh that does not setcap. (Causes [bad interpreter: operation not permitted] error)

COPY deploy.sh /app/aavs-system/

RUN ["/bin/bash", "-c", "source /app/aavs-system/deploy.sh"]
# Expose the DAQ port to UDP traffic.
EXPOSE 4660/udp

RUN useradd --create-home --home-dir /home/daqqer daqqer
RUN echo "daqqer ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/daqqer && \
    chmod 0440 /etc/sudoers.d/daqqer

COPY --chown=daqqer:daqqer . /app
WORKDIR /app/

ENV PATH="/home/daqqer/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH}"
RUN /opt/poetry/bin/poetry config virtualenvs.create false && /opt/poetry/bin/poetry install --only main
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10
USER daqqer
