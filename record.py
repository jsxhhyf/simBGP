import pandas as pd

NODE_LINE_FILE_NAME = "/Users/philliphu/Downloads/relationship_n"
PARTITIONED_FILE_NAME = "/Users/philliphu/Downloads/relationship_n.part.3"
CONFIG_FILE_NAME = "/Users/philliphu/Downloads/config_file"

def dec2addr(dec):
    return ".".join([str(dec >> x & 0xff) for x in [24, 16, 8, 0]])

partition = pd.read_csv(PARTITIONED_FILE_NAME, header=None)

with open(NODE_LINE_FILE_NAME, "r") as topo:
    node_list = topo.readlines()
    del node_list[0]
topo.close()

i = 1 # start from the first router
j = 0 # num of cross partition edges
# with open(CONFIG_FILE_NAME, "w") as config:
#     temp_part = partition.iloc[i - 1, 0]
#     for nodes in node_list:
#         print "%dth node:" %i
#         neighbors = nodes.split()
#         print "len=%d" %len(neighbors)
#         config.write("bgp router %d\n" %i)
#         config.write("  bgp router-id %s\n" %dec2addr(i))
#         for node in neighbors:
#             print node
#             config.write("  neighbor %s" %dec2addr(int(node)))
#             if partition.iloc[int(node) - 1, 0] != temp_part:
#                 config.write(" 1\n")
#             else:
#                 config.write("\n")
#         i += 1
#
# config.close()

temp_part = partition.iloc[i - 1, 0]
for nodes in node_list:
    neighbors = nodes.split()
    for node in neighbors:
        if partition.iloc[int(node) - 1, 0] != temp_part:
            j += 1
    i += 1
print j
