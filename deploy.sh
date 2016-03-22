#!/bin/bash

# Declare array containing repositories to clone
declare -a repos=("aavs-access-layer" "aavs-tango" "aavs-daq")

# Helper function to install required package
function install_package(){
    PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $1 | grep "install ok installed")
    if [ "" == "$PKG_OK" ]; then
      echo "Installing $1."
      sudo apt-get --force-yes --yes install $1
    else
      echo "$1 already installed"
    fi
}

# Create installation directory tree
function create_install() {
  # Create install directory if it does not exist
  if [ ! -d $AAVS_INSTALL ]; then
      mkdir -p $AAVS_INSTALL

      # Create subdirectories in install dir
      if [ ! -d "$AAVS_INSTALL/python" ]; then
          mkdir -p $AAVS_INSTALL/python
          echo "export AAVS_PYTHON=$AAVS_INSTALL/python" >> ~/.bashrc 
          export AAVS_PYTHON=$AAVS_INSTALL/python
      fi
      
      if [ ! -d "$AAVS_INSTALL/lib" ]; then
          mkdir -p $AAVS_INSTALL/lib
          echo "export LD_LIBRARY_PATH=\$LD_LIBRARY_PATH:$AAVS_INSTALL/lib" >> ~/.bashrc
          export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$AAVS_INSTALL/python
      fi
  
      if [ ! -d "$AAVS_INSTALL/bin" ]; then
          mkdir -p $AAVS_INSTALL/bin
          echo "export PATH=\$PATH:$AAVS_INSTALL/bin" >> ~/.bashrc
          echo "export AAVS_BIN=$AAVS_INSTALL/bin" >> ~/.bashrc  
          export AAVS_BIN=$AAVS_INSTALL/bin
      fi

      # Create Python virtual environment
      echo $AAVS_PYTHON
      virtualenv $AAVS_PYTHON
  else
    echo "Install directory already exists, skipping creation"
  fi
}

echo -e "\n==== Configuring System for AAVS ====\n"

# Check if AAVS_PATH exist, and if so cd to it
source ~/.bashrc
if [ -z "$AAVS_PATH" ]; then 
    echo -e "AAVS_PATH not set. Please set AAVS_PATH to the top level AAVS directory"
    exit 1
fi

# Installing required system packages
echo "Installing required system packages"
sudo apt-get -q install --force-yes --yes $(grep -vE "^\s*#" requirements.apt  | tr "\n" " ")

# Install python virtual environment
sudo pip install virtualenv

# Create installation directory
create_install
echo "Created installed directory tree"

# Activate Python virtual environment
source $AAVS_PYTHON/bin/activate

# Installing required python packages
pip install -r requirements.pip

# Loop over all required repos
cd $AAVS_PATH
current=`pwd`
for repo in "${repos[@]}"; do

  # Check if directory already exists
  if [ ! -d $repo ]; then
    echo -e "\nCloning $repo"
    git clone https://lessju@bitbucket.org/aavslmc/$repo.git
  else
    echo -e "\n$repo already cloned"
  fi

  # Repository cloned, pull to latest
  cd $AAVS_PATH/$repo
  git pull

  # Repository pulled, call deployment script
  if [ ! -e "deploy.sh" ]; then
    echo "No deployment script for $repo"
  else
    echo "Deploying $repo"
    bash deploy.sh
  fi
  cd $current 
done

