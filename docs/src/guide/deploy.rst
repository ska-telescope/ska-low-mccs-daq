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

-----------------------------------
Adding a network attachment for DAQ
-----------------------------------
It is possible to allow the DAQ pod 
have access to low level network interfaces
This is achieved using Multus CNI.

An example can be seen below:

First we create the NetworkAttachmentDefinition:

.. code-block:: yaml
  
  network_attachments:
    sps: 
      config: |-
        {
          "cniVersion": "0.3.1",
          "type": "macvlan",
          "master": "eno1",
          "ipam": {
            "type": "static",
            "capabilities": {"ips": true}
          }
        }

Next we ensure this is used by the DAQ pod:

.. code-block:: yaml

  ska-low-mccs-daq:
    receivers:
      1: 
        receiver_interface: net1
        annotations: 
          k8s.v1.cni.cncf.io/networks: |-
            [
              {
                "name": "sps",
                "ips": ["10.0.10.3/24"]
              }
            ]
