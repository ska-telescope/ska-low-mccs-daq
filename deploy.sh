#!/usr/bin/env bash

echo -e "\n==== Configuring AAVS System  ====\n"

# Currently, AAVS LMC has to be installed in this directory
# DO NOT CHANGE!
export AAVS_INSTALL=/opt/aavs

# Helper function to install required package
function install_package(){
    PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $1 | grep "install ok installed")
    if [[ "" == "$PKG_OK" ]]; then
      echo "Installing $1."
      sudo apt-get -qq --yes install $1 > /dev/null
      return  0 # Return success status
    else
      echo "$1 already installed"
      return 1  # Return fail status (already installed)
    fi
}

# Create installation directory tree
function create_install() {

  # Create install directory if it does not exist
  if [ ! -d "$AAVS_INSTALL" ]; then
	  sudo mkdir -p $AAVS_INSTALL
	  sudo chown $USER $AAVS_INSTALL
  fi

  # Create lib directory
  if [ ! -d "$AAVS_INSTALL/lib" ]; then
    mkdir -p $AAVS_INSTALL/lib
  fi

  # Add directory to LD_LIBRARY_PATH
  if [[ ! ":$LD_LIBRARY_PATH:" == *"aavs"* ]]; then
    export LD_LIBRARY_PATH=$AAVS_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH} 
  fi
  
  # Create bin directory and add to path
  if [ ! -d "$AAVS_INSTALL/bin" ]; then
    mkdir -p $AAVS_INSTALL/bin
    export PATH=$AAVS_INSTALL/bin:$PATH
  fi

  # Export AAVS bin directory
  if [ -z "$AAVS_BIN" ]; then
    export AAVS_BIN=$AAVS_INSTALL/bin
  fi

  # Create include directory
  if [[ ! -d "$AAVS_INSTALL/include" ]]; then
    mkdir -p $AAVS_INSTALL/include
  fi
  
  # Create log directory
  if [[ ! -d "$AAVS_INSTALL/log" ]]; then
    mkdir -p $AAVS_INSTALL/log
	chmod a+rw $AAVS_INSTALL/log
  fi

  # Create python3 virtual environment
  if [[ ! -d "$AAVS_INSTALL/python3" ]]; then
    mkdir -p $AAVS_INSTALL/python3

    # Create python virtual environment
    virtualenv -p python3 $AAVS_INSTALL/python3

    # Add AAVS virtual environment alias to .bashrc
    if [[ ! -n "`cat ~/.bashrc | grep aavs_python3`" ]]; then
      echo "alias aavs_python3=\"source \opt/aavs/python3/bin/activate\"" >> ~/.bashrc
      echo "aavs_python3" >> ~/.bashrc
      echo "Setting virtual environment alias"
    fi

  fi
}

# Installing required system packages
install_package cmake
install_package git
install_package git-lfs
install_package python2.7
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
echo "Created installed directory tree"

# If software directory is not defined in environment, set it
if [ -z "$AAVS_SOFTWARE_DIRECTORY" ]; then
  export AAVS_SOFTWARE_DIRECTORY=`pwd`
fi

# Start python virtual environment
source $AAVS_INSTALL/python3/bin/activate

# Update pip
pip install -U pip

# Install ipython
pip install ipython

# Give python interpreter required capabilities for accessing raw sockets and kernel space
sudo setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep $AAVS_INSTALL/python3/bin/python3

# Create a temporary setup directory and cd into it
if [[ ! -d "third_party" ]]; then
  mkdir third_party
fi

pushd third_party || exit

  # Install DAQ
  if [[ ! -d "aavs-daq" ]]; then
    git clone https://lessju@bitbucket.org/aavslmc/aavs-daq.git

    pushd aavs-daq/src || exit
      if [[ ! -d build ]]; then
        mkdir build
      fi
      
	  # Install DAQ C++ core
	  pushd build || exit
        cmake -DCMAKE_INSTALL_PREFIX=$AAVS_INSTALL -DWITH_BCC=OFF ..
        make -B -j8 install
      popd
    popd
  fi

  # Install PyFabil
  if [[ ! -d "pyfabil" ]]; then
    git clone https://lessju@bitbucket.org/lessju/pyfabil.git
  fi
  
  pushd pyfabil || exit
    python setup.py install
  popd
popd

# Install C++ src
pushd src || exit
  if [ ! -d build ]; then
    mkdir build
  fi

  pushd build || exit
    cmake -DCMAKE_INSTALL_PREFIX=$AAVS_INSTALL/lib -DWITH_CORRELATOR=ON ..
    make -B -j4 install
  popd
popd


# Install required python packages
pushd python || exit
  python setup.py install
popd

# Link required scripts to bin directory
FILE=$AAVS_BIN/daq_plotter.py
if [ -e $FILE ]; then
  sudo rm $FILE
fi
sudo ln -s $PWD/python/pydaq/daq_plotter.py $FILE
chmod u+x $FILE

FILE=$AAVS_BIN/daq_receiver.py
if [ -e $FILE ]; then
  sudo rm $FILE
fi
ln -s $PWD/python/pydaq/daq_receiver.py $FILE
chmod u+x $FILE

FILE=$AAVS_BIN/station.py
if [ -e $FILE ]; then
  sudo rm $FILE
fi
ln -s $PWD/python/pyaavs/station.py $FILE
chmod u+x $FILE

echo ""
echo "Installation finished. Please check your .bashrc file and source it to update your environment"
echo ""