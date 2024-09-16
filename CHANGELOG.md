# Version History

## unreleased

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
