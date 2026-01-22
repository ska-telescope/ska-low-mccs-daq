Adding Dynamic Metadata to DAQ HDF5 Files
============================================

Overview
--------

The DAQ system now supports adding arbitrary metadata fields to HDF5 files after consumers have been started. This is useful for metadata that becomes available during data acquisition, such as pointing information that may not be known until after observation begins.

Use Cases
---------

* **Pointing Information**: Add RA/Dec, Alt/Az, or other coordinate information as it becomes available
* **Reference Frames**: Add reference frame metadata with dynamically-named fields based on the frame type
* **Observation Context**: Add target names, observation modes, environmental conditions, etc.
* **Processing Notes**: Add calibration information, processing flags, or quality metrics during acquisition

Key Features
------------

1. **Arbitrary Field Names**: Add any metadata key-value pairs - field names are not restricted
2. **Dynamic Field Names**: Field names can vary based on context (e.g., "ra"/"dec" vs "altitude"/"azimuth")
3. **Retroactive Updates**: Can update existing file partitions that have already been written
4. **Selective Updates**: Can target specific consumers or all running consumers
5. **Future-Only Updates**: Can apply metadata only to future file partitions if desired

API
---

DaqReceiver Interface

~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def add_daq_metadata(
        self,
        metadata: Dict[str, Any],
        update_existing: bool = True,
        consumer_modes: Optional[List[DaqModes]] = None,
    ) -> Dict[DaqModes, Dict[str, Any]]:

**Parameters:**

* ``metadata``: Dictionary of key-value pairs to add/update
* ``update_existing``: If True (default), updates existing file partitions. If False, only applies to future partitions
* ``consumer_modes``: List of specific consumer modes to update (e.g., ``[DaqModes.BEAM_DATA]``). If None, updates all running consumers

**Returns:**

Dictionary mapping each consumer mode to its update result:

.. code-block:: python

    {
        DaqModes.BEAM_DATA: {
            "updated_partitions": 2,
            "errors": []
        }
    }

Legacy Interface
~~~~~~~~~~~~~~~~

.. code-block:: python

    def add_daq_metadata(metadata, update_existing=True, consumer_modes=None):

Same parameters and return value as the interface version.

Examples
--------

Example 1: Basic Usage - Adding Pointing Information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ska_low_mccs_daq.pydaq.daq_receiver_interface import DaqReceiver

    daq = DaqReceiver()

    # Configure and start consumer
    daq.populate_configuration(config)
    daq.initialise_daq()
    daq.start_beam_data_consumer()

    # Later, when pointing becomes available, add it to files
    result = daq.add_daq_metadata({
        "reference_frame": "ICRS",
        "ra": 123.456,
        "dec": 67.890,
    })

    print(f"Updated {result[DaqModes.BEAM_DATA]['updated_partitions']} partition(s)")

Example 2: Dynamic Field Names Based on Reference Frame

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Scenario: Pointing information comes in different coordinate systems

    # If pointing is in ICRS (RA/Dec):
    daq.add_daq_metadata({
        "reference_frame": "ICRS",
        "ra": 123.456,
        "dec": 67.890
    })

    # If pointing changes to Alt/Az:
    daq.add_daq_metadata({
        "reference_frame": "AltAz",
        "altitude": 45.0,
        "azimuth": 180.0,
    })

    # If pointing is in Galactic coordinates:
    daq.add_daq_metadata({
        "reference_frame": "Galactic",
        "galactic_longitude": 30.0,
        "galactic_latitude": -15.0
    })

Example 3: Update Only Future Partitions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Add metadata that should only go in new files, not existing ones
    result = daq.add_daq_metadata(
        metadata={"processing_note": "Calibration applied"},
        update_existing=False  # Don't modify existing files
    )

Example 4: Update Specific Consumers Only
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ska_low_mccs_daq.pydaq.daq_receiver_interface import DaqModes

    # Add beam-specific pointing to beam data files only
    daq.add_daq_metadata(
        metadata={
            "beam_pointing_ra": 45.0,
            "beam_pointing_dec": -30.0,
            "beam_id": 0
        },
        consumer_modes=[DaqModes.BEAM_DATA]
    )

Example 5: Adding Multiple Types of Metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Add observation context
    daq.add_daq_metadata({
        "target_name": "PKS 1934-638",
        "target_type": "calibrator",
        "observation_mode": "tracking"
    })

    # Add environmental conditions
    daq.add_daq_metadata({
        "weather_temperature_c": 22.5,
        "weather_humidity_percent": 45,
        "weather_wind_speed_ms": 3.2
    })

    # Add processing information
    daq.add_daq_metadata({
        "rfi_flagging_enabled": True,
        "calibration_solution_applied": "20260109_solution.h5"
    })

Example 6: Error Handling
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    results = daq.add_daq_metadata({
        "reference_frame": "ICRS",
        "ra": 123.456,
        "dec": 67.890
    })

    # Check for errors
    for mode, result in results.items():
        if result["errors"]:
            print(f"Errors updating {mode}:")
            for error in result["errors"]:
                print(f"  - {error}")
        else:
            print(f"{mode}: Successfully updated {result['updated_partitions']} partition(s)")

How It Works
------------

File Structure
~~~~~~~~~~~~~~

Metadata is stored in the HDF5 file's ``observation_info`` group as attributes::

    # HDF5 structure
    /
    ├── root (dataset with standard metadata attributes)
    ├── observation_info (group)
    │   ├── @reference_frame = "ICRS"
    │   ├── @ra = 123.456
    │   ├── @dec = 67.890
    │   ├── @target_name = "PKS 1934-638"
    │   └── ... (any other metadata)
    ├── polarization_0/
    ├── polarization_1/
    └── sample_timestamps/

File Partitions
~~~~~~~~~~~~~~~

Large acquisitions may span multiple file partitions. By default, ``add_daq_metadata()`` updates:

1. All existing partitions (if ``update_existing=True``)
2. Any future partitions created after the call

This ensures consistent metadata across all files from an observation.

Timing Considerations
~~~~~~~~~~~~~~~~~~~~~

* **Before consumer starts**: Use the ``observation_metadata`` parameter in configuration
* **After consumer starts**: Use ``add_daq_metadata()`` function
* **During long acquisitions**: Call ``add_daq_metadata()`` whenever new information becomes available

Implementation Details
----------------------

The functionality is implemented across three layers:

1. **AAVSFileManager.add_metadata()** (``aavs_file.py``): Base implementation that handles HDF5 file updates
2. **DaqReceiver.add_daq_metadata()** (``daq_receiver_interface.py``): Interface class method
3. **add_daq_metadata()** (``daq_receiver.py``): Legacy interface function

All three support the same functionality and API.

Reading Metadata
----------------

Metadata can be read from HDF5 files using standard h5py:

.. code-block:: python

    import h5py

    with h5py.File("beam_data_file.hdf5", "r") as f:
        if "observation_info" in f:
            obs_info = f["observation_info"]
            reference_frame = obs_info.attrs.get("reference_frame")
            ra = obs_info.attrs.get("ra")
            dec = obs_info.attrs.get("dec")
            print(f"Pointing: {reference_frame} {ra}, {dec}")

Or using the existing ``get_metadata()`` method:

.. code-block:: python

    from ska_low_mccs_daq.pydaq.persisters.beam import BeamFormatFileManager

    file_mgr = BeamFormatFileManager(root_path="/path/to/data")
    metadata = file_mgr.get_metadata(timestamp=timestamp, tile_id=tile_id)

    if "observation_info" in metadata:
        print(f"Reference frame: {metadata['observation_info']['reference_frame']}")
        print(f"RA: {metadata['observation_info']['ra']}")
        print(f"Dec: {metadata['observation_info']['dec']}")

Best Practices
--------------

1. **Use descriptive keys**: Use clear, self-documenting key names (e.g., ``"ra"`` not ``"r"``)
2. **Include units**: Consider including units in the key name (e.g., ``"temperature_c"``, ``"wind_speed_ms"``)
3. **Use standard types**: Stick to types supported by HDF5 attributes (strings, numbers, small arrays)
4. **Add context**: Include reference frame, coordinate system, or other context with coordinate values
5. **Handle updates gracefully**: Check the return value for errors and handle them appropriately
6. **Document conventions**: Document your metadata field conventions for downstream users

Migration from observation_metadata
------------------------------------

Before (Limited Flexibility)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    config = {
        "observation_metadata": {
            "software_version": "1.2.3",
            "description": "Test observation"
        }
    }
    daq.populate_configuration(config)
    daq.start_beam_data_consumer()

    # Problem: Can't add pointing info after this point!

After (Full Flexibility)
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Initial metadata still works the same way
    config = {
        "observation_metadata": {
            "software_version": "1.2.3",
            "description": "Test observation"
        }
    }
    daq.populate_configuration(config)
    daq.start_beam_data_consumer()

    # Now you can add more metadata anytime!
    daq.add_daq_metadata({
        "reference_frame": "ICRS",
        "ra": 123.456,
        "dec": 67.890
    })

Notes
-----

* Metadata updates to existing files use ``r+`` mode and proper file locking
* Updates to closed/finalized files are supported as long as the files exist
* The ``observation_metadata`` configuration is still supported and will be merged with dynamically added metadata
* Metadata is persisted immediately - no explicit flush/save is required

