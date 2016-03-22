import pandas as pd

PARTITION_FILE_NAME = "/Users/philliphu/Downloads/relationship_n.part.3"
NODE_LINE_FILE_NAME = "/Users/philliphu/Downloads/relationship_n"
P1_FILE_NAME = "/Users/philliphu/Downloads/relationship_1"
P2_FILE_NAME = "/Users/philliphu/Downloads/relationship_2"
P3_FILE_NAME = "/Users/philliphu/Downloads/relationship_3"

with open(NODE_LINE_FILE_NAME, "r") as topo:
    node_list = topo.readlines()
    del node_list[0]
topo.close()

partition = pd.read_csv(PARTITION_FILE_NAME, header=None)
try:
    p1_file = open(P1_FILE_NAME, "w")
    p2_file = open(P2_FILE_NAME, "w")
    p3_file = open(P3_FILE_NAME, "w")
    for i in range(0, partition.shape[0]):
        if partition.iloc[i, 0] == 0:
            p1_file.write("%d " % (i + 1))
            p1_file.write(node_list[i])
        elif partition.iloc[i, 0] == 1:
            p2_file.write("%d " % (i + 1))
            p2_file.write(node_list[i])
        elif partition.iloc[i, 0] == 2:
            p3_file.write("%d " % (i + 1))
            p3_file.write(node_list[i])
except:
    pass
finally:
    p1_file.close()
    p2_file.close()
    p3_file.close()