# Richard Darst, July 2011

import copy
from math import exp, log
import numpy
import random
import sys
import types

from networkx.algorithms import is_isomorphic
import networkx

import graphs
import models
import util

# Initialized to one community per list
G = graphs.random_graph(size=5)
G.check()

# Test copying
G2 = G.copy()
assert id(G) != id(G2)
assert id(G) != id(G2)

# Test that various attributes do NOT have the same id:
for name in dir(G):
    if name[:2] == '__' \
       or name in ('_layout', 'q', 'q_c', 'q_python' )\
       or name in G.__class__.__dict__:
        continue
    print name, id(getattr(G, name)), id(getattr(G2, name)), \
          type(getattr(G, name))
    v1 = getattr(G , name)
    v2 = getattr(G2, name)
    assert id(v1) != id(v2), name
# Continue testing copying.  Make sure that 
G .check()
G2.check()
G .cmtyCreate(randomize=True)
G2.cmtyCreate(randomize=True)
assert (G.cmty != G2.cmty).any()
assert (G.cmtyl != G2.cmtyl).any()
#from fitz import interactnow
#sys.exit(1)
G .check()
G2.check()
G .minimize(1.0)
G2.minimize(.01) # use different gammas, otherwise it is too likely to
                 # be identical results
G .check()
G2.check()
assert (G.cmty != G2.cmty).any()
assert (G.cmtyl != G2.cmtyl).any()


#
# Test related to cmty list data structures
#
G.check()

# Test that cmtyListCheck does find errors:
G.cmty[:] = 0
print "***Ignore errors below, this is a test of errorchecking***"
try:                    G.check()
except AssertionError:
    print "***Ignore errors above, this is a test of errocchecking***"
else:        raise AssertionError("cmtyListCheck did not detect an error "
                                  "when there should be one.")
G.cmtyListInit()
G.check()

# Test various ways of manipulating the lists
G.minimize(1.0)
G.check()

G.minimize(0)
G.check()

G.remapCommunities()
G.check()


# Test to/from networkX
array = numpy.asarray([[0,  0, 1,  2, 1],
                       [0,  0, 1, -1, 1],
                       [1,  1, 0, -1, 0],
                       [2, -1, -1, 0, 1],
                       [1,  1,  0, 1, 0],])
g1 = util.networkx_from_matrix(array, ignore_values=(0,))
g2 = networkx.Graph()
g2.add_edges_from([#(0, 1, {'weight':-1}),
                   (0, 2, {'weight': 1}),
                   (0, 3, {'weight': 2}),
                   (0, 4, {'weight': 1}),
                   (1, 2, {'weight': 1}),
                   (1, 3, {'weight':-1}),
                   (1, 4, {'weight': 1}),
                   (2, 3, {'weight':-1}),
                   #(2, 4, {'weight':-1}),
                   (3, 4, {'weight': 1}),
                  ])
assert is_isomorphic(g1, g2, weighted=True)
G1 = models.Graph.fromNetworkX(g1)
G2 = models.Graph.fromNetworkX(g2)


# Test rearranging of rows and columns
for i in range(10):
    G1 = G2.copy()
    # Do a bunch of swaps
    for a,b in [random.sample(range(G1.N), 2) for _ in range(100)]:
        util.matrix_swap_basis(G1.imatrix, a, b)
    assert is_isomorphic(G1.make_networkx(), G2.make_networkx(), weighted=True)

# Test rearranging of rows and columns (more aggressive)

# This one is more aggressive, since it involves the really big
# random_graph(size=5) object.  We have weighted=False to make the
# is_isomorphic return in a reasonable time.
for i in range(10):
    G1 = G.copy()
    # Do a bunch of swaps
    for a,b in [random.sample(range(G1.N), 2) for _ in range(100)]:
        util.matrix_swap_basis(G1.imatrix, a, b)
    assert is_isomorphic(G1.make_networkx(), G.make_networkx(), weighted=False)


# Assert that gamma=0 and we get only one community at the end
# (everything collapses to one cmty at gamma=0)
G.cmtyCreate()
G.minimize(gamma=0)
assert G.q == 1



# Test hashes
assert G.hash() == G.hash()
assert G.copy().hash() == G.hash()
G2 = G.copy()
G2.minimize(gamma=1)
assert G.hash() != G2.hash()

# Test getting and setting community state.
state = G.getcmtystate()
G2.setcmtystate(state)
assert G.hash() == G2.hash()
