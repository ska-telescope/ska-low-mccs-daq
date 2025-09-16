MccsDaqReceiver Starting, Stopping and Configuring Scans
========================================================

This page aims to provide users with a simple guide to initiating scans with the DAQ receiver.

------------------------
Starting MccsDaqReceiver
------------------------

The MccsDaqReceiver device can be started by calling the Start command on a device proxy.
This command accepts a json formatted string as such:

.. code-block:: python

    setup = {"modes_to_start": "INTEGRATED_CHANNEL_DATA, RAW_DATA"}
    daq.Start(json.dumps(setup))

The ``setup`` variable in this case is a dictionary with a key ``"modes_to_start"`` and the values
``"INTEGRATED_CHANNEL_DATA, RAW_DATA"``. The command will then convert the values into an enum list
and pass them to the daq client.

The following is a list of available modes:

- RAW_DATA
- CHANNEL_DATA
- BEAM_DATA
- CONTINUOUS_CHANNEL_DATA
- INTEGRATED_BEAM_DATA
- INTEGRATED_CHANNEL_DATA
- STATION_BEAM_DATA
- CORRELATOR_DATA
- ANTENNA_BUFFER
- RAW_STATION_BEAM

.. Caution::
    RAW_STATION_BEAM will raise an error and reject the command when started alongside other modes.

---------------------------
Configuring MccsDaqReceiver
---------------------------

By default, once the Start command has begun, all the data will be saved within a dictionary of form:
``/product/eb-id/ska-low-mccs/scan-id/``. Users can change this (and many other configurations) with
the ``Configure()`` command:

.. code-block:: python

    configs = {'directory': 'user/specific/directory'}
    daq.Configure(json.dumps(configs))

.. Admonition::
    Directory structure

    The directory used by the daq must be of form: ``/product/eb-id/ska-low-mccs/.scan-id/``. When 
    configuring the directory as a path that doesn't adhere to the above form, the code will create
    a new path and append the user specified path to it.

    Additionally, the fourth path will always be used as a 'marker'. This means that the path will
    have a "." prepended to it at the start of the code and the dot will be removed when users call
    the ``MarkDone()`` command.

The rest of the options available to the configure command are listed in the API section of the docs.

----------------------------
Stopping the MccsDaqReceiver
----------------------------

The ``Stop()`` command requires on inputs and stops the scan when called:

.. code-block:: python

    daq.Stop()

-----------------
Notifying the DLM
-----------------

In order to notify the DLM of finished scans the device uses directory markers. When a scan is
started, the directory containing the scan (named after the scan id) has its name modified to mark
a scan in progress. By default this adds a dot before the scan id as the directory name.

As mentioned before, an initial directory will start with the following form:

.. code-block:: shell

    /product/eb-id/ska-low-mccs/scan-id/user/path

Then, when a user starts the scan the path will be changed to:

.. code-block:: shell

    /product/eb-id/ska-low-mccs/.scan-id/user/path

Users can change the tag used by calling the configure command and specifying a new tag as such:

.. code-block:: python

    configs = {'directory_tag': '_in_progress'}
    daq.Configure(json.dumps(configs))

This will change the tag used to mark a scan by appending it to the directory:

.. code-block:: shell

    /product/eb-id/ska-low-mccs/scan-id_in_progress/user/path

To return to the default tag, users can use "", ".", and "default" as directory tag:

.. code-block:: python

    configs = {'directory_tag': ''}
    configs = {'directory_tag': '.'}
    configs = {'directory_tag': 'default'}

The above configs will all result in the tag changing to the default:

.. code-block:: shell

    /product/eb-id/ska-low-mccs/scan-id/user/path

To mark a scan as finished, users can call the ``MarkDone`` command. This will remove the last tag used:

.. code-block:: python

    daq.MarkDone()

.. Caution::
    While the code can accept any string as a tag, it's recommended that users are mindful of the choices they make.
    Slashes, spaces, tabs and other such characters will be removed from the tag. 
