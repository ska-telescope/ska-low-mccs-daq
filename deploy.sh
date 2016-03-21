#!/bin/bash

# Declare array containing repositories to clone
declare -a repos=("aavs-access-layer" "aavs-tango")

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
          AAVS_PYTHON=$AAVS_INSTALL/python
      fi
      
      if [ ! -d "$AAVS_INSTALL/lib" ]; then
          mkdir -p $AAVS_INSTALL/lib
          echo "export LD_LIBRARY_PATH=\$LD_LIBRARY_PATH:$AAVS_INSTALL/lib" >> ~/.bashrc
          LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$AAVS_INSTALL/python
      fi
  
      if [ ! -d "$AAVS_INSTALL/bin" ]; then
          mkdir -p $AAVS_INSTALL/bin
          echo "export PATH=\$PATH:$AAVS_INSTALL/python" >> ~/.bashrc
          echo "export AAVS_BIN=\$PATH:$AAVS_INSTALL/bin" >> ~/.bashrc  
          AAVS_BIN=$AAVS_PATH:/bin
      fi

      # Create Python virtual environment
      echo $AAVS_PYTHON
      virtualenv $AAVS_PYTHON
  else
    echo "Install directory already exists, skipping creation"
  fi
}

echo -e "\n==== Configuring System for AAVS ====\n"

# Installing required system packages
echo "Installing required system packages"
#sudo apt-get -qq update
#sudo apt-get -q install --force-yes --yes $(grep -vE "^\s*#" requirements.apt  | tr "\n" " ")

# Check if AAVS install directory has been passed as an argument
if [ -z "$AAVS_INSTALL" ]; then
  if [[ $# -lt 1 ]]; then
    echo "AAVS install directory required as argument"
    exit 1
  else
    echo "export AAVS_INSTALL=`echo $1`" >> ~/.bashrc 
    source ~/.bashrc
  fi
elif [ $# -lt 1 ]; then
  echo "AAVS_INSTALL already defined, ignoring argument $1"
fi

# Create installation directory
create_install
source ~/.bashrc
echo "Created installed directory tree"

# Activate Python virtual environment
source $AAVS_PYTHON/bin/activate

# Check if AAVS_PATH exist, and if so cd to it
if [ -z "$AAVS_PATH" ]; then 
    echo -e "AAVS_PATH not set. Please set AAVS_PATH to the top level AAVS directory"
    exit 1
fi
cd $AAVS_PATH

# Loop over all required repos
current=`pwd`
for repo in "${repos[@]}"; do

  # Check if directory already exists
  if [ ! -d $repo ]; then
    echo -e "\nCloning $repo"
    git clone https://lessju@bitbucket.org/aavslmc/$repo.git
  else
    echo -e "\n$repo already cloned"
  fi

  # Repository cloned, call deployment script
  cd $AAVS_PATH/$repo
  if [ ! -e "deploy.sh" ]; then
    echo "No deployment script for $repo"
  else
    echo "Deploying $repo"
    bash deploy.sh
  fi
  cd $current 
done

which python

