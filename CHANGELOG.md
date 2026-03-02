# Version History

## 5.3.3

* [JANUS-343] Fix segmentation faults and file descriptor errors in Raw Station Beam DAQ mode

## 5.3.2

* [SKB-1196] Stop the bandpasses falling over on reception of a partially populated bandpass.

## 5.3.1

* [SKB-1048] Update DAQ core ref for fix to lost_pushes reporting and segfaults around Stop()

## 5.3.0

* [JANUS-342] Add support for non default port to station beam DAQ mode
* [THORN-399] Upgrade ska-low-mccs-common to improve Tango error event log messages, which now include device and attribute name.

## 5.2.2

* [THORN-398] Fix bandpasses for a fully populated station.

## 5.2.1

* [THORN-387] Bandpasses are now pushed with the exact same time for archive and change events. Different attributes will still have slightly different times.

## 5.2.0

* [SKB-1171] Devices which fail to connect to their parent device for adminmode inheritance will now retry forever, however the device will go to alarm if the connection has been failing for the timeout length, the device will go to ALARM. The timeout length defaults to 120s however is configurable through the ParentConnectionTimeout device property.

## 5.1.0

* [LOW-1956] Update ska-tango-devices chart dependency to v0.14.0
* [THORN-380] Add raw{x,y}PolBandpass attributes for pushing uint16 bandpasses before decibelisation
* [SKB-1162] Refactored the bandpass monitor to no longer make/delete files which was the source of the memory leak.

## 5.0.1

* [JANUS-328] Support for Python3.12. Removed `__future__`, `future` and `past` imports which were required for Python2/3 intercompatibility, no longer necessary.

## 5.0.0

* [THORN-331] Daq.Stop() now correctly calls back with result= when done.
* Improvements to the continuous channel consumer by addressing floating-point precision loss and packet counter synchronisation issues, and upgraded memory allocation for better performance. This eliminates intermittent errors ("skipped packets") and ensures accurate data streaming, particularly over long observation periods.

## 4.5.0

* [SKB-1105] Removed code to reset the sampling time in the raw station beam mode which was causing incorrect timestamps in the DADA headers.
* [THORN-262] Add timeout to pytest configuration. This should be set to slightly less than the pipeline timeout so that test reports are generated before the job is killed.
* [SKB-1123] Fix TCC inversion of XY/YX stokes.
* [LOW-1804] Default MarkDone() tag to be a no-op.
* [SKB-1079] Cleanup. Ensure that we are not defining important cleanup information in init, this is executed after.

## 4.4.0

* [SKB-610] Add Station Name to hdf5 metadata. Add `StationName` and `StationId` properties to Daq to be set by templates. Update deploy submodule.

## 4.3.1

* [SKB-1090] Fixed issue related to buffer boundaries in the channelised continuous mode.
* [JANUS-257] Using the payload_length field from the header isntead of samples value for channelised metadata.

## 4.3.0

* [SPRTS-388] Update ringbuffer size for station beam data consumer.
* [THORN-247] Added a new correlator mode for the Tensor Core Correlator (<https://git.astron.nl/RD/tensor-core-correlator/-/tree/master>).
    It lives in a new DaqMode 'TC_CORRELATOR_DATA' and should be considered experimental for now.

## 4.2.0

* [JANUS-257] Fixed the order of fields in the AntennaBufferMetadata class to match with AntennaBuffer.h. Seperated the member variable nof_packets in ChaneelisedData.h from the
metadata field nof_packets. Added condition for calling back for only the tiles the DAQ has received data from for AntennaBuffer and Channelised modes.
* [THORN-259] Add attributes correlatorTimeUtil, relativeNofPacketsDiff, relativeNofSamplesDiff, lostPushRate for healthstatus calculation

## 4.1.2

* [JANUS-257] Fixed the type of subarray_id in the StationMetadata class to match with StationData.h
* [THORN-257] Added MarkDone() command
* [JANUS-273] Updated environment variable used in acquire_station_beam.cpp to align with other data modes
* [THORN-259] Implementation of alarms on Ringbuffer occupancy, which maps to healthstate via ADR-115.

## 4.1.1

* [JANUS-257] Deleted a space in a field name in BeamMetadata

## 4.1.0

* [JANUS-257] Added the SPEAD header metadata to the callbacks of RAW_DATA, BEAM_DATA, INTEGRATED_BEAM_DATA, STATION_BEAM_DATA, ANTENNA_BUFFER DAQ modes.
* [JANUS-257] Added channelised data SPEAD headers to callback as metadata.

## 4.0.0

* [THORN-172] The old two pod DAQ has been removed.

## 3.2.2

* [THORN-248] Update ska-low-mccs-common dependency.

## 3.2.1

* [LOW-1593] Eliminate dependency on bitnami images / charts

## 3.2.0

* [THORN-197] Add attributes nofPackets/bufferCount for raw station beam. Link up ringbufferOccupancy/lostPushes for raw station beam.

## 3.1.0

* [THORN-38] Added Raw station beam data consumer.
Known bug: If Daq is configured for a single channel and a channel > ~8 is chosen then a segfault is observed when receiving data. See `https://jira.skatelescope.org/browse/THORN-242`

## 3.0.2

* [SKB-996] Fix bug with x pol data in the station data consumer having a fake additional 1e-6 power values.
* [SKB-996] Fix bug with the bandpass DAQ loadbalancer not exposing port 4660 on UDP.

## 3.0.1

* [REL-2240] Moved back to STFC pipelines
* [THORN-235] Fix data callback attribute

## 3.0.0

* [SKB-490] Fix timestamps being all zeroes for integrated channel data by adding sampling time to ingest data call.
* [THORN-229] Fix StartBandpassMonitor internal command interface, reinstate necessary configuration checks.
* [THORN-196] Added attributes for the correlator mode: nofSamples, correlatorTimeTaken
* [THORN-203] The nofPackets attribute now works for integrated channel data.
* [THORN-178] Added attribute to expose aavsdaq library version
* [SKB-827] Fixed a memory leak in StationData.cpp. The DoubleBuffer was cleaning up the incorrect number of buffers.
* [SKB-827] Updated aavs-daq reference for fixes to the ringbuffer.
* [SPRTS-388] SIMD optimisations to station beam data mode to be more resiliant to bursty behaviour.
* [THORN-215] Add json validation to MccsDaq configure command.
* [THORN-180] Expose DaqStatus as attributes
* [THORN-233] Added documentation for new attributes
* [THORN-187] Added ringbuffer diagnostic attributes ringbufferOccupancy and lostPushes
* [THORN-185] Added interface monitoring points and station beam monitoring points

## 3.0.0-rc2

* [THORN-220] Add cleanup for component manager.

## 3.0.0-rc1

* [THORN-174] Update DaqComponentManager to talk to DaqReceiver. (DaqComponentManager -> DaqHandler -> DaqReceiver is now DaqComponentManager -> DaqRecevier)

## 2.1.0

* [THORN-217] Add method for fetching loadbalancer IP
* [THORN-170] Update Dockerfile to support a Tango device too. It remains backward compatible with the two-pod-daq.
* [THORN-215] Update configuration after writing.
* [THORN-171] Copy the DAQ tango device into ska-low-mccs-daq.

## 2.0.4

* [THORN-160] Re-add methods that were omitted during the repo reshuffle.

## 2.0.3

* [JANUS-153] Fix to typo in daq_receiver_interface

## 2.0.2

* [JANUS-146] Fix Error Message "AAVS_SOFTWARE_DIRECTORY not defined"

## 2.0.1

* [JANUS-142] Fixed imports in daq_plotter and daq_receiver required for CLI usage
* [SPRTS-260] Fixed issue with pydaq not locking hdf5 files introduced in bug fix AAVS-System release 2.1.4

## 2.0.0

* [THORN-110] Pull aavs-system code in to its new home. We now don't clone aavs-system and instead use the copied code when building the image. Changes should be transparent to users. Relax python version requirements.

## 1.0.2

* [THORN-97] Expose LoadBalancer IP through DaqStatus if loadbalancer is present

## 1.0.1

* [SKB-799] Pull fix in aavs system to DAQ

## 1.0.0

* [THORN-17] 1.0.0 release - all MCCS repos

## 0.10.0

* [THORN-12] Add methods/attributes to measure data rate over receiver interface.

## 0.9.2

* [SKB-705] DaqHandler to handle DAQ receiver restart gracefully while bandpass monitoring is active
* [THORN-35] Update CODEOWNERS.

## 0.9.1

* [SKB-610] Add StationID as a configuration option.

## 0.9.0

* [MCCS-2227] support SIGTERM in daq receivers so that Pods terminate gracefully
* [SKB-524] allow specifying memory limits for receivers
* [MCCS-2230] ensure that the receiver interface specified in environment variables is used by default
* [SKB-494] update aavs-system/pydaq to support the new SPEAD format

## 0.8.0

* [MCCS-2141] Update to ska-control-model 1.0.0

## 0.7.0

* [MCCS-2213] Reconfigure helmfile templates to pull configuration info from TelModel.
* [MCCS-2202] Allow to configure from an optional NAD.
* [MCCS-2191] Move static Daq properties from Tango device to backend.
* [SPRTS-224] Invert the interpretation of X and Y HDF5 file indices.
* [LOW-938] Add ska-low-deployment as `.deploy` submodule containing deployment templates.
* [MCCS-2189] Allow exposing Daq's data service as a LoadBalancer with external IP.
* [MCCS-2189] Deploy two daqs per station. One for calibration one for bandpasses.

## 0.6.2

* [MCCS-1883] Add bandpass monitor labels. Fix attribute size.
* [MCCS-1885] Introduce `cadence` as an argument to bandpass monitor.
* [MCCS-2046] Update Pyfabil and AAVS-System references.

## 0.6.1

* [MCCS-1940] Fix DAQ deployment bug

## 0.6.0

* [MCCS-1631] Add bandpass monitor.

## 0.5.0

* [LOW-580] Use a queue.SimpleQueue instead of a custom buffer
* [MCCS-1808] Propagate ADR-55 changes to daq-handler.
* [MCCS-1776] Add external daq instructions to ReadTheDocs.
* [MCCS-1706] Bug fix in json serialisation.
* [MCCS-1684] Remote platform specs

## 0.4.0

* [MCCS-1665, MCCS-1668] platform-dependent chart configurationrefactor
* [MCCS-1586] Allow the DaqHandler to expose received metadata
* [MCCS-1633, MCCS-1636] Docs theme updates
* [MCCS-1541, MCCS-1542] Correlator support
* [MCCS-1613] Add version logging to device init
* [MCCS-1355] Refactor to align with ska-tango-base ComponentManager
* [MCCS-1599, MCCS-1537, MCCS-1534, MCCS-1538, MCCS-1540] Refactor to move Tango device to ska-low-mccs-spshw, and use ska-low-mccs-daq-interface

## 0.3.0

* [MCCS-1510] chart rewrite with PVC support
* [MCCS-1502] Chart template fix
* [MCCS-1487] test harness
* [MCCS-1432] Add xray integration to mccs-daq repo
* [MCCS-1203] Proposed changes resulting from thin_slice_demo.
* [MCCS-1423] Update pyfabil and aavs-system version
* [MCCS-1347] Fix when DAQ connects to its DaqReceiver
* [MCCS-1310] dependency update

## 0.2.0

* MCCS-1326 Implement prototype gRPC solution for DAQ
* MCCS-1279 Pin Pyfabil and Daq versions
* MCCS-1194 Fix bug with DaqReceiver.Start
* MCCS-1083 Report Status of MccsDaqReceiver
* MCCS-1098 Add GetConfiguration command to DAQ

## 0.1.2

* update .gitlab-ci.yml

## 0.1.1

* MCCS-1177 add helm chart option

## 0.1.0

* LOW-379 Expose device configurations
* MCCS-1153 Add command to set default consumers to start.
* MCCS-1094 "Implement BDD test for DAQ configuration"
* MCCS-1152 Daq permissions workaround
* MCCS-1078 Move MccsDaqReceiver device into its own repo.

Initial release

* MCCS-1149 - initial creation
