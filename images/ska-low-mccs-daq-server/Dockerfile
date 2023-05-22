FROM artefact.skao.int/ska-tango-images-tango-dependencies:9.4.1 AS tango_deps
FROM artefact.skao.int/ska-tango-images-pytango-builder:9.3.35 AS buildenv
FROM artefact.skao.int/ska-tango-images-pytango-runtime:9.3.22 AS pytango_runtime
FROM nvidia/cuda:11.6.1-base-ubuntu20.04 AS base

USER root
# nuclear option...
COPY --from=pytango_runtime / /
# Copy retry/wait-for-it from SKAO image.
# COPY --from=tango_deps /usr/local /usr/local
COPY . /app

# Commit SHAs to use.
# When updating AAVS_SYSTEM_SHA, also update aavs_system in pyproject.toml
ENV AAVS_SYSTEM_SHA=498662646fcbb50c4995a1246f207852e2430006
ENV AAVS_DAQ_SHA=65c8339543ff94818ccc9335583168c9b7f877f4
ENV PYFABIL_SHA=1aa0dc954fb701fd2a7fed03df21639fc4c50560
ENV DEBIAN_FRONTEND=noninteractive
# CUDA variables
# ENV CUDA_VERSION=11.5.119
# ENV CUDA_PKG_VERSION=11-5=11.5.119-1
# ENV CUDA_VERSION=10.2.89
# ENV CUDA_PKG_VERSION=10-2=10.2.89-1
#ENV NVIDIA_VISIBLE_DEVICES all
#ENV NVIDIA_DRIVER_CAPABILITIES compute,utility
#ENV NVIDIA_REQUIRE_CUDA "cuda>=11.5"

# Setup NVIDIA Container Toolkit package repo + GPG key.
RUN apt-get update && apt-get install -y software-properties-common
RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt-get update && apt-get install -y python3.10 python3.10-distutils curl sudo pkg-config
RUN apt-get install -y nvidia-utils-510

#RUN update-alternatives --install /usr/bin/python3 python /usr/bin/python3.8 1
RUN update-alternatives --install /usr/bin/python3 python /usr/bin/python3.10 2
#RUN apt-get install -y python3-pip
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3.10
#RUN apt-get update && apt-get install -y 
#  curl sudo 
# Create symlink to python3.
RUN export PATH="/usr/bin/python:/usr/bin/python3:/usr/bin/python3.10:$PATH"
#RUN ["/usr/bin/ln", "-s", "/usr/bin/python3.10", "/usr/bin/python3"]
#RUN ["/usr/bin/ln", "-s", "/usr/bin/python3.10", "/usr/bin/python"]

#COPY --from=pytango_runtime /usr/local/lib/ /usr/local/lib/
#COPY --from=pytango_runtime /usr/local/bin /usr/local/bin
RUN python3.10 -m pip install poetry
# Fix distro-info being non pep compliant
RUN apt -y autoremove python3-debian python3-distro-info
# RUN distribution=$(. /etc/os-release;echo $ID$VERSION_ID) \
#       && curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
#       && curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
#             sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
#             tee /etc/apt/sources.list.d/nvidia-container-toolkit.list


RUN apt-get update && \
    TZ="United_Kingdom/London" apt-get install -y \
    build-essential ca-certificates cmake libcap2-bin git make tzdata 
# RUN apt-get update && apt-get install -y nvidia-cuda-toolkit nvidia-container-toolkit nvidia-container-runtime
#RUN apt-get update && apt-get install -y pciutils ubuntu-drivers-common lshw

#RUN nvidia-ctk

# Install AAVS DAQ
RUN git clone https://gitlab.com/ska-telescope/aavs-system.git /app/aavs-system/
WORKDIR /app/aavs-system
RUN git reset --hard ${AAVS_SYSTEM_SHA}
# Copy a version of deploy.sh that does not setcap. (Causes [bad interpreter: operation not permitted] error)
COPY deploy.sh /app/aavs-system/
RUN ["/bin/bash", "-cC", "source /app/aavs-system/deploy.sh"]
# Install xGPU and replace a header file with one that has custom values.
# RUN git clone https://github.com/GPU-correlators/xGPU.git
# RUN cp /app/xgpu_info.h /app/xGPU/src/
# WORKDIR /app/xGPU/src/
# RUN make install
# Expose the DAQ port to UDP traffic.
EXPOSE 4660/udp
WORKDIR /app/

COPY images/ska-low-mccs-daq-server/pyproject.toml .

RUN pip uninstall -y virtualenv
RUN pip install -U virtualenv
RUN poetry config virtualenvs.create false && poetry install -vvv --only main
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10

#RUN useradd -ms /bin/bash tango
USER tango
