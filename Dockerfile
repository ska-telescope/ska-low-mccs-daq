FROM artefact.skao.int/ska-tango-images-pytango-builder:9.3.35 AS buildenv
FROM artefact.skao.int/ska-tango-images-pytango-runtime:9.3.22 AS runtime

USER root

# Commit SHAs to use.
# When updating AAVS_SYSTEM_SHA, also update aavs_system in pyproject.toml
ENV AAVS_SYSTEM_SHA=498662646fcbb50c4995a1246f207852e2430006
ENV AAVS_DAQ_SHA=65c8339543ff94818ccc9335583168c9b7f877f4
ENV PYFABIL_SHA=1aa0dc954fb701fd2a7fed03df21639fc4c50560

# CUDA variables
# ENV CUDA_VERSION=11.5.119
# ENV CUDA_PKG_VERSION=11-5=11.5.119-1
ENV CUDA_VERSION=10.2.89
ENV CUDA_PKG_VERSION=10-2=10.2.89-1
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENV NVIDIA_REQUIRE_CUDA=cuda>=10.2 brand=tesla,driver>=396,driver<397 brand=tesla,driver>=410,driver<411 brand=tesla,driver>=418,driver<419 brand=tesla,driver>=440,driver<441

# Setup NVIDIA Container Toolkit package repo + GPG key.
RUN apt-get update && apt-get install -y gpg
RUN distribution=$(. /etc/os-release;echo $ID$VERSION_ID) \
      && curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
      && curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
            tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive TZ="United_Kingdom/London" apt-get install -y \
    build-essential ca-certificates cmake libcap2-bin git make tzdata nvidia-cuda-toolkit nvidia-container-toolkit nvidia-driver-510 pciutils ubuntu-drivers-common lshw

#RUN nvidia-ctk

# Install AAVS DAQ
RUN git clone https://gitlab.com/ska-telescope/aavs-system.git /app/aavs-system/
WORKDIR /app/aavs-system
RUN git reset --hard ${AAVS_SYSTEM_SHA}
# Copy a version of deploy.sh that does not setcap. (Causes [bad interpreter: operation not permitted] error)
RUN cp /app/deploy.sh /app/aavs-system/
RUN ["/bin/bash", "-cC", "source /app/aavs-system/deploy.sh"]
# Install xGPU and replace a header file with one that has custom values.
# RUN git clone https://github.com/GPU-correlators/xGPU.git
# RUN cp /app/xgpu_info.h /app/xGPU/src/
# WORKDIR /app/xGPU/src/
# RUN make install
# Expose the DAQ port to UDP traffic.
EXPOSE 4660/udp
WORKDIR /app/

RUN poetry config virtualenvs.create false && poetry install --only main
RUN setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep /usr/bin/python3.10
USER tango
