

P1_FILE_NAME = "/Users/philliphu/Downloads/relationship_1"
P2_FILE_NAME = "/Users/philliphu/Downloads/relationship_2"
P3_FILE_NAME = "/Users/philliphu/Downloads/relationship_3"
CONFIG1_FILE_NAME = "/Users/philliphu/Downloads/config_1"
CONFIG2_FILE_NAME = "/Users/philliphu/Downloads/config_2"
CONFIG3_FILE_NAME = "/Users/philliphu/Downloads/config_3"

def dec2addr(dec):
    return ".".join([str(dec >> x & 0xff) for x in [24, 16, 8, 0]])

with open(P1_FILE_NAME, "r") as topo1:
    node_list1 = topo1.readlines()
topo1.close()

with open(P2_FILE_NAME, "r") as topo2:
    node_list2 = topo2.readlines()
topo2.close()

with open(P3_FILE_NAME, "r") as topo3:
    node_list3 = topo3.readlines()
topo3.close()

local_nodes1 = []
for nodes in node_list1:
    local_nodes1.append(nodes.split()[0])

local_nodes2 = []
for nodes in node_list2:
    local_nodes2.append(nodes.split()[0])

local_nodes3 = []
for nodes in node_list3:
    local_nodes3.append(nodes.split()[0])

with open(CONFIG1_FILE_NAME, "w") as config:
    for nodes in node_list1:
        neighbors = nodes.split()
        config.write("router bgp %d\n" %int(neighbors[0]))
        config.write("  bgp router-id %s\n" %dec2addr(int(neighbors[0])))
        del neighbors[0]
        for node in neighbors:
            config.write("  neighbor %s remote-as %s" % (dec2addr(int(node)), node))
            if node in local_nodes1:
                config.write("\n")
            elif node in local_nodes2:
                config.write(" 1\n")
            elif node in local_nodes3:
                config.write(" 2\n")
config.close()
print "file 1 done"

with open(CONFIG2_FILE_NAME, "w") as config:
    for nodes in node_list2:
        neighbors = nodes.split()
        config.write("router bgp %d\n" %int(neighbors[0]))
        config.write("  bgp router-id %s\n" %dec2addr(int(neighbors[0])))
        del neighbors[0]
        for node in neighbors:
            config.write("  neighbor %s remote-as %s" % (dec2addr(int(node)), node))
            if node in local_nodes2:
                config.write("\n")
            elif node in local_nodes1:
                config.write(" 0\n")
            elif node in local_nodes3:
                config.write(" 2\n")
config.close()
print "file 2 done"

with open(CONFIG3_FILE_NAME, "w") as config:
    for nodes in node_list3:
        neighbors = nodes.split()
        config.write("router bgp %d\n" %int(neighbors[0]))
        config.write("  bgp router-id %s\n" %dec2addr(int(neighbors[0])))
        del neighbors[0]
        for node in neighbors:
            config.write("  neighbor %s remote-as %s" % (dec2addr(int(node)), node))
            if node in local_nodes3:
                config.write("\n")
            elif node in local_nodes1:
                config.write(" 0\n")
            elif node in local_nodes2:
                config.write(" 1\n")
config.close()
print "file 3 done"