# TODO: Adding this image "as tools"
# so that we can copy the shell scripts
# that ska-tango-util expects this image to have
# is highly unsatisfactory.
# I've taken this from ska-tango-examples
# but hopefully a better solution will be found.
FROM artefact.skao.int/ska-tango-images-tango-dsconfig:1.5.13 AS tools


# ── Build stage ───────────────────────────────────────────────────────────────
# Holds the CUDA toolkit, the compilers and Poetry. Nothing from this stage
# reaches the final image except /opt/aavs, /src and the CUDA headers, so the
# build trees, nvcc and the CUDA static archives stay behind. The devcontainer
# targets this stage, because it is the one that can rebuild cdaq in place.
FROM artefact.skao.int/ska-build-cuda:1.0.0 AS build

ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=1
ENV POETRY_VIRTUALENVS_CREATE=1
ENV VIRTUAL_ENV=/src/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV DEBIAN_FRONTEND=noninteractive
ENV LC_ALL="en_US.UTF-8"
ENV DAQ_INSTALL="/opt/aavs"

# The build image lacks cmake and make. The rest are listed to keep the
# toolchain this build needs explicit. sudo is used by .devcontainer.
RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    cmake \
    curl \
    git \
    make \
    sudo

# The base image already has Poetry 2.1.3, under /root/.local, which the
# secure_path of sudo does not cover. The link makes `sudo poetry` work, which is
# how daqqer reaches it, because /root is 0700.
RUN ln -sfn /root/.local/bin/poetry /usr/local/bin/poetry

# Install AAVS DAQ. The cdaq build fetches and builds the DAQ core (libdaq) at
# the commit cdaq/cmake/AavsDaqSource.cmake pins, and installs it with the cdaq
# libraries into ${DAQ_INSTALL}, where the ctypes loader of pydaq finds them.
RUN mkdir -p /app/aavs-system/cdaq
COPY src/ska_low_mccs_daq/cdaq /app/aavs-system/cdaq/
WORKDIR /app/aavs-system/build
RUN cmake /app/aavs-system/cdaq \
        -DCMAKE_INSTALL_PREFIX="${DAQ_INSTALL}" \
        -DWITH_TCC=ON \
    && make -j8 install

WORKDIR /src
COPY README.md pyproject.toml poetry.lock* ./
RUN poetry install --no-root

COPY src ./
RUN poetry install


# ── Runtime stage ─────────────────────────────────────────────────────────────
# The CUDA runtime image of the same 12.9 toolkit the build stage uses, so every
# soname the libraries link resolves. It holds no compiler and no CUDA static
# archives, which is where the size saving comes from.
FROM artefact.skao.int/ska-cuda:1.0.1

ENV DEBIAN_FRONTEND=noninteractive
ENV VIRTUAL_ENV=/src/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV NVIDIA_VISIBLE_DEVICES="all"
ENV NVIDIA_DRIVER_CAPABILITIES="compute,utility"
ENV TZ="United_Kingdom/London"
ENV LC_ALL="en_US.UTF-8"
ENV DAQ_INSTALL="/opt/aavs"
ENV LD_LIBRARY_PATH="/opt/aavs/lib:/usr/local/lib:${LD_LIBRARY_PATH}"

# The runtime image lacks libcap2-bin (the setcap below), sudo (used by
# .devcontainer) and tzdata (the TZ above). It already has the python3.10 that
# the virtualenv points at. git is a runtime dependency, because GitPython
# reaches the interpreter through a main dependency and looks for the executable
# when it is imported, so `import ska_low_mccs_daq` fails without it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libcap2-bin \
    sudo \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

# Create non-root user. uid 1000 matches the fsGroup of the ADR-55 volume and the
# owner the COPY commands below set.
RUN useradd --create-home --home-dir /home/daqqer --uid 1000 daqqer
RUN mkdir -p /etc/sudoers.d/ && \
    echo "daqqer ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/daqqer && \
    chmod 0440 /etc/sudoers.d/daqqer

# TODO: Unsatisfactory; see comment above
COPY --from=tools /usr/local/bin/retry /usr/local/bin/retry
COPY --from=tools /usr/local/bin/wait-for-it.sh /usr/local/bin/wait-for-it.sh

# TCC compiles its correlator kernel with NVRTC on first use, and that kernel
# includes CUDA headers such as <cuda/barrier> and <mma.h>. The runtime image
# ships none of them. libtcc finds them by walking up from the directory of the
# loaded libnvrtc.so, so they have to land in the toolkit include directory that
# /usr/local/cuda/include also points at.
COPY --from=build /usr/local/cuda/targets/x86_64-linux/include \
                  /usr/local/cuda/targets/x86_64-linux/include

# The cdaq libraries plus libdaq.so and libtcc.so, and the virtualenv with the
# project installed into it. Owned by daqqer so a running container can write
# where it already could.
COPY --from=build --chown=1000:1000 /opt/aavs /opt/aavs
COPY --from=build --chown=1000:1000 /src /src

RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10

EXPOSE 4660/udp

# daqqer writes in its working directory, because the default output `directory`
# of the DAQ is "." and the DAQ creates directories below it. /product is the
# ADR-55 mount point, a volume with fsGroup 1000 at runtime, so only the mount
# point itself needs this.
RUN mkdir -p /app/ && chmod a+w /app/
RUN mkdir /product && chmod a+w /product/

WORKDIR /app/

USER daqqer
