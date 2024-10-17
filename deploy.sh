#!/usr/bin/env bash

if [[ -z "${AAVS_PYTHON_BIN}" ]]; then
  export PYTHON=/usr/bin/python3
else
  export PYTHON=${AAVS_PYTHON_BIN}
fi

# Function to display installer help
function display_help(){
    echo "This script will install the AAVS system software in /opt/aavs."
    echo
    echo "Arguments:"
    echo "-C             Correlator will be compiled, installing CUDA and xGPU in the process (off by default)"
    echo "               NOTE: Automated install of CUDA and xGPU not supported yet"
    echo "-p             Activate AAVS virtualenv in .bashrc (off by default)"
    echo "-a <aavs path> specifies location of installed AAVS (default /opt/aavs), must be absolute"
    echo "-v <venv path> specifies location of 'python' virtualenv folder (default /opt/aavs)"
    echo "-b <pyfabil_branch> specifies pyfabil branch to be installed"
    echo "-t <itpm_bios_branch> specifies itpm-bios branch to be installed"
    echo "-c             clean build directories and installed python virtual environment"
    echo "-d             installs requirements for documentation, requires at least python 3.8.1"
    echo "-h             Print this message"
    echo "
This script should not be executed with sudo, however the user executing it must have sudo privileges. Only the user
running this script will have privileges to install additional python packages in the virtual environment.

After sucessfully executing this script, a station configuration file should be created. Refer to
    config/default_config.yml
It is suggested to copy, rename and modify the default configuration according to the used system.

A test environment in available in python/pyaavs/tests, refer to
    python/pyaavs/tests/doc/TPM_Hardware_test_user_manual.docx

The following directories should be deleted when encountering issues running this script:
    /opt/aavs/python
    src/build
    python/build
    python/dist
    third_party

Using the command line option -c will delete the above folders before installing aavs-system.

If issues are experienced with the ipython version installed by default, install a different ipython version in the
virtual environment using:
    pip install ipython==5.5.0

This script uses /usr/bin/python3 as default Python interpreter. To use another interpreter, for instance python3.8
instead of default python3, do as follows:

    AAVS_PYTHON_BIN=/usr/bin/python3.8
    export AAVS_PYTHON_BIN
    ./deploy.sh"
}

# AAVS install directory. DO NOT CHANGE!
export AAVS_INSTALL=/opt/aavs
export VENV_INSTALL=/opt/aavs

# Installation options
CLEAN=false
COMPILE_CORRELATOR=ON
ACTIVATE_VENV=false
PRINT_HELP=false
PYFABIL_BRANCH="master"
ITPM_BIOS_BRANCH="main"
INSTALL_DOCS_REQS=false

# Process command-line arguments

while getopts "Chpcdb:t:v:a:" flag
do
    case "${flag}" in
        C) COMPILE_CORRELATOR=ON ;;
        h) PRINT_HELP=true ;;
        p) ACTIVATE_VENV=true ;;
        c) CLEAN=true ;;
        d) INSTALL_DOCS_REQS=true ;;
        b) PYFABIL_BRANCH=${OPTARG} ;;
        t) ITPM_BIOS_BRANCH=${OPTARG} ;;
        v) export VENV_INSTALL=${OPTARG%/}
           if [[ ${VENV_INSTALL:0:1} == "-" ]]; then # If argument is next option
             echo "Error: -${flag} requires an argument."
             exit 1                   # Exit abnormally.
           fi
           echo "Selected venv Path: $VENV_INSTALL" ;;
        a) export AAVS_INSTALL=${OPTARG%/}
           if [[ ${AAVS_INSTALL:0:1} == "-" ]]; then # If argument is next option
             echo "Error: -${flag} requires an argument."
             exit 1                   # Exit abnormally.
           fi
           echo "Selected AAVS Path: $AAVS_INSTALL" ;;

        \?)                                    # If expected argument omitted:
           echo "Error: missing argument."
           exit 1                   # Exit abnormally.
           ;;
    esac
done


if [ "$VENV_INSTALL" == "/opt/aavs" ]; then
    export VENV_INSTALL=$AAVS_INSTALL;
fi


# Check if printing help
if [ $PRINT_HELP == true ]; then
    display_help
    exit
fi

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


# Check if printing help
if [ $CLEAN == true ]; then
    echo "Cleaning aavs-system installation"
    sudo rm -r $VENV_INSTALL/python src/build python/build python/dist third_party
fi

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
    echo "export LD_LIBRARY_PATH=LD_LIBRARY_PATH:${AAVS_INSTALL}/lib" >> ~/.bashrc
  fi

  # Add directory to LD_LIBRARY_PATH
  if [[ ! ":$LD_LIBRARY_PATH:" == *"aavs"* ]]; then
    export LD_LIBRARY_PATH=$AAVS_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
  fi

  # Create bin directory and add to path
  if [ ! -d "$AAVS_INSTALL/bin" ]; then
    mkdir -p $AAVS_INSTALL/bin
    export PATH=$AAVS_INSTALL/bin:$PATH
    echo "export PATH=$PATH:${AAVS_INSTALL}/bin" >> ~/.bashrc
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
  sudo groupadd aavs_logger
  if [[ ! -d "$AAVS_INSTALL/log" ]]; then
    mkdir -p $AAVS_INSTALL/log
  fi
  sudo chgrp aavs_logger $AAVS_INSTALL/log
  sudo chmod 775 $AAVS_INSTALL/log
  sudo chmod g+s $AAVS_INSTALL/log
  if [[ -f "$AAVS_INSTALL/log/aavs.log" ]]; then
     sudo chmod 664 $AAVS_INSTALL/log/aavs.log
     sudo chgrp aavs_logger $AAVS_INSTALL/log/aavs.log
  fi



  # Create python3 virtual environment
  if [[ ! -d "$VENV_INSTALL/python" ]]; then
    mkdir -p $VENV_INSTALL/python

    # Create python virtual environment
    # virtualenv -p python3 $AAVS_INSTALL/python
    $PYTHON -m venv $VENV_INSTALL/python
    
    # Add AAVS virtual environment alias to .bashrc, uses default venv
    if [[ ! -n "`cat ~/.bashrc | grep aavs_python`" ]]; then
      echo "alias aavs_python=\"source /opt/aavs/python/bin/activate\"" >> ~/.bashrc
      echo "Setting virtual environment alias"

      # Check if compiling correlator
      if [ $ACTIVATE_VENV == true ]; then
          echo "aavs_python" >> ~/.bashrc
      fi
    fi
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

# If software directory is not defined in environment, set it
if [ -z "$AAVS_SOFTWARE_DIRECTORY" ]; then
  export AAVS_SOFTWARE_DIRECTORY=`pwd`
fi


if [[ ! -n "`cat $VENV_INSTALL/python/bin/activate | grep AAVS_INSTALL`" ]]; then
    echo "export AAVS_INSTALL=$AAVS_INSTALL" >> $VENV_INSTALL/python/bin/activate
fi

# Start python virtual environment
source $VENV_INSTALL/python/bin/activate

# Update pip
pip install -U pip

# Install ipython
pip install ipython

# Give python interpreter required capabilities for accessing raw sockets and kernel space
PYTHON_BINARY=`readlink -f $VENV_INSTALL/python/bin/python`
#sudo setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep $PYTHON_BINARY || exit

# Create a temporary setup directory and cd into it
if [[ ! -d "third_party" ]]; then
  mkdir third_party
fi

pushd third_party || exit

  # Install PyFABIL
  pip install git+https://gitlab.com/ska-telescope/pyfabil.git@$PYFABIL_SHA --force-reinstall

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
        cmake -DCMAKE_INSTALL_PREFIX=$AAVS_INSTALL -DWITH_BCC=OFF .. || exit
        make -B -j8 install || exit
      popd
    popd
  fi

  # Install itpm-bios
  pip install git+https://gitlab.com/sanitaseg/itpm-bios.git@$ITPM_BIOS_BRANCH --force-reinstall

popd

# Install C++ src
pushd src || exit
  if [ ! -d build ]; then
    mkdir build
  fi

  pushd build || exit
    cmake -DCMAKE_INSTALL_PREFIX=$AAVS_INSTALL -DWITH_CORRELATOR=$COMPILE_CORRELATOR .. || exit
    make -B -j4 install || exit
  popd
popd


# Install required python packages
pushd python || exit
  pip install -r requirements.pip || exit
  if [ $INSTALL_DOCS_REQS == true ]; then
    pip install -r requirements_docs.pip || exit
  fi
  python setup.py install || exit
popd

# Link required scripts to bin directory
FILE=$AAVS_BIN/acquire_station_beam
if [ -e $FILE ]; then
  sudo rm $FILE
fi
sudo cp $PWD/src/build/acquire_station_beam $AAVS_BIN/
chmod u+x $FILE

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

DIR=$AAVS_INSTALL/bitfiles
if [ -d $DIR ]; then
  sudo rm -r $DIR
fi
ln -s $PWD/bitfiles $DIR

DIR=$AAVS_INSTALL/config
if [ -d $DIR ]; then
  sudo rm -r $DIR
fi
ln -s $PWD/config $DIR


echo ""
echo "Installation finished. Please check your .bashrc file and source it to update your environment."
echo ""
echo "Instructions to update the TPM BIOS are available here: https://gitlab.com/sanitaseg/itpm-bios"
echo ""
