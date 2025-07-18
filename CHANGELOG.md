# Version History

## Unreleased

* [THORN-196] Added attributes for the correlator mode: nofSamples, correlatorTimeTaken
* [THORN-203] The nofPackets attribute now works for integrated channel data.
* [THORN-178] Added attribute to expose aavsdaq library version

## 3.0.0-rc3

* [SKB-827] Fixed a memory leak in StationData.cpp. The DoubleBuffer was cleaning up the incorrect number of buffers.
* [SKB-827] Updated aavs-daq reference for fixes to the ringbuffer.
* [SPRTS-388] SIMD optimisations to station beam data mode to be more resiliant to bursty behaviour.
* [THORN-215] Add json validation to MccsDaq configure command.
* [THORN-180] Expose DaqStatus as attributes

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
