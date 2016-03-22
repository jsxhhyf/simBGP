import pandas as pd
import random
from IPy import IP

P1_FILE_NAME = "/Users/philliphu/Downloads/relationship_1"
P2_FILE_NAME = "/Users/philliphu/Downloads/relationship_2"
P3_FILE_NAME = "/Users/philliphu/Downloads/relationship_3"
CONFIG1_FILE_NAME = "/Users/philliphu/Downloads/config_1"
CONFIG2_FILE_NAME = "/Users/philliphu/Downloads/config_2"
CONFIG3_FILE_NAME = "/Users/philliphu/Downloads/config_3"
ORIGIN_FILE_NAME = "/Users/philliphu/Downloads/201501.origin.csv"
TRANSFORMED_ORIGIN_FILE_NAME = "/Users/philliphu/Downloads/201501.origin.t.csv"
SIMPLIFIED_ORIGIN_FILE_NAME = "/Users/philliphu/Downloads/201501.origin.s.csv"

# ----------------transform AS numbers to [1-51195]---------------
#
# origin = pd.read_csv(ORIGIN_FILE_NAME, header=None)
# ASes = origin.iloc[:, 1].drop_duplicates().order()
#
#
# D = {}
# T = pd.DataFrame(data={'origin': ASes, 'new': range(1, ASes.shape[0] + 1)})
# print T.shape, origin.shape
#
# for i in range(0, T.shape[0]):
#     D[T.iloc[i, 1]] = T.iloc[i, 0]
#
# g_counter = 0
# for i in range(0, origin.shape[0]):
#     origin.iloc[i, 1] = D[origin.iloc[i, 1]]
#     g_counter += 1
#     if g_counter % 10000 == 0:
#         print g_counter
#
# origin.to_csv(TRANSFORMED_ORIGIN_FILE_NAME, header=None)
# --------------------------------------------------------

def dec2addr(dec):
    return ".".join([str(dec >> x & 0xff) for x in [24, 16, 8, 0]])

to = pd.read_csv(TRANSFORMED_ORIGIN_FILE_NAME, header=None)
to_simplified = to.head(1000)
to_simplified.to_csv(SIMPLIFIED_ORIGIN_FILE_NAME, header=None)

# to_simplified = pd.read_csv(SIMPLIFIED_ORIGIN_FILE_NAME, header=None)

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

try:
    config1 = open(CONFIG1_FILE_NAME, "a")
    config2 = open(CONFIG2_FILE_NAME, "a")
    config3 = open(CONFIG3_FILE_NAME, "a")
    non123 = 0
    for i in range(0, 999):
        if str(to_simplified.iloc[i, 1]) in local_nodes1:
            print "fuck!"
            config1.write("event announce-prefix %s %s %f\n" % (dec2addr(to_simplified.iloc[i, 1]), IP(to_simplified.iloc[i, 0]).net(), random.uniform(0, 20)))
        # elif str(to_simplified.iloc[i, 1]) in local_nodes2:
        #     config2.write("event announce-prefix %s %s %f\n" % (dec2addr(to_simplified.iloc[i, 1]), IP(to_simplified.iloc[i, 0]).net().strNormal(), random.uniform(0, 20)))
        # elif str(to_simplified.iloc[i, 1]) in local_nodes3:
        #     config3.write("event announce-prefix %s %s %f\n" % (dec2addr(to_simplified.iloc[i, 1]), IP(to_simplified.iloc[i, 0]).net(), random.uniform(0, 20)))
finally:
    config1.close()
    config2.close()
    config3.close()