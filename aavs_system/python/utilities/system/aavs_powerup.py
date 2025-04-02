#! /usr/bin/python

from time import sleep
import os

if __name__ == "__main__":

    os.system("dropbox start")

    print("Setting server network interfaces")
#    os.system("ifconfig eth3:2 down")
#    os.system("ifconfig eth3:1 down")
    os.system("ifconfig eth2 down")
    os.system("ifconfig eth1 down")
    os.system("ifconfig eth3 mtu 9000")
    os.system('sudo ethtool -G eth3 rx 8192')
    os.system("service dnsmasq restart")
    
    print("Enabling PSU output")
    os.system("python /opt/aavs/bin/psu.py -i aavs1-psu57.mwa128t.org on")
    os.system("python /opt/aavs/bin/psu.py -i aavs1-psu58.mwa128t.org on")
    os.system("python /opt/aavs/bin/psu.py -i aavs1-psu59.mwa128t.org on")
    # os.system("python psu.py -i aavs1-psu60.mwa128t.org off")
    
    sleep(10)
    print("Switching on TPMs")
    os.system("python /opt/aavs/bin/pdu.py --ip=pdu-1 --action=reset")
    os.system("python /opt/aavs/bin/pdu.py --ip=pdu-2 --action=reset")
    os.system("python /opt/aavs/bin/pdu.py --ip=10.0.10.113 --action=reset")
    # os.system("python pdu.py --ip=pdu-4 --action=reset")

    # Start Mongo database
    os.system("service mongod restart")
    
#    sleep(5)
#    print "Generating antenna spectra"
#    os.system("sudo -u aavs python /home/aavs/aavs-daq/python/standalone/monitor_spectra.py")
    
    



