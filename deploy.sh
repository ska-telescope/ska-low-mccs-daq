#!/bin/bash

# Declare array containing repositories to clone
declare -a repos=("aavs-access-layer" "aavs-tango" "aavs-daq" "aavs-backend")

# Create installation directory tree
function create_install() {
  # Create install directory if it does not exist
  if [ ! -d $AAVS_INSTALL ]; then
      mkdir -p $AAVS_INSTALL
  fi

  # Create subdirectories in install dir
  if [ ! -d "$AAVS_INSTALL/python" ]; then
    mkdir -p $AAVS_INSTALL/python

    # Create Python virtual environment
    virtualenv $AAVS_INSTALL/python
  fi

  if [ -z "$AAVS_PYTHON" ]; then
    echo "export AAVS_PYTHON=$AAVS_INSTALL/python" >> ~/.bashrc 
    export AAVS_PYTHON=$AAVS_INSTALL/python
  fi

  if [ ! -d "$AAVS_INSTALL/lib" ]; then
    mkdir -p $AAVS_INSTALL/lib
  fi

  if [[ ! ":$LD_LIBRARY_PATH:" == *"aavs"* ]]; then
    echo "export LD_LIBRARY_PATH=$AAVS_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" >> ~/.bashrc
    export LD_LIBRARY_PATH=$AAVS_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH} 
  fi
  
  if [ ! -d "$AAVS_INSTALL/bin" ]; then
    mkdir -p $AAVS_INSTALL/bin
  fi

  if [ -z "$AAVS_BIN" ]; then
    echo "export PATH=\$PATH:$AAVS_INSTALL/bin" >> ~/.bashrc
    echo "export AAVS_BIN=$AAVS_INSTALL/bin" >> ~/.bashrc  
    export AAVS_BIN=$AAVS_INSTALL/bin
  fi

  if [ ! -d "$AAVS_INSTALL/log" ]; then
    mkdir -p $AAVS_INSTALL/log
  fi

  if [ -z "$AAVS_LOG" ]; then
    echo "export AAVS_LOG=$AAVS_INSTALL/log" >> ~/.bashrc  
    export AAVS_LOG=$AAVS_INSTALL/log
  fi

  if [ -z "$AAVS_DATA" ]; then
    echo "export AAVS_LOG=$AAVS_INSTALL/data" >> ~/.bashrc
    export AAVS_DATA=$AAVS_INSTALL/data
  fi
}

echo -e "\n==== Configuring System for AAVS ====\n"

# Check if AAVS_PATH exists, and if so cd to it
source ~/.bashrc
if [ -z "$AAVS_PATH" ]; then 
    echo -e "AAVS_PATH not set. Please set AAVS_PATH to the top level AAVS directory"
    exit 1
fi

# Installing required system packages (including virtualenv)
echo "Installing required system packages"
sudo apt-get -q install --force-yes --yes $(grep -vE "^\s*#" requirements.apt  | tr "\n" " ")

# Create installation directory
create_install
echo "Created installed directory tree"

# Add AAVS virtual environment alias to .bashrc
if [ ! -n "`cat ~/.bashrc | grep aavs_env`" ]; then
  echo "alias aavs_env=\"source \$AAVS_PYTHON/bin/activate\"" >> ~/.bashrc
  echo "Setting virtual environment alias"
fi

# Activate Python virtual environment
source $AAVS_PYTHON/bin/activate

# Installing required python packages
pip install -r requirements.pip

# If required, build other repos
if [[ $1 = "y" ]]; then
  ./install_repos.sh
fi
