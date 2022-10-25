from __future__ import annotations

import pytest
import json
from pytest_bdd import given, scenarios ,parsers, then, when
from ska_low_mccs_daq.daq_receiver import MccsDaqReceiver
from ska_low_mccs_common import MccsDeviceProxy
from ska_low_mccs_common.testing.tango_harness import DevicesToLoadType

@pytest.fixture(scope="module")
def devices_to_load() -> DevicesToLoadType:
    """
    Fixture that specifies the devices to be loaded for testing.

    Here we specify that we want a controller-only deployment and provide a custom chart.

    :return: specification of the devices to be loaded
    """
    return {
        "path": "charts/ska-low-mccs-daq/data/configuration.json",
        "package": "ska_low_mccs_daq",
        "devices": [
            {"name": "daqreceiver_001", "proxy": MccsDeviceProxy},
        ],
    }

EXTRA_TYPES = {
    'Dict':str,
}

scenarios("daq_configuration.feature")

@given("A MccsDaqReceiver is available", target_fixture="daq_receiver_bdd")
def daq_receiver_bdd(daq_receiver: MccsDeviceProxy) -> MccsDeviceProxy:
    """
    Return a DeviceProxy to an instance of MccsDaqReceiver.

    :param daq_receiver: The daq_receiver fixture to use.

    :return: A MccsDeviceProxy instance to MccsDaqReceiver stored in the target_fixture `daq_receiver_bdd`.
    """
    return daq_receiver

@when(parsers.cfparse('We pass a {configuration:Dict} to the MccsDaqReceiver', extra_types = EXTRA_TYPES))
def daq_fed_configuration_file(daq_receiver_bdd, configuration):
    """
    Feed the configuration into the daq_receiver, this expects a string representation of a dictionary.
    
    """
    #MccsDaqReceiver expects a string as input, this will be a string representation of a dictionary.
    daq_receiver_bdd.Configure(configuration)

    

@then(parsers.cfparse('The DAQ_reciever interface has that {configuration:Dict}', extra_types = EXTRA_TYPES))
def assert_daq_instance_configuration(daq_receiver_bdd, configuration):
    """
    Here we need to check whether the daq_instance has the same configuration that we sent to the daq_receiver
    notes: we may only send a subset of the configuration to the DaqInstance.
    - The DaqInstance has some type casting therefore this is performed in the test (not ideal as means the test is duplicating code in the daq_receiver_interface, 
    could we assume the populate_configuration is passed the correct types? (type check before we call this?))
    - There are items in the configeration that can be overriden internally these are edge cases tested "
    - We have assumed that the 'observation_metadata' configuration item is not passed as is overriden entirely in the daq_receiver_interface so a test wouldn't make sense.

    """
    #first convert to a dictionary
    configuration = json.loads(configuration)

    #The daq_receiver_interface.py performes type casting in some cases, this is mimicked here (not ideal) for testing purposes.
    try:
        if 'receiver_ports' in configuration and configuration['receiver_ports'] is not list:
            value = [int(x) for x in value.split(',')]
    except:
        raise ValueError("values entered as receiver_ports invalid!")

    #This is a edge case scenario with another test
    if 'receiver_ip' in configuration and configuration['receiver_ip' ] == "":
        raise ValueError("There is a seperate test scenario for this 'Check receiver_ip is assigned address if not defined'")

    if 'observation_metadata' in configuration:
        raise ValueError("This is not a parameter tested here")
    
    assert configuration.items() <= daq_receiver_bdd.component_manager.daq_instance.get_configuration().items()
