# Richard Darst, September 2011

import pcd
from pcd import graphs

fast = globals().get('fast', False)

g = graphs.karate_club()
for a,b,d in g.edges(data=True):
    print a, b, d
G = pcd.Graph.fromNetworkX(g, defaultweight=1)
G.minimize(gamma=.1)
if not fast:
    G.viz()

ldensity = 50
if fast:
    ldensity = 10

MR = pcd.MultiResolution()
MR.run([G]*10, gammas=dict(low=0.005, high=50, density=ldensity),
      threads=2)
MR.write('tmp-karate.txt')
MR.plot("karate.png")
