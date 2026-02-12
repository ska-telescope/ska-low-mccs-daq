# TODO: Adding this image "as tools"
# so that we can copy the shell scripts
# that ska-tango-util expects this image to have
# is highly unsatisfactory.
# I've taken this from ska-tango-examples
# but hopefully a better solution will be found.
FROM artefact.skao.int/ska-tango-images-tango-dsconfig:1.5.13 AS tools

FROM artefact.skao.int/ska-build-cuda-11:0.1.3

# Create non-root user
RUN useradd --create-home --home-dir /home/daqqer daqqer && mkdir /etc/sudoers.d/
RUN echo "daqqer ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/daqqer && \
    chmod 0440 /etc/sudoers.d/daqqer

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
ENV TZ="United_Kingdom/London"
ENV NVIDIA_DRIVER_CAPABILITIES compute,utility
ENV CUDA_ARCH="sm_80"
ENV LC_ALL="en_US.UTF-8"
ENV AAVS_DAQ_SHA=68e5953acd7a778ea37278f38679e5ca30636e69
ENV DAQ_INSTALL="/opt/aavs"

ENV CMAKE_PREFIX_PATH="/opt/aavs:${CMAKE_PREFIX_PATH}"
ENV LD_LIBRARY_PATH="/opt/aavs:/usr/local/lib:${LD_LIBRARY_PATH}"

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

ENV POETRY_HOME=/opt/poetry
RUN curl -sSL --retry 3 --connect-timeout 15 https://install.python-poetry.org | \
    gosu root python3 - --yes --version 2.1.3
RUN ln -sfn /usr/bin/python3 /usr/bin/python && \
    ln -sfn /opt/poetry/bin/poetry /usr/local/bin/poetry

# Clone and install xGPU
WORKDIR /app/
RUN git clone https://github.com/GPU-correlators/xGPU.git /app/xGPU/
WORKDIR /app/xGPU/src/
RUN make NFREQUENCY=1 NTIME=1835008 NTIME_PIPE=16384 install

# Clone and install TensorCoreCorrelator
WORKDIR /app/
RUN git clone https://git.astron.nl/RD/tensor-core-correlator.git
WORKDIR /app/tensor-core-correlator/
# The TCC is under active development and doesn't follow semver, so pin to a commit.
RUN git checkout 00a9b7b2f826bc3eac26a5368f4a604e33061e6e
RUN cmake -S . -B build
RUN make -C build
RUN make -C build install

# Install AAVS DAQ
RUN mkdir /app/aavs-system/ && mkdir /app/aavs-system/pydaq && mkdir /app/aavs-system/cdaq
COPY --chown=daqqer:daqqer /src/ska_low_mccs_daq/pydaq  /app/aavs-system/pydaq/
COPY --chown=daqqer:daqqer /src/ska_low_mccs_daq/cdaq /app/aavs-system/cdaq/
COPY --chown=daqqer:daqqer deploy.sh cdaq_requirements.pip /app/aavs-system/
WORKDIR /app/aavs-system
RUN ["/bin/bash", "-c", "source /app/aavs-system/deploy.sh"]

WORKDIR /src



EXPOSE 4660/udp
COPY --chown=daqqer:daqqer README.md pyproject.toml poetry.lock* ./
RUN poetry install --no-root

COPY --chown=daqqer:daqqer src ./
RUN poetry install
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10
RUN chmod a+w /app/
RUN mkdir /product && chmod a+w /product/

# Ensure root doesn't own things it shouldn't
# There should be a way to avoid this, but it works for now.
RUN chown daqqer:daqqer /product/ -R
RUN chown daqqer:daqqer /app/ -R
RUN chown daqqer:daqqer /opt/ -R

WORKDIR /app/

USER daqqer