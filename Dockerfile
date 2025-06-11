# TODO: Adding this image "as tools"
# so that we can copy the shell scripts
# that ska-tango-util expects this image to have
# is highly unsatisfactory.
# I've taken this from ska-tango-examples
# but hopefully a better solution will be found.
FROM artefact.skao.int/ska-tango-images-tango-dsconfig:1.5.13 AS tools

# For now pulling from the gitlab registry
FROM registry.gitlab.com/ska-telescope/ska-base-images/ska-build-cuda-11:0.1.0-dev.caeef7591

# TODO: Unsatisfactory; see comment above
COPY --from=tools /usr/local/bin/retry /usr/local/bin/retry
COPY --from=tools /usr/local/bin/wait-for-it.sh /usr/local/bin/wait-for-it.sh

ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=1
ENV POETRY_VIRTUALENVS_CREATE=1
ENV VIRTUAL_ENV=/src/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV DEBIAN_FRONTEND=noninteractive
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES compute,utility
ENV TZ="United_Kingdom/London"
ENV CUDA_ARCH="sm_80"
ENV LC_ALL="en_US.UTF-8"
ENV AAVS_DAQ_SHA=7ca4f06a983861a8596a98abe3a3d34fa5f1a1b5

# Install necessary packages for compiling and installing DAQ and prerequisites.
RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    cmake \
    curl \
    git \
    gosu \
    libcap2-bin \
    make \
    pkg-config \
    sudo \
    tzdata

# Clone and install xGPU
WORKDIR /app/
RUN git clone https://github.com/GPU-correlators/xGPU.git /app/xGPU/
WORKDIR /app/xGPU/src/
RUN make NFREQUENCY=1 NTIME=1835008 NTIME_PIPE=16384 install

# Install AAVS DAQ
RUN mkdir /app/aavs-system/ && mkdir /app/aavs-system/pydaq && mkdir /app/aavs-system/cdaq
COPY /src/ska_low_mccs_daq/pydaq  /app/aavs-system/pydaq/
COPY /src/ska_low_mccs_daq/cdaq /app/aavs-system/cdaq/
COPY deploy.sh cdaq_requirements.pip /app/aavs-system/
WORKDIR /app/aavs-system
RUN ["/bin/bash", "-c", "source /app/aavs-system/deploy.sh"]

WORKDIR /src

# Expose the DAQ port to UDP traffic.
EXPOSE 4660/udp
COPY README.md pyproject.toml poetry.lock* ./
RUN poetry install --no-root

COPY src ./
RUN poetry install
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10
RUN chmod a+w /app/
RUN mkdir /product && chmod a+w /product/

WORKDIR /app/