# Build stage, also the devcontainer target.
FROM artefact.skao.int/ska-build-cuda-11:1.1.4 AS build

# CUDA_ARCH is the xGPU target.
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    VIRTUAL_ENV=/src/.venv \
    PATH="/src/.venv/bin:$PATH" \
    DEBIAN_FRONTEND=noninteractive \
    CUDA_ARCH=sm_80 \
    LC_ALL=C.UTF-8 \
    DAQ_INSTALL=/opt/aavs \
    CMAKE_PREFIX_PATH=/opt/aavs \
    LD_LIBRARY_PATH="/opt/aavs/lib:/usr/local/lib:${LD_LIBRARY_PATH}"

# The link lets daqqer run `sudo poetry`, because /root is 0700.
RUN apt-get update && apt-get install -y \
        build-essential ca-certificates cmake curl git libcap2-bin make sudo \
    && ln -sfn /root/.local/bin/poetry /usr/local/bin/poetry \
    && useradd --uid 1000 --create-home --home-dir /home/daqqer daqqer \
    && echo "daqqer ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/daqqer \
    && chmod 0440 /etc/sudoers.d/daqqer

# ldconfig, because python3.10 has file capabilities and ignores LD_LIBRARY_PATH.
RUN git clone https://github.com/GPU-correlators/xGPU.git /app/xGPU \
    && make -C /app/xGPU/src NFREQUENCY=1 NTIME=1835008 NTIME_PIPE=16384 install \
    && ldconfig

# Builds libdaq and the cdaq libraries into ${DAQ_INSTALL}.
COPY --chown=daqqer:daqqer src/ska_low_mccs_daq/cdaq /app/aavs-system/cdaq/
RUN cmake -S /app/aavs-system/cdaq -B /app/aavs-system/build \
        -DCMAKE_INSTALL_PREFIX="${DAQ_INSTALL}" -DWITH_CORRELATOR=ON -DWITH_TCC=ON \
    && make -C /app/aavs-system/build -j8 install \
    && chown -R daqqer:daqqer "${DAQ_INSTALL}"

# Only the main group, because the venv goes into the runtime image.
WORKDIR /src
COPY --chown=daqqer:daqqer README.md pyproject.toml poetry.lock* ./
RUN poetry install --only main --no-root
COPY --chown=daqqer:daqqer src ./

# The DAQ writes in its working directory. /product is the ADR-55 mount point.
RUN poetry install --only main \
    && setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10 \
    && chmod a+w /app \
    && mkdir -m 777 /product

WORKDIR /app/
USER daqqer


# Runtime stage.
FROM nvidia/cuda:11.8.0-base-ubuntu22.04

# The upgrade is needed because NVIDIA does not rebuild its image tags.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates cuda-nvrtc-11-8 libcap2-bin libgomp1 python3.10 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home --home-dir /home/daqqer daqqer \
    && mkdir -m 777 /app /product

# TCC compiles its kernel with NVRTC, which looks for these headers beside libnvrtc.
COPY --from=build /usr/local/cuda/targets/x86_64-linux/include \
                  /usr/local/cuda-11.8/targets/x86_64-linux/include
COPY --from=build /usr/local/lib/libxgpu.so /usr/local/lib/
COPY --from=build /opt/aavs /opt/aavs
COPY --from=build /src/.venv /src/.venv
COPY --from=build /src/ska_low_mccs_daq /src/ska_low_mccs_daq

# LD_LIBRARY_PATH is for the CI python-test job. GIT_PYTHON_REFRESH lets GitPython
# import without git.
ENV VIRTUAL_ENV=/src/.venv \
    PATH="/src/.venv/bin:$PATH" \
    DAQ_INSTALL=/opt/aavs \
    LD_LIBRARY_PATH="/opt/aavs/lib:/usr/local/lib:${LD_LIBRARY_PATH}" \
    LANG=C.UTF-8 \
    GIT_PYTHON_REFRESH=quiet

RUN ldconfig \
    && setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10

EXPOSE 4660/udp
WORKDIR /app/
USER 1000:1000
