import subprocess
import os


switch_ip_list = ["10.0.10.121", "10.0.10.122", "10.0.10.123", "10.0.10.124", "10.0.10.125", "10.0.10.126", "10.0.10.127"]
username = "admin"

for i in range(len(switch_ip_list)):

    cmd = ""
    cmd += '\\\"' + "reload halt" + '\\\" '
    
    cmd = "/usr/bin/sshpass -p admin ssh " + username + "@" + switch_ip_list[i] + " cli  \\\"enable\\\" \\\"configure terminal\\\"  " + cmd
    print cmd
   
    os.system(cmd)

