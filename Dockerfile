FROM nvidia/cuda:11.4.3-devel-ubuntu20.04 AS cuda_base

RUN useradd --create-home --home-dir /home/daqqer daqqer && mkdir /etc/sudoers.d/
RUN echo "daqqer ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/daqqer && \
    chmod 0440 /etc/sudoers.d/daqqer

COPY --chown=daqqer:daqqer ./ /app/

# Setup environment variables
# When updating AAVS_SYSTEM_SHA, also update aavs_system in pyproject.toml
ENV AAVS_SYSTEM_SHA=74c03585a3ba7bdbfd259f044b0d8a7f77951c96
ENV AAVS_DAQ_SHA=65c8339543ff94818ccc9335583168c9b7f877f4
ENV PYFABIL_SHA=c5e10ffde94b656e5d4439803916d50972052e42
ENV DEBIAN_FRONTEND=noninteractive
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES compute,utility
ENV TZ="United_Kingdom/London"
ENV CUDA_ARCH="sm_80"

# Add required packages and python repo.
RUN rm /etc/apt/sources.list.d/cuda.list && apt-get update && apt-get install -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa
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
    python3.10 \
    python3-distutils \
    sudo \
    tzdata

# Set Python3.10 to preferred version, add folders to PATH, create symlink to python3
RUN update-alternatives --install /usr/bin/python3 python /usr/bin/python3.10 2
RUN export PATH="/usr/local/lib:/usr/local/bin:/usr/local/cuda:/usr/local/cuda/bin:/usr/bin/python:/usr/bin/python3:/usr/bin/python3.10:${PATH}"
RUN ["/usr/bin/ln", "-s", "/usr/bin/python3.10", "/usr/bin/python"]

# Install pip and poetry.
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VERSION=1.3.2
RUN curl -sSL https://bootstrap.pypa.io/get-pip.py | gosu root python3
RUN curl -sSL --retry 3 --connect-timeout 15 https://install.python-poetry.org | gosu root python3 - --yes
RUN ln -sfn /usr/bin/python3 /usr/bin/python && \
    ln -sfn /opt/poetry/bin/poetry /usr/local/bin/poetry

# Fix distro-info being non pep compliant (due to the NVIDIA base image configuration)
RUN apt -y autoremove python3-debian python3-distro-info

# Clone and install xGPU
WORKDIR /app/
RUN git clone https://github.com/GPU-correlators/xGPU.git /app/xGPU/
WORKDIR /app/xGPU/src/
RUN make NFREQUENCY=1 NTIME=1835008 NTIME_PIPE=16384 install

# Install AAVS DAQ
RUN git clone https://gitlab.com/ska-telescope/aavs-system.git /app/aavs-system/
WORKDIR /app/aavs-system
RUN git reset --hard ${AAVS_SYSTEM_SHA}

# Copy a version of deploy.sh that does not setcap. (Causes [bad interpreter: operation not permitted] error)
COPY deploy.sh /app/aavs-system/
# Copy CMakeLists.txt with corrected library name.
COPY CMakeLists.txt /app/aavs-system/src/
RUN ["/bin/bash", "-c", "source /app/aavs-system/deploy.sh"]

# Expose the DAQ port to UDP traffic.
EXPOSE 4660/udp

WORKDIR /app/
COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.create false && poetry install --only main
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10
RUN chmod a+w /app/
RUN chmod -x /usr/local/lib/libxgpu.so
ENV PATH="/usr/local/lib/:${PATH}"
USER daqqer
