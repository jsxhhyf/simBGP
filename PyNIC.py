import pcap, dpkt

pc = pcap.pcap('en0')
pc.setfilter('tcp')
for i, j in pc:
    print i, `j`
