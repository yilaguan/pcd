# Richard Darst, August 2011

import numpy
import random
import networkx.algorithms

import pcd.models
import pcd.graphs
import pcd.util

# weights of -1, 2, 6 seem to make it match the paper... for q.
g = pcd.graphs.polopa_tribes(weightAllied=-1, weightHostile=2)
g_p2 = pcd.graphs.polopa_tribes_peter(fname="highland.txt")
g_p1 = pcd.graphs.polopa_tribes_peter()

assert networkx.algorithms.is_isomorphic(g, g_p2)
assert networkx.algorithms.is_isomorphic(g, g_p1, weighted=True)


G = pcd.models.Graph.fromNetworkX(g, defaultweight=1, diagonalweight=0)
G2 = pcd.models.Graph.fromNetworkX(g_p1, defaultweight=1, diagonalweight=0)
print G.interactions
assert numpy.all(G.interactions - G.interactions.T == 0)

from numpy import array
G._layout = {'GAVEV': array([ 0.53410183,  0.06217559]), 'KOHIK': array([ 0.       ,  0.1474209]), 'UHETO': array([ 0.14830981,  0.34515878]), 'KOTUN': array([ 0.37326864,  0.        ]), 'NAGAM': array([ 0.26417734,  0.41649365]), 'ASARO': array([ 0.56901665,  0.49511319]), 'MASIL': array([ 0.55606811,  0.41225591]), 'NOTOH': array([ 0.07688195,  0.24116678]), 'UKUDZ': array([ 0.70980807,  0.41850366]), 'ALIKA': array([ 1.        ,  0.17964178]), 'GEHAM': array([ 0.43121325,  0.39188928]), 'GAHUK': array([ 0.56559475,  0.2937324 ]), 'GAMA': array([ 0.3887513 ,  0.17512021]), 'OVE': array([ 0.80835312,  0.17731299]), 'NAGAD': array([ 0.28961018,  0.10020374]), 'SEUVE': array([ 0.27922518,  0.62217477])}

while True:
    break
    gamma = 3
    from matplotlib import pyplot
    pyplot.ion()
    pyplot.clf()
    G.cmtyCreate()
    G.minimize(gamma=gamma)
    print gamma, G.q, G.energy(gamma=gamma)
    #if G._layout is None:
    #    import networkx.drawing.layout as layout
    #    G._layout = layout.spring_layout(g)
    #    print G._layout
    if 1 or G.q != 5 and G.energy(gamma=gamma) <= -21:
        g = G.viz()
        raw_input(',')
#exit(2)

#for a,b in [random.sample(range(G.N), 2) for _ in range(1000)]:
#    pcd.util.matrix_swap_basis(G.interactions, a, b)
MR = pcd.models.MultiResolution(low=.01, high=10, number=100)
MR.do(Gs=[G]*12, trials=100)
MR.write("tmp-polopatribes.txt")
#MR.viz()

#for a,b in [random.sample(range(G2.N), 2) for _ in range(1000)]:
#    pcd.util.matrix_swap_basis(G2.interactions, a, b)
#MR = pcd.models.MultiResolution(low=.01, high=10)
#MR.do(Gs=[G2]*12, trials=50)
#MR.write("tmp-polopatribes2.txt")
