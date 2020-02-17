#!/bin/bash

echo "This script has not been updated yet. Do not use."
exit

echo -e "\n==== Configuring AAVS System  ====\n"

# Currently, AAVS LMC has to be installed in this directory
# DO NOT CHANGE!
export AAVS_INSTALL_DIRECTORY=/opt/aavs

# Create installation directory tree
function create_install() {

  # Create install directory if it does not exist
  if [ -z "$AAVS_INSTALL" ]; then
    export AAVS_INSTALL=$AAVS_INSTALL_DIRECTORY

    # Check whether directory already exists
    if [ ! -d "$AAVS_INSTALL_DIRECTORY" ]; then
      # Check whether we have write persmission
      parent_dir="$(dirname "$AAVS_INSTALL_DIRECTORY")"
      if [ -w "$parent_dir" ]; then
        mkdir -p $AAVS_INSTALL_DIRECTORY
      else
        sudo mkdir -p $AAVS_INSTALL_DIRECTORY
        sudo chown $USER $AAVS_INSTALL_DIRECTORY
      fi
    fi
  fi

  if [ ! -d "$AAVS_INSTALL/lib" ]; then
    mkdir -p $AAVS_INSTALL/lib
  fi

  if [[ ! ":$LD_LIBRARY_PATH:" == *"aavs"* ]]; then
    export LD_LIBRARY_PATH=$AAVS_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH} 
  fi
  
  if [ ! -d "$AAVS_INSTALL/bin" ]; then
    mkdir -p $AAVS_INSTALL/bin
  fi

  if [ -z "$AAVS_BIN" ]; then
    export AAVS_BIN=$AAVS_INSTALL/bin
  fi
}

# Installing required system packages
echo "Installing required system packages"
sudo apt-get -q install --force-yes --yes $(grep -vE "^\s*#" requirements.apt  | tr "\n" " ")

# Create installation directory
create_install
echo "Created installed directory tree"

# Installing requirements for eBPF
#CODENAME=`lsb_release -c`
#sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys D4284CDD
#echo "deb https://repo.iovisor.org/apt "${CODENAME//Codename:}" main" | sudo tee /etc/apt/sources.list.d/iovisor.list
#sudo apt-get update
#sudo apt-get -q install --force-yes --yes binutils bcc bcc-tools libbcc-examples python-bcc

# Build C++ library
echo "Building Source"
pushd src || exit
if [ ! -d build ]; then
  mkdir build
fi
pushd build || exit

# Check if AAVS_PATH exists, and if so cd to it
if [ -z $AAVS_INSTALL ]; then
    echo "AAVS_INSTALL not set in termninal"
    exit 1
else
  # Build library
  cmake -DCMAKE_INSTALL_PREFIX=$AAVS_INSTALL/lib -DWITH_CORRELATOR=OFF ..
  make -B -j4 install
fi
popd || exit
popd || exit

# Install required python packages
pushd python || exit

# Check if we are using python in virtual env, if not we need to install
# numpy via synaptic (not sure why)
if [ `python -c "import sys; print hasattr(sys, 'real_prefix')"` = "False" ]; then  
    sudo apt-get -q install --force-yes --yes python-numpy
fi

pip install -r requirements.pip

# Give python interpreter required capabilities for accessing raw sockets and kernel space
PYTHON=`which python`
sudo setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep `readlink -f $PYTHON`

# Install DAQ python library
python setup.py install

# Link required scripts to bin directory
pushd pydaq || exit
FILE=$AAVS_BIN/daq_plotter.py
if [ ! -e $FILE ]; then
  ln -s $PWD/daq_plotter.py $FILE
fi

FILE=$AAVS_BIN/daq_receiver.py
if [ ! -e $FILE ]; then
  ln -s $PWD/daq_receiver.py $FILE
fi

popd || exit

# Finished with python
popd || exit

