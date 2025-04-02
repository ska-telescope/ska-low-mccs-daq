"""
Python script which is able to handle udp packets captured with wireshark that are emitted from the TPM antenna buffer.
The script retrieves the information included in the SPEAD header and the data for each antenna.

Constraints:
    - It only works with a *.pcapng file;
    - At the moment it only works for 2 antennas. The script needs minor changes 
      (some are already implemented) when 4 antennas will be supported;
    - It works only with SPEAD of the antenna buffer register described in mccs-731. 
      The script needs to be updated if the length of the SPEAD header is changed;

Input:
    - *.pcapng file;

Output:
    - A *.txt file for each antenna. The output file stores the H (first column) and V (second column) polarizations;
    - To get an output *.mat file, import the scipy.io library and uncomment lines from #134;

:example:
        >>> python3 antenna_buffer_datadump.py ../"pcapng file"
            
    -> write pcapng file name without extension. 
"""

from pcapng import FileScanner
import pcapng
import numpy as np
import sys
#import scipy.io
#from datetime import datetime

def toint(buf:str) -> int:
    """ 
    Converts a string of bytes in direc byte order.

    :param buf: string of bytes to convert
    :return: string in direct byte order
    """
    nwords = int(len(buf)/8)
    bufout = [0]*nwords
    for i in range(nwords):
       bufout[i] = buf[8*i+7]+(buf[8*i+6]<<8)+(buf[8*i+5]<<16)+(buf[8*i+4] <<24)+( 
            buf[8*i+3] <<32)+(buf[8*i+2]<<40)+(buf[8*i+1]<<48)+(buf[8*i] <<56)
    return bufout

def packet_analyzer(pcapng_file_name:str):
    """ 
    Analyze UDP packets printing the SPEAD info and saving data read from DDR. 
    At present, data are saved for 2 antennas(ant_0, ant_1) and 2 polarization(H, V).

    :param pcapng_file_name: pcapng filename
    """
    try:
        fp = open(pcapng_file_name+'.pcapng', 'rb')
    except(FileNotFoundError):
        print(f"File {pcapng_file_name}.pcapng not found!")
        raise

    scanner = FileScanner(fp)
    flag_idx = True
    SPEAD_info = dict()
    pkt_times = []

    data_len = 1024
    data_size = int(data_len/4) # for 2 antennas and 2 polarizations

    for block in scanner:
        if type(block) == pcapng.blocks.EnhancedPacket:
            pk_buf=block.packet_payload_info[2]
            pk_len = ((pk_buf[38] <<8) + pk_buf[39])-8
            if (pk_len >= 72+data_len) and (len(pk_buf)>(42+72)):
                spead_hdr = toint(pk_buf[42:(42+ 72)])
                if spead_hdr[0] == 0x5304020600000008:
                    if flag_idx:  #to run only once                  
                        SPEAD_info['pkt_payload_length'] = spead_hdr[2] & 0xffffff
                        SPEAD_info['pkt_sync_time'] = spead_hdr[3] & 0xffffff
                        SPEAD_info['pkt_time_stamp(unix)'] = spead_hdr[4] & 0xffffff
                        SPEAD_info['pkt_capture_mode'] = spead_hdr[5] & 0xffffff
                        SPEAD_info['pkt_nof_ant'] = (spead_hdr[6] & 0xff00000000) >> 32
                        SPEAD_info['ant_3'] = (spead_hdr[6] & 0x00ff000000) >> 24
                        SPEAD_info['ant_2'] = (spead_hdr[6] & 0x0000ff0000) >> 16
                        SPEAD_info['ant_1'] = (spead_hdr[6] & 0x000000ff00) >> 8
                        SPEAD_info['ant_0'] = (spead_hdr[6] & 0x00000000ff)
                        SPEAD_info['pkt_tpm_id'] = (spead_hdr[7] & 0xff00000000) >> 32
                        SPEAD_info['ant_station_id'] = (spead_hdr[7] & 0xffff0000) >> 16
                        SPEAD_info['fpga_id'] = (spead_hdr[7] & 0x00000000ff)
                        SPEAD_info['pkt_sample_offset'] = spead_hdr[8] & 0xffffff
                        flag_idx = False 
                pkt_times = pkt_times + [spead_hdr[1] & 0xffffffff]

    fp.close()

    time0=min(pkt_times)
    pkt_indx = np.array(list(set(pkt_times)),dtype='int')
    pkt_indx.sort()
    time_size = pkt_indx.size
    table_data_ant_0 = np.zeros((time_size*data_size, 2),dtype='int')
    table_data_ant_1 = np.zeros((time_size*data_size, 2),dtype='int')
    table_data_ant_2 = np.zeros((time_size*data_size, 2),dtype='int')
    table_data_ant_3 = np.zeros((time_size*data_size, 2),dtype='int')

    #matrix size is [number of udp packets*data in the udp packet for antenna and polarization(968*256) , 2 (H and V)]
    SPEAD_info['table size'] = [len(table_data_ant_0),len(table_data_ant_0[0])]
    #print SPEAD info
    for keys,values in SPEAD_info.items():
        print(f"{keys}= {values}")

    fp = open(pcapng_file_name+'.pcapng', 'rb')
    scanner = FileScanner(fp)
    for block in scanner:
        if type(block) == pcapng.blocks.EnhancedPacket:
            pk_buf=block.packet_payload_info[2]
            pk_len = ((pk_buf[38] <<8) + pk_buf[39])-8
            if pk_len == 72+data_len:
                spead_hdr = toint(pk_buf[42:(42+72)])
                if spead_hdr[0] == 0x5304020600000008:
                    pkt_time = (spead_hdr[1] & 0xffffffff)
                    for ds in range(int(data_size/4)):
                        for t in range(4):
                            H0 = pk_buf[t*2 + (114+(ds*16))]
                            V0 = pk_buf[t*2 + (115+(ds*16))] 
                            H1 = pk_buf[t*2 + (122+(ds*16))]
                            V1 = pk_buf[t*2 + (123+(ds*16))]   
                            table_data_ant_0[(pkt_time*data_size)+ds*4+t, 0] = H0 if H0<=127 else H0-256
                            table_data_ant_0[(pkt_time*data_size)+ds*4+t, 1] = V0 if V0<=127 else V0-256
                            table_data_ant_1[(pkt_time*data_size)+ds*4+t, 0] = H1 if H1<=127 else H1-256
                            table_data_ant_1[(pkt_time*data_size)+ds*4+t, 1] = V1 if V1<=127 else V1-256

    fp.close()

    np.savetxt(pcapng_file_name+'_ant0.txt',table_data_ant_0,fmt='%d ')
    np.savetxt(pcapng_file_name+'_ant1.txt',table_data_ant_1,fmt='%d ')
    # Uncomment when 4 antennas are supported
    #np.savetxt(pcapng_file_name+'_ant2.txt',table_data_ant_2,fmt='%d ')
    #np.savetxt(pcapng_file_name+'_ant3.txt',table_data_ant3,fmt='%d ')

    #To save in mat file format import scipy lib
    #scipy.io.savemat(pcapng_file_name+'_ant0.mat', {'mydata': table_data_ant_0})
    #scipy.io.savemat(pcapng_file_name+'_ant1.mat', {'mydata': table_data_ant_1})
    #scipy.io.savemat(pcapng_file_name+'_ant2.mat', {'mydata': table_data_ant_2})
    #scipy.io.savemat(pcapng_file_name+'_ant3.mat', {'mydata': table_data_ant_3})

    # end

if __name__ == "__main__":
    if len(sys.argv) > 1:
        pcapng_file_name=sys.argv[1]
    else:
        print("Please insert the pcapng file name.")
    packet_analyzer(pcapng_file_name)
