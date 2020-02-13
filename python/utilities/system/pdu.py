#! /usr/bin/python

from pysnmp.entity.rfc3413.oneliner import cmdgen
from pysnmp.proto import rfc1902
import logging

class PDU(object):
    """ Class for interacting with PDU """

    def __init__(self, ip, port=161):
        """ Class constructor  """
        self._nof_ports = 12
        self._port = port
        self._ip = ip

        # Create device variables dictionary and populate it
        self._device_variables = {}
        self._populate_device_varaibles()

        # Check connection
        self.port_info(0, 'name')

    def port_info(self, port, field):
        """ Get port information """
        if port >= self._nof_ports:
            logging.error("PDU: Port %d does not exist" % port)
            return

        if field == "enabled":
            return True if self['outputEnable'][port] == 1 else False
        elif field == "name":
            return self['outputName'][port]
        elif field == "current":
            return self['outputCurrent'][port]
        else:
            logging.error("PDU: Field must be name, enabled or current")
            return

    def disable_port(self, port):
        """ Disable a port on the PDU """
        self._set_command("%s.%d" % (self._device_variables['outputEnable'][0], port), 2)

    def enable_port(self, port):
        """ Enable a port on the PDU """
        self._set_command("%s.%d" % (self._device_variables['outputEnable'][0], port), 1)

    def system_voltage(self):
        """ Get system current """
        return self['systemVoltage']

    def system_current(self):
        """ Get system current """
        return self['systemCurrent']

    def _get_command(self, variable):
        """ Issue SNMP get command """

        # Issue SNMP BULK GET command to retrieve variable
        cmdGen = cmdgen.CommandGenerator()
        error_indication, error_status, error_index, var_bind_table = cmdGen.bulkCmd(
            cmdgen.CommunityData('public'),
            cmdgen.UdpTransportTarget((self._ip, self._port)), 0, 25,
            str(variable))

        # Check if an error occured
        if error_indication:
            logging.error("PDU: %s" % error_indication)
            return None
        else:
            if error_status:
                logging.error("PDU: %s at %s" % (error_status.prettyPrint(),
                              error_indication and var_bind_table[-1][int(error_index)-1] or '?'))
                return None
            else:
                results = []
                for var_bind_table_row in var_bind_table:
                    for name, val in var_bind_table_row:
                        results.append(val.prettyPrint())
                return results

    def _set_command(self, variable, value):
        """ Issue SNMP set command """

        # Issue SNMP BULK GET command to retrieve variable
        cmdGen = cmdgen.CommandGenerator()

        error_indication, error_status, error_index, var_binds = cmdGen.setCmd(
            cmdgen.CommunityData('write', mpModel=0),
            cmdgen.UdpTransportTarget(((self._ip, self._port))),
            (variable, rfc1902.Integer(value))
        )

        # Check if an error occurred
        if error_indication:
            logging.error("PDU: %s" % error_indication)
        else:
            if error_status:
                logging.error("PDU: %s at %s" % (error_status.prettyPrint(),
                              error_indication and var_binds[int(error_index)-1] or '?'))

    def _populate_device_varaibles(self):
        """ Populate device varaibles """

        self._device_variables['sysDescr'] = ('1.3.6.1.2.1.1.1', 'r', 'str')
        self._device_variables['sysObjectID'] = ('1.3.6.1.2.1.1.2', 'r', 'object')
        self._device_variables['sysUpTime'] = ('1.3.6.1.2.1.1.3', 'r', 'time')
        self._device_variables['sysContact'] = ('1.3.6.1.2.1.1.4', 'r', 'str')
        self._device_variables['sysName'] = ('1.3.6.1.2.1.1.5', 'r', 'str')
        self._device_variables['sysLocation'] = ('1.3.6.1.2.1.1.6', 'r', 'str')
        self._device_variables['sysServices'] = ('1.3.6.1.2.1.1.7', 'r', 'int')

        self._device_variables['deviceModel'] = ('1.3.6.1.4.1.39145.10.1', 'r', 'str')
        self._device_variables['deviceName'] = ('1.3.6.1.4.1.39145.10.2', 'r', 'str')
        self._device_variables['deviceHardware'] = ('1.3.6.1.4.1.39145.10.3', 'r', 'int')
        self._device_variables['deviceFirmware'] = ('1.3.6.1.4.1.39145.10.4', 'r', 'str')
        self._device_variables['deviceMacAddress'] = ('1.3.6.1.4.1.39145.10.5', 'r', 'str')
        self._device_variables['systemVoltage'] = ('1.3.6.1.4.1.39145.10.6', 'r', 'float')
        self._device_variables['systemCurrent'] = ('1.3.6.1.4.1.39145.10.7', 'r', 'float')

        self._device_variables['outputNumber'] = ('1.3.6.1.4.1.39145.10.8.1.1', 'r', 'int')
        self._device_variables['outputName'] = ('1.3.6.1.4.1.39145.10.8.1.2', 'r', 'str')
        self._device_variables['outputCurrent'] = ('1.3.6.1.4.1.39145.10.8.1.3', 'r', 'float')
        self._device_variables['outputFuseStatus'] = ('1.3.6.1.4.1.39145.10.8.1.4', 'r', 'int')
        self._device_variables['outputEnable'] = ('1.3.6.1.4.1.39145.10.8.1.5', 'rw', 'int')

        self._device_variables['alarmNumber'] = ('1.3.6.1.4.1.39145.10.9.1.1', 'r', 'int')
        self._device_variables['alarmName'] = ('1.3.6.1.4.1.39145.10.9.1.2', 'r', 'str')
        self._device_variables['alarmStatus'] = ('1.3.6.1.4.1.39145.10.9.1.3', 'r', 'int')

        self._device_variables['busNumber'] = ('1.3.6.1.4.1.39145.10.10.1.1', 'r', 'int')
        self._device_variables['busName'] = ('1.3.6.1.4.1.39145.10.10.1.2', 'r', 'str')
        self._device_variables['busVoltage'] = ('1.3.6.1.4.1.39145.10.10.1.3', 'r', 'str')
        self._device_variables['busCurrent'] = ('1.3.6.1.4.1.39145.10.10.1.4', 'r', 'str')

    def __getitem__(self, key):
        """ Get value for a particular variables """
        if key not in self._device_variables.keys():
            raise ValueError("Variable %s does not exist" % key)

        vals = self._get_command(self._device_variables[key][0])
        if self._device_variables[key][2] == 'int':
            result = [int(x) for x in vals]
        elif self._device_variables[key][2] == 'float':
            result = [float(x) for x in vals]
        else:
            result = vals

        return result if len(result) > 1 else result[0]


# Script entry point
if __name__ == "__main__":

    def extract_values(values):
        """ Extract values from string representation of list
        :param values: String representation of values
        :return: List of values
        """
        # Return list
        converted = []
        for item in values.split(","):
            # Check if item contains a semi-colon
            if item.find(":") > 0:
                index = item.find(":")
                lower = item[:index]
                upper = item[index + 1:]
                converted.extend(range(int(lower), int(upper)))
            else:
                converted.append(int(item))
        return converted

    # Use OptionParse to get command-line arguments
    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %pdu [options]")
    parser.add_option("", "--ip", action="store", dest="ip",
                      default="", help="PDU IP")
    parser.add_option("", "--ports", action="store", dest="ports",
                      type="string", default="1:13", help="PDU ports (default: all)")
    parser.add_option("", "--action", action="store", dest="action",
                      default="info", help="Action tp be performed (info | switch_on | switch_off | reset")

    (config, args) = parser.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.DEBUG)
    str_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    from sys import stdout

    ch = logging.StreamHandler(stdout)
    ch.setFormatter(str_format)
    log.addHandler(ch)

    # Sanity checks
    if config.ip == "":
        logging.error("An IP must be specified")
        exit(-1)

    if config.action not in ["info", "switch_on", "switch_off", "reset"]:
        logging.error("Invalid action {}. Permitted: info | switch_on | switch_off".format(config.action))
        exit(-1)

    # Create port list
    config.ports = extract_values(config.ports)
    config.ports = [port - 1 for port in config.ports]
    for port in config.ports:
        if port < 0 or port > 11:
            logging.error("Invalid port {}".format(port))
            exit(-1)

    # Connect to PDU
    try:
        pdu = PDU(config.ip)
    except Exception as e:
        logging.error("Could not connect to PDU with IP {} [{}]".format(config.ip, e))
        exit(-1)

    import pprint

    # Check what action needs to be performed
    if config.action == "info":
        for port in config.ports:
            print "\nInfo for port {}".format(port + 1)
            print "     Name: {}".format(pdu.port_info(port, 'name'))
            print "  Enabled: {}".format(pdu.port_info(port, 'enabled'))
            print "  Current: {}".format(pdu.port_info(port, 'current')) 
            
    elif config.action == "switch_on":
        for port in config.ports:
            logging.info("Switching port {} on".format(port + 1))
            pdu.enable_port(port)
            logging.info("Switched port {} on".format(port + 1))
    elif config.action == "switch_off":
        for port in config.ports:
            logging.info("Switching port {} off".format(port + 1))
            pdu.disable_port(port)
            logging.info("Switched port {} off".format(port + 1))
    else:
        for port in config.ports:
            logging.info("Resetting port {}".format(port + 1))
            pdu.disable_port(port)
            pdu.enable_port(port)
            logging.info("Reset port {}".format(port + 1))
