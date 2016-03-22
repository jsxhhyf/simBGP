import pandas as pd
import numpy as np

FILE_NAME = "/Users/philliphu/Downloads/relationship_transformed.csv"
_FILE_NAME = "/Users/philliphu/Downloads/relationship_n"
data = pd.read_csv(FILE_NAME, header=None)
# b = data.iloc[:, 1].isin(data.iloc[:, 0])
# data = data[b]
concatenated = data[0].append(data[1])
con_ordered = concatenated.order().drop_duplicates()
node_num = con_ordered.shape[0]
# print data.shape[0], node_num
grouped = data.groupby(0)

# T = pd.DataFrame(data={'origin': con_ordered, 'new': range(1, node_num + 1)})
# D = {}
#
# for i in range(0, node_num):
#     D[T.iloc[i, 1]] = T.iloc[i, 0]
#
#
# for i in range(0, 2):
#     for j in range(0, data.shape[0]):
#         data.iloc[j, i] = D[data.iloc[j, i]]
#
# data.to_csv(FILE_NAME, header=False)

# with open(_FILE_NAME, "w") as file:
#     file.write("%d %d\n" % (grouped.count().size, data.shape[0] / 2))
#     for element in grouped:
#         # file.write("%d " %element[0])
#         for vertex in element[1].iloc[:, 1].values:
#             file.write("%d " %vertex)
#         file.write("\n")
# file.close()

for element in grouped:
    if element[0] == 10:
        break
    else:
        print "*************** %d *******************" %element[0]
        for node in element[1].iloc[:, 1]:
            print node

print 'node num:', grouped.count().size, node_num
print 'edge num:', data.shape[0]