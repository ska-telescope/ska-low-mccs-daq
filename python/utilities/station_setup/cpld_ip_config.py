import sys
from optparse import OptionParser
from netifaces import AF_INET
import netifaces as ni
import socket
import array
from struct import *
import time
import functools


"""!@package rmp UDP socket management and RMP packet encoding/decoding
 
This package provides functions for network initializing and basic 32 bit read/write
operations on the network attached device using RMP protocol. This is rough and minimal code
not exploiting all the RMP protocol features.     
"""



class rmpNetwork():
    def __init__(self, this_ip, fpga_ip, udp_port, timeout):
        """!@brief Initialize the network

        It Opens the sockets and sets specific options as socket receive time-out and buffer size.

        @param this_ip  -- str -- Host machine IP address
        @param fpga_ip  -- str -- Network attached device IP address
        @param udp_port -- int -- UDP port
        @param timeout  -- int -- Receive Socket time-out in seconds

        Returns -- int -- socket handle
        """
        self.sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)  # Internet # UDP

        self.sock.settimeout(1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        if fpga_ip == "255.255.255.255":
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind((this_ip, 0))
        self.fpga_ip = fpga_ip
        self.this_ip = this_ip
        self.remote_udp_port = udp_port
        self.timeout = timeout
        self.psn = 0
        self.reliable = 0

    def CloseNetwork(self):
        """!@brief Close previously opened socket.
        """
        self.sock.close()
        return

    def recvfrom_to(self, buff):
        attempt = 0
        while (attempt < self.timeout or self.timeout == 0):
            try:
                return self.sock.recvfrom(10240)
            except:
                attempt += 1
        raise NameError("UDP timeout. No answer from remote end!")

    def wr32(self, add, dat, infinite_loop = False):
        """!@brief Write remote register at address add with dat.

        It transmits a write request to the remote device.

        @param add -- int -- 32 bits remote address
        @param dat -- int -- 32 bits write data
        """
        req_add = add
        for i in range(3):
            #try:

            self.psn += 1

            pkt = array.array('I')
            pkt.append(self.psn)  # psn
            pkt.append(2)  # opcode
            if type(dat) == list:
                pkt.append(len(dat))  # noo
            else:
                pkt.append(1)  # noo
            pkt.append(req_add)  # sa
            if type(dat) == list:
                for d in dat:
                    pkt.append(d)
            else:
                pkt.append(dat)  # dat

            self.sock.sendto(bytes(pkt.tostring()), (self.fpga_ip, self.remote_udp_port))
            while infinite_loop:
                self.sock.sendto(bytes(pkt.tostring()), (self.fpga_ip, self.remote_udp_port))
            data, addr = self.recvfrom_to(10240)

            data = bytes(data)

            psn = unpack('I', data[0:4])[0]
            add = unpack('I', data[4:8])[0]

            if psn == self.psn and add == req_add:
                return
            elif psn != self.psn:
                print
                print("Failed UCP write, received wrong PSN ...")
                print("Received: " + str(psn))
                print("Expected: " + str(self.psn))
                print("Retrying...")
            elif add != req_add:
                print
                print("Failed UCP write, error received ...")
                print("Requested Add: " + hex(req_add))
                print("Received Add: " + hex(add))
                print("Retrying...")
                self.socket_flush()
            # except:
                # if self.reliable == 1:
                    # print
                    # print("Failed UCP write:")
                    # #print "Received: " + str(psn)
                    # #print "Expected: " + str(self.psn)
                    # print("Requested Add: " + hex(req_add))
                    # #print "Received Add: " + hex(add)
                    # print("Retrying...")
                    # pass
                # else:
                    # print("Failed UCP write. Exiting ...")
                    # sys.exit(-1)


            print("Getting Last Executed PSN...")
            last_psn = self.rd32(0x30000004)
            print("Getting Last Executed PSN..." + str(last_psn))
            if last_psn == self.psn:
                return
            else:
                pass

        print
        print("UCP write error")
        print("Requested Add: " + hex(req_add))
        print("Received Add: " + hex(add))
        exit(-1)


    def rd32(self, add, n=1):
        """!@brief Read remote register at address add.

        It transmits a read request and waits for a read response from the remote device.
        Once the response is received it extracts relevant data from a specific offset within the
        UDP payload and returns it. In case no response is received from the remote device
        a socket time-out occurs.

        @param add -- int -- 32 bits remote address

        Returns -- int -- read data
        """
        req_add = add
        for i in range(3):

            self.psn += 1

            try:
                pkt = array.array('I')
                pkt.append(self.psn)    # psn
                pkt.append(1)           # opcode
                pkt.append(n)           # noo
                pkt.append(req_add)     # sa

                self.sock.sendto(bytes(pkt.tostring()), (self.fpga_ip, self.remote_udp_port))

                data, addr = self.recvfrom_to(10240)

                data = bytes(data)

                psn = unpack('I', data[0:4])[0]
                add = unpack('I', data[4:8])[0]

                if psn == self.psn and add == req_add:
                    dat = unpack('I' * n, data[8:])
                    dat_list = []
                    for k in range(n):
                        dat_list.append(dat[k])
                    if n == 1:
                        return dat_list[0]
                    else:
                        return dat_list
                else:
                    print
                    print("Failed UCP read, received wrong PSN or error detected ...")
                    print("Received: " + str(psn))
                    print("Expected: " + str(self.psn))
                    print("Requested Add: " + hex(req_add))
                    print("Received Add: " + hex(add))
                    print("Retrying...")
                    self.socket_flush()

            except:
                if self.reliable == 1:
                    print("Failed UCP read, retrying ...")
                else:
                    print("Failed UCP read, exiting ...")
                    sys.exit(-1)

        print
        print("UCP read error")
        print("Requested Add: " + hex(req_add))
        #print "Received Add: " + hex(add)
        exit(-1)

    def socket_flush(self):
        print("Flushing UCP socket...")
        self.sock.close()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet # UDP

        self.sock.settimeout(1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        if self.fpga_ip == "255.255.255.255":
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind((self.this_ip, 0))
        
class Eeprom():
    def __init__(self, rmp):
        self.rmp = rmp
        
    def eep_rd8(self, offset):
        ba = 0x40000000
        add = 0xA0 >> 1
        nof_rd_byte = 1
        nof_wr_byte = 1
        cmd = (nof_rd_byte << 12) + (nof_wr_byte << 8) + add

        self.rmp.wr32(ba + 0x4, (offset & 0xFF))
        self.rmp.wr32(ba + 0x0, cmd)
        while(self.rmp.rd32(ba + 0xC) != 0):
            pass
        return self.rmp.rd32(ba + 0x8)

    def eep_wr8(self, offset, data):
        ba = 0x40000000
        add = 0xA0 >> 1
        nof_rd_byte = 0
        nof_wr_byte = 2
        cmd = (nof_rd_byte << 12) + (nof_wr_byte << 8) + add

        while (True):
            self.rmp.wr32(ba + 0x4, ((data & 0xFF) << 8) + (offset & 0xFF))
            self.rmp.wr32(ba + 0x0, cmd)
            while (True):
                rd = self.rmp.rd32(ba + 0xC)
                if rd == 2:
                    time.sleep(0.1)
                    break
                elif rd == 0:
                    return
                else:
                    time.sleep(0.1)

    def eep_rd32(self, offset, data):
        rd = 0
        for n in range(4):
            rd = rd << 8
            rd = rd | self.eep_rd8(offset+n)
        return rd

    def eep_wr32(self, offset, data):
        for n in range(4):
            self.eep_wr8(offset+n, (data >> 8*(3-n)) & 0xFF)
        return

def i2c_set_passwd(inst):
    rd = inst.rd32(0x40000020)
    inst.wr32(0x4000003C, rd)
    rd = inst.rd32(0x40000024)
    inst.wr32(0x40000038, rd)

    rd = inst.rd32(0x4000003C)
    if rd & 0x10000 != 0:
        print("I2C password accepted!")
    else:
        print("I2C password not accepted!")
        exit(-1)

def i2c_remove_passwd(inst):
    inst.wr32(0x4000003C, 0)
    inst.wr32(0x40000038, 0)

if __name__ == "__main__":

    parser = OptionParser()
    parser.add_option("--ip",
                        dest="ip",
                        default="10.0.10.2",
                        help="TPM IP Address [default: 10.0.10.2]")
    parser.add_option("--netmask",
                        dest="netmask",
                        default="255.255.255.0",
                        help="TPM IP Netmask [default: 255.255.255.0]")
    parser.add_option("--gateway",
                      dest="gateway",
                      default="10.0.10.254",
                      help="TPM IP Gateway [default: 10.0.10.254]")
    parser.add_option("-p", "--udp_port",
                        dest="udp_port",
                        default="10000",
                        help="TPM UCP UDP port [default: 10000]")
    parser.add_option("--eep",
                      action="store_true",
                      dest="eep",
                      default=False,
                      help="Store network configuration in TPM EEPROM [default: False]")
    parser.add_option("--force_reset",
                      action="store_true",
                      dest="force_reset",
                      default=False,
                      help="Force reset of all boards connected to selected NIC [default: False]")

    (options, args) = parser.parse_args()

    print
    print("""    -----------------------------------------------------------------------
    -- WARNING! This script sets the specified network configuration to all
    -- TPM boards in the local network! Make sure to have a direct cable
    -- connection to the board you want to set!
    -----------------------------------------------------------------------""")
    print

    if raw_input("Press Y to continue, any other key to exit. ") != "Y":
        exit (0)
    print
    print("The new IP configuration on the TPM board will be:")
    print("IP:      " + options.ip)
    print("Netmask: " + options.netmask)
    print("Gateway: " + options.gateway)
    print
    print("List of available IP addresses:")
    print
    idx = 0
    ips = []
    for intf in ni.interfaces():
        try:
            if ni.ifaddresses(intf)[AF_INET][0]['addr'] != "127.0.0.1":
                print("[" + str(idx) + "] " + ni.ifaddresses(intf)[AF_INET][0]['addr'])
                ips.append(ni.ifaddresses(intf)[AF_INET][0]['addr'])
                idx += 1
        except:
            pass

    print
    idx = input("Select the IP address, this selects the output interface of broadcast UCP packets. ")
    try:
        idx = int(idx)
    except:
        print("What are you doing? You have to input a number!")
        sys.exit(1)
    if not idx in range(len(ips)):
        print("The specified interface doesn't exist!")
    else:
        print("Selected local interface IP: " + ips[idx])
    this_ip = ips[idx]
    inst = rmpNetwork(this_ip=this_ip, fpga_ip="255.255.255.255", udp_port=int(options.udp_port), timeout=5)
    eep = Eeprom(inst)

    ip2int = lambda ip: functools.reduce(lambda a, b: (a << 8) + b, map(int, ip.split('.')), 0)

    if options.force_reset:
        while True:
            inst.wr32(0x30000008,0x40,True)

    print("Setting TPM IP configuration. Address: %s, netmask: %s, gateway: %s" % (options.ip, options.netmask, options.gateway))
    inst.wr32(0x40000028, [ip2int(options.ip), ip2int(options.netmask), ip2int(options.gateway)])

    if options.eep:
        print("Writing IP configuration to EEPROM...")
        #storing network configuration in EEPROM

        i2c_set_passwd(inst)
        eep.eep_wr32(0x0, ip2int(options.ip))
        i2c_remove_passwd(inst)

        i2c_set_passwd(inst)
        eep.eep_wr32(0x4, ip2int(options.netmask))
        i2c_remove_passwd(inst)

        i2c_set_passwd(inst)
        eep.eep_wr32(0x8, ip2int(options.gateway))
        i2c_remove_passwd(inst)

        #read configuration from EEPROM and set volatile registers
        inst.wr32(0x40000018,1)
    print("Done!")

inst.CloseNetwork()


