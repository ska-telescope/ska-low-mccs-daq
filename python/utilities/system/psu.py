from builtins import object
import sys
import socket
from optparse import OptionParser
import time


class Psu(object):
    def __init__(self, **kwargs):
        self.ip = kwargs.get('ip', None)
        self.port = kwargs.get('port', None)

    def connect(self):
        #create an INET, STREAMing socket
        try:
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except socket.error:
            print('Failed to create socket')
            return -1
        print('Socket Created')
        self.s.connect((self.ip, int(self.port)))
        self.s.setblocking(1)
        self.s.settimeout(2)
        print('Socket Connected to ' + self.ip + " using port " + self.port)
        return 0

    def send_cmd(self, cmd):
        try:
            # Set the whole string
            sent = self.s.send(cmd)
            l = len(cmd)
            time.sleep(1)
            if (sent != l):
                return -1
            else:
                return 0
        except socket.error:
            # Send failed
            print('Send failed')
            return -1

    # ###get_voltage
    # # this function read the voltage value of the selected channel
    # # @param[in] channel: power supply channel to be used
    # # @return res: voltage value
    # # @return opstat:operation status, -1 failed res value not valid, 0 passed
    # def get_voltage(self, channel):
    #     if ((channel > 0) & (channel < self.channel)):
    #         cmd = "INST OUT" + str(channel) + "\n"
    #         if (self.send_cmd(cmd) != -1):
    #             time.sleep(0.5)
    #             cmd = "VOLT?\n"
    #             if (self.send_cmd(cmd) != -1):
    #                 time.sleep(0.5)
    #                 res = self.s.recv(256)
    #                 f = float(res)
    #                 opstat = 0
    #             else:
    #                 f = -1
    #                 opstat = -1
    #         else:
    #             f = -1
    #             opstat = -1
    #     else:
    #         f = -1
    #         opstat = -2
    #     return f, opstat
    #     ###get_voltage_measure
    #
    # # this function read the voltage value of the selected channel
    # # @param[in] channel: power supply channel to be used
    # # @return res: voltage value
    # # @return opstat:operation status, -1 failed res value not valid, 0 passed
    # def get_voltage_measure(self, channel):
    #     if ((channel > 0) & (channel < self.channel)):
    #         cmd = "INST OUT" + str(channel) + "\n"
    #         if (self.send_cmd(cmd) != -1):
    #             time.sleep(0.5)
    #             cmd = "VOLT?\n"
    #             if (self.send_cmd(cmd) != -1):
    #                 time.sleep(0.5)
    #                 res = self.s.recv(256)
    #                 f = float(res)
    #                 opstat = 0
    #             else:
    #                 f = -1
    #                 opstat = -1
    #         else:
    #             f = -1
    #             opstat = -1
    #     else:
    #         f = -1
    #         opstat = -2
    #     return f, opstat
    #     ###get_curr
    #
    # # this function read the current value of the selected channel
    # # @param[in] channel: power supply channel to be used
    # # @return res: current value
    # # @return opstat:operation status, -1 failed res value not valid, 0 passed
    # def get_current(self, channel):
    #     if ((channel > 0) & (channel < self.channel)):
    #         cmd = "INST OUT" + str(channel) + "\n"
    #         if (self.send_cmd(cmd) != -1):
    #             time.sleep(0.5)
    #             cmd = "CURR?\n"
    #             if (self.send_cmd(cmd) != -1):
    #                 time.sleep(0.5)
    #                 res = self.s.recv(256)
    #                 f = float(res)
    #                 opstat = 0
    #             else:
    #                 f = -1
    #                 opstat = -1
    #         else:
    #             f = -1
    #             opstat = -1
    #     else:
    #         f = -1
    #         opstat = -2
    #     return f, opstat
    #
    #     ###get_currrent_measure
    #
    # # this function measure the current value of the selected channel
    # # @param[in] channel: power supply channel to be used
    # # @return res: current value
    # # @return opstat:operation status, -1 failed res value not valid, 0 passed
    # def get_current_meas(self, channel):
    #     if ((channel > 0) & (channel < self.channel)):
    #         cmd = "INST OUT" + str(channel) + "\n"
    #         if (self.send_cmd(cmd) != -1):
    #             time.sleep(0.5)
    #             cmd = "MEAS:CURR?\n"
    #             if (self.send_cmd(cmd) != -1):
    #                 time.sleep(0.5)
    #                 res = self.s.recv(256)
    #                 f = float(res)
    #                 opstat = 0
    #             else:
    #                 f = -1
    #                 opstat = -1
    #         else:
    #             f = -1
    #             opstat = -1
    #     else:
    #         f = -1
    #         opstat = -2
    #     return f, opstat
    #
    #     ###set_curr
    #
    # # this function set the current value of the selected channel
    # # @param[in] channel: power supply channel to be used
    # # @return opstat:operation status, -1 failed cmd not send, -2 failed bad param, 0 passed
    # def set_current(self, channel, current):
    #     if ((channel > 0) & (channel < self.channel)):
    #         cmd = "INST OUT" + str(channel) + "\n"
    #         if (self.send_cmd(cmd) != -1):
    #             time.sleep(0.2)
    #             cmd = "CURR " + str(current) + "\n"
    #             o = self.send_cmd(cmd)
    #             time.sleep(0.2)
    #         else:
    #             return -1
    #     else:
    #         return -2
    #
    #         ###set_voltage
    #         # this function set the voltage value of the selected channel
    #         # @param[in] channel: power supply channel to be used
    #         # @return opstat:operation status, -1 failed cmd not send, -2 failed bad param, 0 passed
    #
    # def set_voltage(self, channel, voltage):
    #     if ((channel > 0) & (channel < self.channel)):
    #         cmd = "INST OUT" + str(channel) + "\n"
    #         if (self.send_cmd(cmd) != -1):
    #             time.sleep(0.2)
    #             cmd = "VOLT " + str(voltage) + "\n"
    #             o = self.send_cmd(cmd)
    #             time.sleep(0.2)
    #         else:
    #             return -1
    #     else:
    #         return -2
    #         ###output_on
    #         # this function enable the output of selected channel
    #         # @param[in] channel: power supply channel to be used
    #         # @return opstat:operation status, -1 failed cmd not send, -2 failed bad param, 0 passed
    #
    # def output_on(self, channel):
    #     if ((channel > 0) & (channel < self.channel)):
    #         cmd = "INST OUT" + str(channel) + "\n"
    #         if (self.send_cmd(cmd) != -1):
    #             time.sleep(0.2)
    #             cmd = "OUTP ON\n"
    #             o = self.send_cmd(cmd)
    #             time.sleep(0.2)
    #             return o
    #         else:
    #             return -1
    #     else:
    #         return -2
    #         ###output_off
    #         # this function disable the output of selected channel
    #         # @param[in] channel: power supply channel to be used
    #         # @return opstat:operation status, -1 failed cmd not send, -2 failed bad param, 0 passed
    #
    # def output_off(self, channel):
    #     if ((channel > 0) & (channel < self.channel)):
    #         cmd = "INST OUT" + str(channel) + "\n"
    #         if (self.send_cmd(cmd) != -1):
    #             time.sleep(0.2)
    #             cmd = "OUTP OFF\n"
    #             o = self.send_cmd(cmd)
    #             time.sleep(0.2)
    #             return o
    #         else:
    #             return -1
    #     else:
    #         return -2
    #         ###output_gen_on
    #         # this function enable the general output
    #         # @return opstat:operation status, -1 failed cmd not send, 0 passed
    #
    # def output_gen_on(self):
    #     cmd = "OUTP:GEN ON\n"
    #     o = self.send_cmd(cmd)
    #     time.sleep(0.2)
    #     return o

    def output_stat_on(self):
        cmd = "OUTP:STAT 1\n"
        o = self.send_cmd(cmd)
        time.sleep(0.2)
        return o
        ###output_gen_off

    def output_stat_off(self):
        cmd = "OUTP:STAT 0\n"
        o = self.send_cmd(cmd)
        time.sleep(0.2)
        return o
        ###output_gen_off

    # this function return the id informations of the device
    # @return opstat:operation status, -1 failed cmd not send, 0 passed
    def get_stat(self):
        cmd = "OUTP:STAT?\n"
        if (self.send_cmd(cmd) != -1):
            res = self.s.recv(256)
            opstat = 0
        else:
            res = -1
            opstat = -1
        return res, opstat

    # # this function disable the general output
    # # @return opstat:operation status, -1 failed cmd not send, 0 passed
    # def output_gen_off(self):
    #     cmd = "OUTP:GEN OFF\n"
    #     return self.send_cmd(cmd)
    #     ###get_id

    # # this function return the id informations of the device
    # # @return opstat:operation status, -1 failed cmd not send, 0 passed
    # def get_id(self):
    #     cmd = "*IDN?\n"
    #     if (self.send_cmd(cmd) != -1):
    #         res = self.s.recv(256)
    #         opstat = 0
    #     else:
    #         res = -1
    #         opstat = -1
    #     return res, opstat

    def get_state(self):
        cmd = "OUTPut:GENeral?\n"
        if (self.send_cmd(cmd) != -1):
            time.sleep(0.2)
            res = self.s.recv(256)
            opstat = 0
        else:
            res = -1
            opstat = -1
        return res, opstat

        ###disconnect

    # this function close the tcp connection with instruments
    def disconnect(self):
        self.s.close()


# INSTrument[:SELect] {OUTPut1|OUTPut2|OUTPut3|OUTPut4|OUT1|OUT2|OUT3|OUT4}
# INSTrument[:SELect]?
# INSTrument:NSELect {1|2|3|4}
# INSTrument:NSELect?

# [SOURce:]VOLTage[:LEVel][:IMMediate][:AMPLitude] {<voltage>| MIN | MAX}}
# [SOURce:]VOLTage[:LEVel][:IMMediate][:AMPLitude]? [MIN I MAX]
# [SOURce:]VOLTage[:LEVel][:IMMediate][:AMPLitude] {UP I DOWN}
# [SOURce:]VOLTage[:LEVel]:STEP[:INCRement) {<numeric value>| DEFault}
# [SOURce:]VOLTage[:LEVel]:STEP[:INCRement)? [Default)


# [SOURce:]CURRent[:LEVel][:IMMediate][:AMPLitude] {<current>| MIN | MAX}
# [SOURce:]CURRent[:LEVel][:IMMediate][:AMPLitude]? [MIN I MAX]
# [SOURce:]CURRent[:LEVel][:IMMediate][:AMPLitude] {UP I DOWN}
# [SOURce:]CURRent[:LEVel]:STEP[:INCRement) {<numeric value>| DEFault}
# [SOURce:]CURRent[:LEVel]:STEP[:INCRement)? [Default)

# OUTPut:SELect {OFF | ON | 0 | 1}
# OUTPut[:STATe] {OFF | ON | 0 | 1}
# OUTPut[:STATe]?
# OUTPut:GENeral {OFF | ON | 0 | 1}

# VOLTage:PROTection[:LEVel] {<voltage> | MIN | MAX }
# VOLTage:PROTection[:LEVel]? [MIN | MAX]
# VOLTage:PROTection:TRIPped?
# VOLTage:PROTection:CLEar
# VOLTage:PROTection:MODE {MEASured | PROTected}
# VOLTage:PROTection:MODE?

# MEASure[:SCALar]:CURRent [:DC]?
# MEASure[:SCALar][:VOLTage] [:DC]?

#PSU1: http://aavs1-psu57.mwa128t.org/
#PSU2: http://aavs1-psu58.mwa128t.org/
#PSU3: http://aavs1-psu59.mwa128t.org/
#PSU4: http://aavs1-psu60.mwa128t.org/





supported_cmd = ["on","off","read_all"]

if __name__ == "__main__":
    parser = OptionParser()

    parser.add_option("-i", "--ip",
                      dest="ip",
                      default="10.0.10.20",
                      help="Power Supply IP address")
    parser.add_option("-p", "--port",
                      dest="port",
                      default="8003",
                      help="Power supply SCPI TCP port")

    (options, args) = parser.parse_args()

    if args == []:
        print("Specify command!")
        print("Supported commands: ")
        print(supported_cmd)
        sys.exit(-1)

    cmd = args[0]

    if cmd not in supported_cmd:
        print("Command not supported.")
        print("Supported commands: ")
        print(supported_cmd)
        sys.exit(-1)
    else:
        psu_inst = Psu(ip=options.ip, port=options.port)
        psu_inst.connect()

        if cmd == "on":
            psu_inst.output_stat_on()
        if cmd == "off":
            psu_inst.output_stat_off()
        if cmd == "read_all":
            print(psu_inst.get_stat())
