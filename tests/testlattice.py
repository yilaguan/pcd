# Richard Darst, August 2011

import models
import numpy

import networkx
import util

from networkx.generators.classic import grid_graph

g = grid_graph([20,20], periodic=True)
for a,b,d in g.edges(data=True):
    d['weight'] = -1

G = models.Graph.fromNetworkX(g, defaultweight=1)
print (numpy.sum(G.imatrix) - numpy.sum(G.imatrix.diagonal()))/(400**2-400.)
#exit()

assert numpy.all(G.imatrix - G.imatrix.T == 0)

MR = models.MultiResolution(low=.1, high=100, number=10)
MR.do([G]*5, trials=10)
MR.write('tmp-lattice.txt')
#MR.viz()

