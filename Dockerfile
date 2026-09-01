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
ENV DAQ_INSTALL="/opt/aavs"

ENV CMAKE_PREFIX_PATH="/opt/aavs:${CMAKE_PREFIX_PATH}"
ENV LD_LIBRARY_PATH="/opt/aavs/lib:/usr/local/lib:${LD_LIBRARY_PATH}"

# The base image lacks only cmake, libcap2-bin (setcap), libnuma-dev (libdaq
# links -lnuma), sudo (used by .devcontainer) and tzdata. The rest are listed to
# keep the toolchain this build needs explicit.
RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    cmake \
    curl \
    git \
    libcap2-bin \
    libnuma-dev \
    make \
    sudo \
    tzdata

# The base image already has Poetry 2.1.3, under /root/.local, which the
# secure_path of sudo does not cover. The link makes `sudo poetry` work, which is
# how daqqer reaches it, because /root is 0700. Runtime does not use Poetry.
RUN ln -sfn /root/.local/bin/poetry /usr/local/bin/poetry

# Install AAVS DAQ. The cdaq build fetches and builds the DAQ core (libdaq) at
# the commit cdaq/cmake/AavsDaqSource.cmake pins, and installs it with the cdaq
# libraries into ${DAQ_INSTALL}, where the ctypes loader of pydaq finds them.
RUN mkdir -p /app/aavs-system/cdaq
COPY --chown=daqqer:daqqer /src/ska_low_mccs_daq/cdaq /app/aavs-system/cdaq/
WORKDIR /app/aavs-system/build
RUN cmake /app/aavs-system/cdaq \
        -DCMAKE_INSTALL_PREFIX="${DAQ_INSTALL}" \
        -DWITH_TCC=ON \
    && make -j8 install

WORKDIR /src



EXPOSE 4660/udp
COPY --chown=daqqer:daqqer README.md pyproject.toml poetry.lock* ./
RUN poetry install --no-root

COPY --chown=daqqer:daqqer src ./
RUN poetry install
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10

# daqqer writes in its working directory, because the default output `directory`
# of the DAQ is "." and the DAQ creates directories below it. /product is the
# ADR-55 mount point, a volume with fsGroup 1000 at runtime, so only the mount
# point itself needs this.
RUN chmod a+w /app/
RUN mkdir /product && chmod a+w /product/

# Root installs the libraries daqqer loads from /opt/aavs. Change the owner so a
# devcontainer can rebuild them in place. The build trees under /app stay
# root-owned, because a recursive chown would only add another image layer.
RUN chown daqqer:daqqer /opt/aavs -R

WORKDIR /app/

USER daqqer