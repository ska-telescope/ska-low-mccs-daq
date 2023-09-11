=========
Deploying
=========

As a component of the MCCS subsystem,
ska-low-mccs-daq would not normally be deployed directly,
except for development purposes.
This guidance is aimed at developers,
and should be read in conjunction with the MCCS subsystem documentation
on deploying the MCCS subsystem as a whole.

``ska-low-mccs-daq`` uses helmfile to configure helm values files.

---------------------
Deploy using helmfile
---------------------
To deploy ``ska-low-mccs-daq`` onto a k8s cluster, use the command
``helmfile --environment <environment_name> sync``.
To see what environments are supported,
see the ``environments`` section of ``helmfile.d/helmfile.yaml``.

(Although helmfile supports k8s context switching, this has not yet
been set up. You must manually set your k8s context for the platform
you are targetting, before running the above command.)

To tear down a release that has been deployed by helmfile,
use the command ``helmfile <same arguments> destroy``.
It is important that the arguments to the ``destroy`` command
be the same as those used with the ``sync`` command.
For example, if the release was deployed with ``helmfile --environment gmrt sync``,
then it must be torn down with ``helmfile --environment gmrt destroy``.
If arguments are omitted from the ``helmfile destroy`` command,
the release may not be fully torn down.

--------------------------------
Deploy using the .make submodule
--------------------------------
The ``ska-low-mccs-daq`` repo includes the ``ska-cicd-makefile`` submodule,
and thus supports the SKA-standard ``make install-chart`` and ``make uninstall-chart`` targets.
When using this approach,
use the ``K8S_HELMFILE_ENV``environment variable to specify the environment.
For example, ``make K8S_HELMFILE_ENV=aavs3-minikube install-chart`` and
``make K8S_HELMFILE_ENV=aavs3-minikube uninstall-chart``.

------------
How it works
------------
The ``environments`` section of ``helmfile.d/helmfile.yaml`` specifies
a sequence of helmfile values files for each environment.
The first file will generally be a specification of the target platform.
This file should only change when the platform itself changes.

For example, the platform specification for PSI-Low is:

.. code-block:: yaml

   platform:
     metadata:
       version: 0.0.3
       description: A platform configuration specification for the PSI-Low.

     cluster:
       domain: cluster.local
       services:
         jupyterhub: true
         taranta-platform: true
       daq:
         storage_class: nfss1
         node_selector:
           kubernetes.io/hostname: psi-node3

     array:
       name: psi-low
       stations:
         "1":
           name: psi-low
           sps:
             subracks:
               "1":
                 srmb_host: 10.0.10.80
                 srmb_port: 8081
                 nodeSelector:
                   kubernetes.io/hostname: psi-node3
             tpms:
               "10":
                 host: 10.0.10.218
                 port: 10000
                 version: tpm_v1_6
                 subrack: 1
                 subrack_slot: 2
                 nodeSelector:
                   kubernetes.io/hostname: psi-node3
               "13":
                 host: 10.0.10.215
                 port: 10000
                 version: tpm_v1_6
                 subrack: 1
                 subrack_slot: 5
                 nodeSelector:
                   kubernetes.io/hostname: psi-node3

Subsequent files may specify default values (via key ``defaults``)
and overrides (via key ``overrides``);
but this helmfile only makes use of the latter.

The ``overrides`` key follows the structure of the platform specification,
but with values to override or augment that specification.
For example, for a platform that provides a DAQ receiver as a platform service,
(so that here we only need to set up egress to that service),
we can override the IP address of that service with:

.. code-block:: yaml

   overrides:
     array:
       stations:
         "1":
           sps:
             daq:
               ip: 10.80.81.82

Two special keys are supported:

* The ``enabled`` key can be used to enable or disable deployment of a DAQ instance.
  For example, to disable deployment of a station's DAQ instance:

    .. code-block:: yaml

       overrides:
         array:
           stations:
             "1":
               sps:
                 daq:
                   enabled: false

    One can also disable an entire station, and then explicitly enable its DAQ:

    .. code-block:: yaml

       overrides:
         array:
           stations:
             "1":
               enabled: false
               sps:
                 daq:
                   enabled: true

* The ``simulated`` key indicates that
  monitoring and control of a DAQ instance
  should run against a simulator.
  For the purposes of this repo,
  it is equivalent to (the negation of) the ``enabled`` key:
  if ``simulated`` is true, then the real thing should be disabled.

  For example:

  .. code-block:: yaml

     overrides:
       array:
         stations:
           "1":
             sps:
               daq:
                 simulated: true

--------------------------------
Direct deployment of helm charts
--------------------------------
It is possible to deploy helm charts directly.
However note that helm chart configuration is handled by helmfile,
so the helm chart values files are expected to provide
a deterministic, fully-configured specification
of what devices and simulators should be deployed.
For example:

.. code-block:: yaml

   storage:
     daq_data:
       storage_class: nfss1
       size: "250Mi"

   receivers:
     1:
       gpu_limit: "1"
       runtime_class: nvidia
       storage: daq_data


----------------------------
Deployment of a external DAQ
----------------------------
Minikube has limitations that kubernetes does not.
One of these is related to networking, to stream data 
from the TPM to DAQ, the DAQ requires low level access to the 
network interface. To overcome this issue the the daq server
is deployed external to the DAQ tango device. This external 
server is run in a container with evevated permissions to 
access the low level network interface. We can then connect 
to this server from minikube and have access to the low level 
network interface.


First we will want to run a container external to minikube on the 
host with access to the low level network interface:

.. code-block:: bash

  docker run --net=host --cap-add=NET_RAW --cap-add=IPC_LOCK --cap-add=SYS_NICE --cap-add=SYS_ADMIN artefact.skao.int/ska-low-mccs-daq:0.4.0 python3 /app/src/ska_low_mccs_daq/daq_handler.py

This will start the server, see logs:

.. code-block:: bash

  2023-03-21 05:43:33,502 - INFO - MainThread - generated new fontManager
  Starting daq server...
  Server started, listening on 50051

We can then deploy minikube and connect our tango DAQ to this external server. 
To do this we use the ska-low-mccs-spshw repor (hosting the DAQ tango device) and 
configure the chart to:

.. code-block:: yaml

  overrides:
    array:
      station_clusters:
        "xyz":
          stations:
            "1":
              sps:
                daq:
                  ip: 10.0.255.255 # The network interface on host.
                  port: 50051 # the port to connect to server.
                  receiver_interface: eth0 # the interface the tpm is sending data to 
                  receiver_port: 4660 # the port tpm is sending data to
                  logging_level_default: 5

followed by:

.. code-block:: bash

  helmfile -e '<platform_spec>' sync

Finally when you call daq_proxy.adminMode = AdminMode.ONLINE,
you should see the tango_device connecting to the external DAQ.
