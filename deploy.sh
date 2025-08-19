#!/usr/bin/env bash

if [[ -z "${AAVS_PYTHON_BIN}" ]]; then
  export PYTHON=/usr/bin/python3
else
  export PYTHON=${AAVS_PYTHON_BIN}
fi

# AAVS install directory. DO NOT CHANGE!
export DAQ_INSTALL=/opt/aavs
COMPILE_CORRELATOR=ON

# Check if compiling correlator
if [ $COMPILE_CORRELATOR == ON ]; then
    echo "============ COMPILING CORRELATOR ==========="
else
    echo "========== NOT COMPILING CORRELATOR ========="
fi

echo -e "\n==== Configuring AAVS System  ====\n"

# Helper function to install required package
function install_package(){
    PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $1 | grep "install ok installed")
    if [[ "" == "$PKG_OK" ]]; then
      echo "Installing $1."
      sudo apt-get -qq --yes install $1 > /dev/null || exit
      return  0 # Return success status
    else
      echo "$1 already installed"
      return 1  # Return fail status (already installed)
    fi
}

# Create installation directory tree
function create_install() {

  # Create install directory if it does not exist
  if [ ! -d "$DAQ_INSTALL" ]; then
	  sudo mkdir -p $DAQ_INSTALL
	  sudo chown $USER $DAQ_INSTALL
  fi

  # Create lib directory
  if [ ! -d "$DAQ_INSTALL/lib" ]; then
    mkdir -p $DAQ_INSTALL/lib
    echo "export LD_LIBRARY_PATH=LD_LIBRARY_PATH:${DAQ_INSTALL}/lib" >> ~/.bashrc
  fi

  # Add directory to LD_LIBRARY_PATH
  if [[ ! ":$LD_LIBRARY_PATH:" == *"aavs"* ]]; then
    export LD_LIBRARY_PATH=$DAQ_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
  fi

  # Create bin directory and add to path
  if [ ! -d "$DAQ_INSTALL/bin" ]; then
    mkdir -p $DAQ_INSTALL/bin
    export PATH=$DAQ_INSTALL/bin:$PATH
    echo "export PATH=$PATH:${DAQ_INSTALL}/bin" >> ~/.bashrc
  fi

  # Export AAVS bin directory
  if [ -z "$AAVS_BIN" ]; then
    export AAVS_BIN=$DAQ_INSTALL/bin
  fi

  # Create include directory
  if [[ ! -d "$DAQ_INSTALL/include" ]]; then
    mkdir -p $DAQ_INSTALL/include
  fi
}

# Installing required system packages
install_package cmake
install_package git
install_package git-lfs
install_package libyaml-dev
install_package python3-dev
install_package python3-virtualenv
install_package libnuma-dev
install_package build-essential

# Set up NTP synchronisation
if install_package ntp; then
    sudo service ntp reload
fi

# Create installation directory
create_install
echo "Created installation directory tree"

# Update pip
pip install -U pip

# Create a temporary setup directory and cd into it
if [[ ! -d "third_party" ]]; then
  mkdir third_party
fi

pushd third_party || exit

  # Install DAQ
  if [[ ! -d "aavs-daq" ]]; then
    git clone https://gitlab.com/ska-telescope/aavs-daq

    pushd aavs-daq || exit
      git reset --hard $AAVS_DAQ_SHA
    popd

    pushd aavs-daq/src || exit
      if [[ ! -d build ]]; then
        mkdir build
      fi
	# Install DAQ C++ core
        pushd build || exit
        cmake -DCMAKE_INSTALL_PREFIX=$DAQ_INSTALL -DWITH_BCC=OFF .. || exit
        make -B -j8 install || exit
      popd
    popd
  fi

  # Install CudaWrapper
  if [[ ! -d "cudawrappers" ]]; then
    git clone https://github.com/nlesc-recruit/cudawrappers

    pushd cudawrappers || exit
      if [[ ! -d build ]]; then
        mkdir build
      fi

        pushd build || exit
        cmake -DCMAKE_INSTALL_PREFIX=$DAQ_INSTALL -DCMAKE_INSTALL_LIBDIR=lib -S .. -B build || exit
        make -C build || exit
        make -C build install || exit
      popd
    popd
  fi
popd

# Install C++ src
if [ ! -d build ]; then
  mkdir build
fi

pushd build || exit
  cmake -DCMAKE_INSTALL_PREFIX=$DAQ_INSTALL -DWITH_CORRELATOR=$COMPILE_CORRELATOR -DCMAKE_INSTALL_LIBDIR=lib ../cdaq || exit
  make -B -j4 install || exit
popd

Install required python packages
pip install -r cdaq_requirements.pip || exit
pip install .

echo ""
echo "Installation finished."
echo ""
