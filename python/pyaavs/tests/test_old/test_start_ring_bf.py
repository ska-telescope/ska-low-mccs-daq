#! /opt/aavs/python/bin/python


def start_ring_bf(tile):
    for i in [0, 1, 2, 3, 4, 5, 6, 7]:
        tile.tpm.tpm_10g_core[i].set_src_mac(0x620000000002 + i)
        tile.tpm.tpm_10g_core[i].set_dst_mac(0xE41D2DB40640)
        tile.tpm.tpm_10g_core[i].set_dst_ip("192.168.7.100")
        tile.tpm.tpm_10g_core[i].set_src_port(0xF0D0)
        tile.tpm.tpm_10g_core[i].set_dst_port(0xF0D1)

    tile.tpm.tpm_10g_core[0].set_src_ip("192.168.7.12")
    tile.tpm.tpm_10g_core[1].set_src_ip("192.168.7.13")
    tile.tpm.tpm_10g_core[2].set_src_ip("192.168.7.14")
    tile.tpm.tpm_10g_core[3].set_src_ip("192.168.7.15")
    tile.tpm.tpm_10g_core[4].set_src_ip("192.168.7.16")
    tile.tpm.tpm_10g_core[5].set_src_ip("192.168.7.17")
    tile.tpm.tpm_10g_core[6].set_src_ip("192.168.7.18")
    tile.tpm.tpm_10g_core[7].set_src_ip("192.168.7.19")
    tile['fpga1.udp_core.udp_core_inst_0_udp_core_control_udp_core_control_packet_split_size'] = 0x00002328
    tile['fpga2.udp_core.udp_core_inst_0_udp_core_control_udp_core_control_packet_split_size'] = 0x00002328

    # place a tone in channel 36 & 39 (ch 2 & 5 of the beamformed region)
    tile.tpm.test_generator[0].set_tone(0, 4 * 800e6 / 1024, 0.5)
    tile.tpm.test_generator[0].set_tone(1, 4 * 800e6 / 1024, 0.5)
    tile.tpm.test_generator[1].set_tone(0, 5 * 800e6 / 1024, 0.4)
    tile.tpm.test_generator[1].set_tone(1, 5 * 800e6 / 1024, 0.4)
    tile.tpm.test_generator[0].channel_select(0xffff)
    tile.tpm.test_generator[1].channel_select(0xffff)
    # Use debug generator
    # tile['fpga1.regfile.debug']=0x4
    # tile['fpga2.regfile.debug']=0x4
    # testpoint: ddr request and rnw
    tile['fpga1.regfile.tp_sel'] = 0xa8
    tile['fpga2.regfile.tp_sel'] = 0xa8

    tile['fpga1.beamf_ring.last_frame'] = 0x1
    tile['fpga2.beamf_ring.last_frame'] = 0x1
    tile['fpga1.beamf_ring.frame_timing'] = 2
    tile['fpga1.beamf_ring.frame_rate'] = 0x0010047e
    tile['fpga1.beamf_ring.ch_n'] = 0x100
    tile['fpga2.beamf_ring.frame_timing'] = 2
    tile['fpga2.beamf_ring.frame_rate'] = 0x0010047e
    tile['fpga2.beamf_ring.ch_n'] = 0x100
    tile['fpga1.beamf_ring.control'] = 2
    tile['fpga2.beamf_ring.control'] = 2
    s_frame = tile['fpga1.beamf_ring.current_frame'] + 4000
    tile['fpga1.beamf_ring.start_frame'] = s_frame
    tile['fpga1.beamf_ring.last_frame'] = s_frame + 0x1000000
    tile['fpga2.beamf_ring.start_frame'] = s_frame
    tile['fpga2.beamf_ring.last_frame'] = s_frame + 0x1000000
