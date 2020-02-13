#! /usr/bin/python

import os

if __name__ == "__main__":


    print "Halting 40G switches"
    os.system("python switch_halt.py")

    print "Shutting down all TPMs" 
    os.system("pdu.py --ip=pdu-1 --action=switch_off")
    os.system("pdu.py --ip=pdu-2 --action=switch_off")
    os.system("pdu.py --ip=pdu-3 --action=switch_off")
    os.system("pdu.py --ip=pdu-4 --action=switch_off")

    print "Shutting down PSUs"
    os.system("python psu.py -i aavs1-psu57.mwa128t.org off")
    os.system("python psu.py -i aavs1-psu58.mwa128t.org off")
    os.system("python psu.py -i aavs1-psu59.mwa128t.org off")
    os.system("python psu.py -i aavs1-psu60.mwa128t.org off")

    print "Powering off server"
    os.system("poweroff")
