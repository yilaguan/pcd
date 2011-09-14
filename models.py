# Richard Darst, July 2011

import collections
import copy
import ctypes
import itertools
import math
from math import exp, log, floor, ceil
import numpy
import cPickle as pickle
import random
import sys
import time

import networkx


from cmodels import cGraph_fields
import cmodels
import util

log2 = lambda x: math.log(x, 2)

class _cobj(object):
    """Generic code to interface an object with ctypes using the darst method.

    Note: work in progress.
    """
    def _allocStruct(self, cModel):
        self._struct = cModel()
        self._struct_p = ctypes.pointer(self._struct)

    def _allocArray(self, name, array=None, **args):
        """Allocate an array in a way usable by both python and C.

        `name` is the name of the array to allocate: it will be
        self.`name` and self.SD.`name`.  `**args` are arguments passed
        to `numpy.zeros` to allocate the arrays.

        If you want to initilize the array to something, you have to
        do it afterwards, like this:
        self.lattsite[:] = S12_EMPTYSITE
        """
        # This code can be hard to understand, since we can't use the
        # name, but it is equivalent to this for the name `lattsite`:
        ##  self.__dict__["lattsite"] = numpy.zeros(**args)
        ##  self.SD.lattsite = self.lattsite.ctypes.data
        # Get dtype if not already a argument
        if 'dtype' not in args:
            args['dtype'] = getattr(self._struct, name)._type_
        if array is None:
            array = numpy.zeros(**args)
        self.__dict__[name] = array
        setattr(self._struct, name,
                array.ctypes.data_as(ctypes.POINTER(
                    getattr(self._struct, name)._type_)))
        #setattr(self._struct, name, array.ctypes.data)
    def _allocArrayPointers(self, pointerarray, array):
        for i, row in enumerate(array):
            pointerarray[i] = row.ctypes.data

    def __getattr__(self, attrname):
        """Wrapper to proxy attribute gets to the C SimData struct
        """
        if attrname in cGraph_fields:
            return getattr(self._struct, attrname)
        raise AttributeError("No Such Attribute: %s"%attrname)
    def __setattr__(self, attrname, value):
        """Wrapper to proxy attribute sets to the C SimData struct
        """
        if attrname in cGraph_fields:
            setattr(self._struct, attrname, value)
        else:
            self.__dict__[attrname] = value

class Graph(_cobj, object):
    """Core Potts-based community detection object.

    This returns an object which can be used to do a community
    detection on a graph.

    There is an important distinction between this object, and the
    underlying NetworkX graph object.  The NetworkX object is a
    Pythonic representation of the graph, but can not be used for
    minimization itself.  The Graph object is the thing which can be
    used for minimizing.  The Graph object can be created from a
    NetworkX object easily.  A typical use is to set up a NetworkX
    graph from loading a file, or your other simulation, and then
    using that to set up Graph object.

    """
    def __init__(self, N, randomize=True):
        self._fillStruct(N)
        self.N = N
        self.cmtyCreate(randomize=randomize)
        self.oneToOne = 1


    @classmethod
    def fromNetworkX(cls, graph, defaultweight=1,
                     layout=None, randomize=True,
                     diagonalweight=None):
        """Create a Graph glass from a NetworkX graph object.

        The NetworkX graph object is expected to have all edges have a
        attribute `weight` which is set to the interaction between the
        nodes.  Note that negative weight is attractive, positive
        weight is repulsive.

        `defaultweight` is the weight for all not explicitely defined
        pairs of nodes.  Note that positive weight is repulsive and
        negative weight is attractive.  `diagonalweight` is the weight
        of all diagonals on the matirx.

        `layout` is a mapping nodeid->(x,y) which is used in the
        .viz() method.

        `randomize` is passed to the constructor, randomizes node
        initial assignments.
        """
        G = cls(N=len(graph), randomize=randomize)
        G._graph = graph
        G._layout = layout

        G._nodeIndex = { }
        G._nodeLabel = { }

        # Set up node indexes (since NetworkX graph object nodes are
        # not always going to be integeras in range(0, self.N)).
        for i, name in enumerate(sorted(graph.nodes())):
            G._nodeIndex[name] = i
            G._nodeLabel[i] = name
            graph.node[name]['index'] = i

        # Default weighting
        G.imatrix[:] = defaultweight
        # Default diagonal weighting
        if diagonalweight is not None:
            for i in range(G.N):
                G.imatrix[i, i] = diagonalweight
        # All explicit weighting from the graph
        for n0 in graph.nodes():
            for n1 in graph.neighbors(n0):
                i0 = graph.node[n0]['index']
                i1 = graph.node[n1]['index']
                G.imatrix[i0,i1] = graph[n0][n1]['weight']
        # Check that the matrix is symmetric (FIXME someday: directed graphs)
        if not numpy.all(G.imatrix == G.imatrix.T):
            print "Note: interactions matrix is not symmetric"
        return G

    @classmethod
    def from_imatrix(cls, imatrix, layout=None):
        """Create a graph structure from a matrix of interactions.
        """
        # This should be improved sometime.
        G = cls(N=imatrix.shape[0])
        G.imatrix[:] = imatrix
        G._layout = layout
        return G
    @classmethod
    def from_coords_and_efunc(cls, coords, efunc, periodic=None):
        """Create graph structure from coordinates+energy function.

        This helper class method is used to create an imatrix from a
        list of coordinates ( [[x0,y0,...], [x1,y1,...], ...]) and a
        efunc, which maps distance -> energy_of_interaction at that
        distance.  The efunc must be able to be applied to an array.

        If `periodic` is given, it is used as a periodic boundary
        length: either a number or a [Lx, Ly, ...] array.
        """
        G = cls(N=coords.shape[0])
        G._layout = coords
        #orig_settings = numpy.seterr()
        #numpy.seterr(all="ignore")

        for n1 in range(len(coords)):
            delta = coords[n1] - coords
            if periodic:
                delta -=  numpy.round(delta/float(periodic))*periodic
            delta = delta**2
            dist = numpy.sum(delta, axis=1)
            dist = numpy.sqrt(dist)
            G.imatrix[n1, :] = efunc(dist)
        #numpy.seterr(**orig_settings)
        return G


    def _fillStruct(self, N=None):
        """Fill C structure."""
        _cobj._allocStruct(self, cmodels.cGraph)

        self._allocArray("cmtyll", shape=[N]*2)
        self._allocArray("cmtyl", shape=N, dtype=ctypes.c_void_p)
        self._allocArrayPointers(self.cmtyl, self.cmtyll)
        self._allocArray("cmty",  shape=N)
        self._allocArray("cmtyN", shape=N)
        self._allocArray("randomOrder", shape=N)
        self._allocArray("randomOrder2", shape=N)
        self.randomOrder[:]  = numpy.arange(N)
        self.randomOrder2[:] = numpy.arange(N)
        self._allocArray("imatrix", shape=(N, N))

    def __getstate__(self):
        """Get state for pickling"""
        state = self.__dict__.copy()
        del state['_struct']
        del state['_struct_p']
        state['__extra_attrs'] = {'N':self.N, 'oneToOne':self.oneToOne }
        #for name, type_ in self._struct._fields_:
        #    if name in state  and isinstance(state[name], numpy.ndarray):
        #        setattr(self, name, state[name])
        #        del state[name]
        return state
    def __setstate__(self, state):
        """Set state when unpickling"""
        self.__init__(state['__extra_attrs']['N'])
        #self._fillStruct(n=state['n'])
        for name, type_ in self._struct._fields_:
            #print name
            if name in state and isinstance(state[name], numpy.ndarray):
                self._allocArray(name, array=state[name])
                del state[name]
        self._allocArrayPointers(self.cmtyl, self.cmtyll)
        for k, v in state['__extra_attrs'].items():
            setattr(self, k, v)
        del state['__extra_attrs']
        self.__dict__.update(state)
    def copy(self):
        """Return a copy of the object (not sharing data arrays).
        """
        # Right now we turn this into a string and back, in order to
        # make actual deep copies of all the arrays.  FIXME.
        new = pickle.loads(pickle.dumps(self, -1))
        #new._allocArray('imatrix', array=self.imatrix)
        return new

    def cmtyCreate(self, cmtys=None, randomize=None):
        """Create initial communities for a model.

        By default, arrays are initialized to one particle per
        community, in random order.

        `cmtys`=<array of length nNodes>: initialize with this initial
        array.  Default: None

        `randomize`=<bool>: Randomize the initial community
        assignments.  Default: True for cmtys=None, False otherwise.
        """
        if cmtys is None:
            cmtys = numpy.arange(self.N)
            randomize = True
        else:
            randomize = False
        if randomize:
            numpy.random.shuffle(cmtys)
        self.cmty[:] = cmtys
        #self.Ncmty = numpy.max(cmtys)+1 done in cmtyListInit()
        #self.cmtyN[:] = 1   # done in cmtyListInit()
        self.cmtyListInit()
    def cmtyListInit(self):
        """Initialize the efficient community lists.

        The community list (self.cmtyll[community_index, ...]) is a
        data structure optimized for the community lookups.  This
        function fills self.cmtyll from self.cmty[i].
        """
        print "cmtyListInit"
        cmodels.cmtyListInit(self._struct_p)
    def cmtySet(self, n, c):
        """Set the community of a particle."""
        raise NotImplementedError("cmtySet not implemented yet.")
    def cmtyContents(self, c):
        """Array of all nodes in community c."""
        return self.cmtyll[c, :self.cmtyN[c]]
    def cmtys(self):
        """Return an iterator over all non-empty community IDs.

        This is a useful method as it only returns communities that
        are non-empty, unlike range(G.cmtyN)
        """
        return ( c for c in range(self.Ncmty) if self.cmtyN[c]>0 )
    def check(self):
        """Do an internal consistency check."""
        print "cmtyListCheck"
        errors = cmodels.cmtyListCheck(self._struct_p)
        assert errors == 0, "We have %d errors"%errors
        assert self.q == len(set(self.cmty))
        return errors
    def _gen_random_order(self, randomize=True):
        """Generate random orders to use for iterations."""
        if not randomize:
            # Fake mode: actually sort them
            numpy.sort(self.randomOrder)
            numpy.sort(self.randomOrder2)
        else:
            numpy.random.shuffle(self.randomOrder)
            numpy.random.shuffle(self.randomOrder2)

    def viz(self, show=True, fname=None):
        """Visualize the detected communities.

        This uses matplotlib to visualize the graphs.  You must have a
        networkx representation of the graph stored at `self._graph`.

        If `show` is True (default), use pyplot.show() to make an
        visual display.  If `fname` is a string, save a copy of the
        graph to that file.
        """
        import matplotlib.pyplot as plt
        #from fitz import interactnow

        colorMap = list(range(self.Ncmty))
        r = random.Random()
        r.seed('color mapping')
        r.shuffle(colorMap)

        g = self._graph.copy()
        for a,b,d in g.edges_iter(data=True):
            weight = d['weight']
            width = 1
            #print a,b,weight
            if self.cmty[g.node[a]['index']] == self.cmty[g.node[b]['index']]:
                newweight = 15
                width = 5
            elif weight < 0:
                newweight = 6
                width = 5
            else:
                newweight = 3
            g.edge[a][b]['weight'] = newweight
            g.edge[a][b]['width'] = width
            #del g.edge[a][b]['weight']

        cmtys = [ self.cmty[d['index']] for (n,d) in g.nodes(data=True) ]
        networkx.draw(g,
                node_color=[colorMap[c] for c in cmtys],
                edge_color=[d.get('color', 'green') for a,b,d in g.edges(data=True)],
                width=[d.get('width', 1) for a,b,d in g.edges(data=True)],
                node_size=900,
                labels = dict((n, "%s (%s)"%(n, c))
                              for (n, c) in zip(g.nodes(), cmtys)),
                pos=self._layout)
        #plt.margins(tight=True)
        if show:
            plt.show()
        if fname:
            plt.savefig(fname, bbox_inches='tight')
        return g
    def get_colormapper(self, colormap_name='gist_rainbow'):
        """Return a colormapper object: colormapper(cmty_id) -> integer_color

        This is a helper method which will return an object which can
        be called with communities and return colors.
        """
        g = self.supernode_networkx()
        return util.ColorMapper(g, colors, colormap_name=colormap_name)

    def savefig(self, fname, coords,
                radii=None, base_radius=0.5, periodic=None, energies=None,
                nodes='circles',
                hulls=None,
                **kwargs):
        """Save a copy of layout to `fname`.

        `coords` is a mapping of node index to (x,y) position.

        `nodes` can be either 'circles' or 'squares', and switches
        between drawing circles for nodes, or drawing a square on the
        background indicating the community of that site (mostly
        useful for square lattices).

        `radii` is a list of relative sizes with the same length as
        `coords`. Smallest particles should be size 1.  `base_radius`
        is a mulitplier for all radii.

        `energies`, if given, will place a small circle in the center
        of each node to indicate its relative energy.  `energies`
        should be an n-length array indicating energy of each
        particle.

        `periodic`, if given, is the (square) box length and used to
        add periodic images of particles when needed.

        `hulls`, if true, will draw convex hulls of communities on the
        background.
        """
        import matplotlib.figure
        import matplotlib.backends.backend_agg
        from matplotlib.patches import Circle, Rectangle, Polygon
        import matplotlib.cm as cm
        import matplotlib.colors as colors

        cmtyColor = self.get_colormapper()

        #f = matplotlib.backends.backend_agg.Figure()
        fig = matplotlib.figure.Figure()
        canvas = matplotlib.backends.backend_agg.FigureCanvasAgg(fig)
        ax = fig.add_subplot(111, aspect='equal')

        if type(radii)==type(None):
            radii=numpy.ones(self.N)*base_radius
        else:
            radii=radii*base_radius

        for n in range(self.N):
            if nodes == 'circles':
                p = Circle(coords[n], radius=radii[n], axes=ax,
                           #color=colormap.to_rgba(n),
                           color=cmtyColor(self.cmty[n]),
                           **kwargs)
            elif nodes == 'squares':
                p = Rectangle(coords[n]-(base_radius,base_radius),
                              width=2*base_radius, height=2*base_radius,
                              axes=ax,
                              color=cmtyColor(self.cmty[n]),
                              **kwargs)
            ax.add_patch(p)
            if periodic and nodes == 'circles':
                greaterthanl=( coords[n] + radii[n] > periodic )
                lessthanzero=( coords[n] - radii[n] < 0        )
                if greaterthanl.any() or lessthanzero.any():
                    p = Circle(
                        coords[n]-periodic*greaterthanl+periodic*lessthanzero,
                        radius=radii[n],
                        color=cmtyColor(self.cmty[n]),
                        **kwargs)
                    ax.add_patch(p)

        if energies:
            e_colormap = cm.get_cmap('RdYlBu')
            e_norm = colors.Normalize()
            e_norm.autoscale(energies)
            for n in range(self.N):
                cir = Circle(coords[n], radius=radii[n]/2, axes=ax,
                             color=e_colormap(e_norm(energies[n])),
                             zorder=1,
                             **kwargs)
                ax.add_patch(cir)

        if hulls:
            #from support.convex_hull import convex_hull
            #from support.convexhull import convexHull
            from support.convexhull import convex_hull
            for c in self.cmtys():
                ns = self.cmtyContents(c)
                points = [ coords[n] for n in ns ]
                points = numpy.asarray(points)
                #if len(points) > 5:
                #    print points
                #    points = convex_hull(points.T)
                points = convex_hull(tuple(p) for p in points)
                p = Polygon(points, alpha=.25, color=cmtyColor(c),
                            zorder=-2,
                            axes=ax)
                ax.add_patch(p)


        ax.autoscale_view(tight=True)
        print fname
        if periodic:
            ax.set_xlim(0,periodic)
            ax.set_ylim(0,periodic)
        canvas.print_figure(fname, bbox_inches='tight')


    def energy(self, gamma):
        """Return total energy of the graph."""
        return cmodels.energy(self._struct_p, gamma)
    def energy_cmty(self, gamma, c):
        """Return energy due to community c."""
        return cmodels.energy_cmty(self._struct_p, gamma, c)
    def energy_cmty_n(self, gamma, c, n):
        """Return energy due to particle n if it was in community c."""
        return cmodels.energy_cmty_n(self._struct_p, gamma, c, n)
    def energy_cmty_cmty(self, gamma, c1, c2):
        """Total entery of interaction between two communities.

        This can be used for making the supernode graph, but is not
        used in normal energy calculations as this is not included in
        normal energy calculations."""
        return cmodels.energy_cmty_cmty(self._struct_p, gamma, c1, c2)
    def energy_n(self, gamma, n):
        """Energy of particle n in its own community."""
        return cmodels.energy_n(self._struct_p, gamma, n)
    @property
    def q_python(self):
        """Number of communities in the graph.

        The attribute Ncmty is an upper bound for the number of
        communites, but some of those communities may be empty.  This
        attribute returns the number of non-empty communities."""
        q = len([1 for c in range(self.Ncmty) if self.cmtyN[c] > 0])
        #q = sum(self.cmtyN > 0)
        #q = len(set(self.cmty))  #FIXME this is fast, but a bit wrong.
        #assert q == len(set(self.cmty))
        return q
    @property
    def q_c(self):
        """Number of communities in the graph.

        The attribute Ncmty is an upper bound for the number of
        communites, but some of those communities may be empty.  This
        attribute returns the number of non-empty communities.

        Optimized implementation in C."""
        return cmodels.q(self._struct_p)
    q = q_c
    def n_counts(self):
        """Return countsogram of community sizes."""
        #community sizes can go from 1 - N
        n_counts = {}
        community_sizes=[ self.cmtyN[c] for c in range(self.Ncmty)
                          if self.cmtyN[c] > 0 ]
        for size in community_sizes:
            if size in n_counts.keys():
                n_counts[size]=n_counts[size]+1
            else:
                n_counts[size]=1
        return n_counts
    @property
    def entropy_python(self):
        """Return the entropy of this graph.
        """
        N = float(self.N)
        H = sum( (n/N)*log2(n/N)  for n in self.cmtyN
                 if n!=0 )
        return -H
    @property
    def entropy_c(self):
        """Return the entropy of this graph.  Optimized impl. in C.
        """
        return cmodels.entropy(self._struct_p)
    entropy = entropy_c

    def minimize_trials(self, gamma, trials):
        """Minimize system using .minimize() and `trials` trials.
        """
        minE = float('inf')
        minCmtys = self.cmty.copy()

        for i in range(trials):
            self.cmtyCreate() # randomizes it
            changes = self.minimize(gamma)
            thisE = self.energy(gamma)
            if thisE < minE:
                minE = thisE
                minCmtys[:] = self.cmty

        self.cmty[:] = minCmtys
        self.cmtyListInit()  # reload the lists from cmty assignments
        return changes

    def minimize(self, gamma):
        """Minimize the communities at a certain gamma.

        This function requires a good starting configuration.  To do
        that, use self.cmtyCreate() first.
        """
        print "beginning minimization (n=%s, gamma=%s)"%(self.N, gamma)
        changes = 0

        changesCombining = None
        for round_ in itertools.count():
            self._gen_random_order()
            changesMoving = self._minimize(gamma=gamma)
            changes += changesMoving
            print "  (r%2s) cmtys, changes: %4d %4d"%(round_, self.q,
                                                      changesMoving)

            if changesMoving == 0 and changesCombining == 0:
                break

            # If we got no changes, then try combining communities
            # before breaking out.
            if changesMoving == 0:
                changesCombining = self.combine_cmtys(gamma=gamma)
                #changesCombining = self.combine_cmtys_supernodes(gamma=gamma)
                changes += changesCombining
                print "  (r%2s) cmtys, changes: %4d %4d"%(
                                           round_, self.q, changesCombining), \
                      "(<-- combining communities)"

                self.remapCommunities(check=False)
            # If we have no changes in regular and combinations, escape
            if changesMoving == 0 and changesCombining == 0:
                break
            if round_ > 250:
                print "  Exceeding maximum number of rounds."
                break
        #print set(self.cmty),
        return changes
    def _minimize(self, gamma):
        return cmodels.minimize(self._struct_p, gamma)
    def overlapMinimize(self, gamma):
        """Attempting to add particles to overlapping communities.
        """
        changes = 0
        changes_add = 0
        changes_remove = None
        for round_ in itertools.count():
            changes_add = self._overlapMinimize_add(gamma)
            changes += changes_add
            print "  (r%2s) overlap: adding  : %4d"%(round_, changes_add)
            if changes_add == 0 and changes_remove == 0:
                break
            if changes_add == 0:
                changes_remove = self._overlapMinimize_remove(gamma)
                changes += changes_remove
                print "  (r%2s) overlap: removing: %4d"%(
                                                     round_, changes_remove)
            if changes_add == 0 and changes_remove == 0:
                break
            if round_ > 250:
                print "  Exceeding maximum number of rounds"
                break
        return changes
    def _overlapMinimize_add(self, gamma):
        return cmodels.overlapMinimize_add(self._struct_p, gamma)
    def _overlapMinimize_remove(self, gamma):
        return cmodels.overlapMinimize_remove(self._struct_p, gamma)
    def combine_cmtys(self, gamma):
        """Attempt to combine communities if energy decreases."""
        return cmodels.combine_cmtys(self._struct_p, gamma)

    def remapCommunities_python(self, check=True):
        """Collapse all communities into the lowest number needed to
        represent everything.

        For example, if we have communities 0, 1, 5, 6 with nonzero
        numbers of particles, this will change us to have communities
        0, 1, 2, 3 only."""
        print "remapping communities"
        def find_empty_cmty():
            """Start at zero, and find the first (lowest-index) empty
            community.
            """
            for m in range(self.Ncmty):
                if self.cmtyN[m] == 0:
                    # Commented out because this significantly slows things.
                    #assert len([ 1 for i in range(self.N)
                    #             if self.cmty[i] == m  ]) == 0
                    return m

        for oldCmty in range(self.Ncmty-1, -1, -1):
            #print "oldCmty:", oldCmty
            # Ignore when we already have a community
            if self.cmtyN[oldCmty] == 0:
                continue
            # Where do we store this?
            newCmty = find_empty_cmty()
            #print "newCmty:", newCmty
            if newCmty is None:
                break
            assert newCmty != oldCmty
            if newCmty > oldCmty:
                #print "No more communities empty"
                break
            # We have established we want to move oldCmty to newCmty,
            # now do it.
            self.cmtyll[newCmty, :] = self.cmtyll[oldCmty, :]
            #for i in range(self.N):
            #    if self.cmty[i] == oldCmty:
            #        self.cmty[i] = newCmty
            self.cmty[self.cmty==oldCmty] = newCmty
            self.cmtyN[newCmty] = self.cmtyN[oldCmty]
            self.cmtyN[oldCmty] = 0
            self.Ncmty -= 1;
        if check:
            self.check()
    def remapCommunities_c(self, check=True):
        print "        remapping communities: ",
        changes = cmodels.remap_cmtys(self._struct_p)
        print changes, "changes"
        if check:
            self.check()
    remapCommunities = remapCommunities_c

    def _test(self):
        return cmodels.test(self._struct_p)
    def make_networkx(self, ignore_values=()):
        """Return a networkX representation of the interaction matrix.

        This could be useful where """

        g = util.networkx_from_matrix(self.imatrix,
                                      ignore_values=ignore_values)
        return g


    def supernode_networkx(self):
        g = networkx.Graph()
        g.add_nodes_from(self.cmtys())
        for c in self.cmtys():
            for n in self.cmtyContents(c):
                for m, interaction in enumerate(self.imatrix[n]):
                    if interaction < 0:
                        g.add_edge(c, self.cmty[m])
        return g
    def supernodeGraph(self, gamma, multiplier=100):
        """Great a sub-graph of super-nodes composed of communities.

        Each community is turned into a super-node, and energy of
        interaction between communities is calculated.
        """
        self.remapCommunities()
        N = self.q
        G = self.__class__(N=N)
        for c1 in range(N):
            for c2 in range(c1+1, N):
                # Find the energy of interaction between c1 and c2
                E = self.energy_cmty_cmty(gamma, c1, c2)
                G.imatrix[c1, c2] = E*multiplier
                G.imatrix[c2, c1] = E*multiplier
        return G
    def loadFromSupernodeGraph(self, G):
        # For each community in the sub-graph
        mapping = { }
        for c in range(G.N):
            for n in self.cmtyContents(c):
                mapping[n] = G.cmty[c]
        #print mapping
        print "Subgraph changes in q: %d -> %d"%(self.q, G.q)
        assert max(mapping) == len(mapping)-1
        #print self.cmty
        for n in range(self.N):
            #print "x", n, self.cmty[n], "->", mapping[n]
            self.cmty[n] = mapping[n]
        #print self.cmty
        self.cmtyListInit()
        #self.check()
    def combine_cmtys_supernodes(self, gamma, maxdepth=1):
        """Attempt to combine communities if energy decreases."""
        depth = getattr(self, "depth", 0)
        if depth >= maxdepth:
            return 0
        # Can't minimize if there are not enough communities.
        if self.q == 1:
            return 0
        print "==== minimizing subgraph, depth:", depth
        subG = self.supernodeGraph(gamma=gamma, multiplier=1000)
        subG.depth = depth + 1
        # If entire interaction matrix is positive, combining is futile.
        if not numpy.any(subG.imatrix < 0):
            return 0
        changes = subG.minimize(gamma=gamma)
        # No need to try to reload subgraph if no changes.
        if changes == 0:
            return 0
        # A bit of error checking (note: we should never even get here
        # since this is conditinod out above).
        if not numpy.any(subG.imatrix < 0):
            assert changes == 0
        # Reload
        self.loadFromSupernodeGraph(subG)
        print "==== done minimizing subgraph, depth:", depth
#        raw_input(str(changes)+'>')
        return changes

class MultiResolutionCorrelation(object):
    def __init__(self, gamma, Gs, nhistbins=50):
        pairs = [ ]

        Gmin = min(Gs, key=lambda G: G.energy(gamma))
        for i, G0 in enumerate(Gs):
            for j, G1 in enumerate(Gs[i+1:]):
                pairs.append((G0, G1))

        Is = [ util.mutual_information(G0,G1) for G0,G1 in pairs ]

        VI = numpy.mean([G0.entropy + G1.entropy - 2*mi
                         for ((G0,G1), mi) in zip(pairs, Is)])
        In = numpy.mean([2*mi / (G0.entropy + G1.entropy)
                         for ((G0,G1), mi) in zip(pairs, Is)
                         if G0.q!=1 or G0.q!=1])

        self.gamma   = gamma
        self.q       = numpy.mean(tuple(G.q for G in Gs))
        self.q_std   = numpy.std(tuple(G.q for G in Gs), ddof=1)
        self.qmin    = Gmin.q

        self.E       = numpy.mean(tuple(G.energy(gamma) for G in Gs))
        self.entropy = numpy.mean(tuple(G.entropy for G in Gs))

        self.I       = numpy.mean(Is)
        self.VI      = VI
        self.In      = In

        self.N       = N = Gs[0].N
        self.n_mean  = sum(tuple(item[0]*item[1]/float(G.q) for G in Gs for 
                                 item in G.n_counts().items())) / ( float(len(Gs)) )

        n_counts=[]
        histdata=tuple(item for G in Gs for item in G.n_counts().items())
        for number,count in histdata:
            n_counts=n_counts+[number]*count
        n_counts= sorted(n_counts) 
     
        edges=numpy.logspace(0,numpy.log10(N+1),num=nhistbins,endpoint=True)
        self.n_hist,self.n_hist_edges = numpy.histogram(n_counts, bins=edges)

from util import LogInterval

class MultiResolution(object):
    """Class to do full multi-resolution analysis.
    """
    _output = None
    _lock = None
    def __init__(self, low, high, callback=None, number=10,
                 output=None, ):
        """Create a multiresolution helper system.

        `low`, `high`: lowest and highest gammas to use.

        `callback`: a callback to run with the optimum configuration
        after each gamma run.

        `number`: resoluation of gammas, there are this many gammas
        logarithmically distributed over each order of magnitude.

        `output`: save table of gamma, q, H, etc, to this file.
        """
        self._li = li = LogInterval(number=number)
        self.indexLow  = int(floor(li.index(low )))
        self.indexHigh = int(ceil (li.index(high)))
        self.callback = callback
        self._output = output

        self._data = { } #collections.defaultdict(dict)
    def _do_gammaindex(self, index):
        """Worker thread for gammas.

        For one index, look up the respective gamma and do that analysis.
        """
        gamma = self._li.value(index)
        minGs = [ ]
        for G in self._Gs:
            if self._lock:  self._lock.acquire()
            G = G.copy()
            if self._lock:  self._lock.release()
            G.minimize_trials(gamma, trials=self.trials)
            minGs.append(G)

        # Do the information theory VI, MI, In, etc, stuff on our
        # minimized replicas.
        self._data[index] = MultiResolutionCorrelation(gamma, minGs)
        # Save output to a file.
        if self._output is not None and self._writelock.acquire(False):
            self.write(self._output)
            self._writelock.release()
        # Run callback if we have it.
        if self.callback:
            totalminimum = min(minGs, key=lambda x: G.energy(gamma))
            self.callback(G=totalminimum, gamma=gamma,
                          mrc=self._data[index])
    def _thread(self):
        """Thread worker - do gammas until all are exhausted.

        One of these are spawned for each thread, they run until all
        gammas have been finished."""
        try:
            while True:
                index = self._queue.get_nowait()
                self._do_gammaindex(index)
                self._queue.task_done()
        except self._Empty:
            return
    def do(self, Gs, trials=10, threads=1):
        """Do multi-resolution analysis on replicas Gs with `trials` each."""
        # If multiple threads requested, do that version instead:
        if threads > 1:
            return self.do_mt(Gs, trials=trials, threads=threads)

        # Non threaded version:
        self._Gs = Gs
        self.replicas = len(Gs)
        self.trials = trials
        for index in range(self.indexLow, self.indexHigh+1):
            self._do_gammaindex(index)
            if self._output:
                self.write(output)

    def do_mt(self, Gs, trials=10, threads=2):
        """Do multi-resolution analysis on replicas Gs with `trials` each.

        Multi-threaded version."""
        self._Gs = Gs
        self.replicas = len(Gs)
        self.trials = trials

        import threading
        import Queue
        self._Empty = Queue.Empty
        self._lock = threading.Lock()
        self._writelock = threading.Lock()
        self._queue = Queue.Queue()

        for index in range(self.indexLow, self.indexHigh+1):
            self._queue.put(index)

        threadlst = [ ]
        for tid in range(threads):
            t = threading.Thread(target=self._thread)
            t.daemon = True
            t.start()
            threadlst.append(t)

        self._queue.join()

    def calc(self):
        MRCs = [ MRC for i, MRC in sorted(self._data.iteritems()) ]

        self.N         = N         = MRCs[0].N
        self.gammas    = gammas    = [mrc.gamma     for mrc in MRCs]
        self.qs        = qs        = [mrc.q         for mrc in MRCs]
        self.qmins     = minss     = [mrc.qmin      for mrc in MRCs]
        self.Es        = Es        = [mrc.E         for mrc in MRCs]
        self.entropies = entropies = [mrc.entropy   for mrc in MRCs]

        self.Is        = Is        = [mrc.I         for mrc in MRCs]
        self.VIs       = VIs       = [mrc.VI        for mrc in MRCs]
        self.Ins       = Ins       = [mrc.In        for mrc in MRCs]
   
        self.n_mean    = n_mean    = [mrc.n_mean    for mrc in MRCs]

        self.n_hist       = n_hist       = [mrc.n_hist       for mrc in MRCs]
        self.n_hist_edges = n_hist_edges = [mrc.n_hist_edges for mrc in MRCs]

        self.field_names = ("gammas", "qs", "Es", "entropies",
                            "Is", "VIs", "Ins", "qmins","n_mean")
    def write(self, fname):
        """Save multi-resolution data to a file."""
        self.calc()
        f = open(fname, 'w')
        print >> f, "#", time.ctime()
        print >> f, "# replicas:", self.replicas
        print >> f, "# trials per replica:", self.trials
        print >> f, "#" + " ".join(self.field_names)
        for i in range(len(self.gammas)):
            for name in self.field_names:
                print >> f, getattr(self, name)[i],
            print >> f

    def plot_nhists(self, fname):
        from matplotlib.backends.backend_agg import Figure, FigureCanvasAgg
        from matplotlib.backends.backend_pdf import PdfPages
        f = Figure()
        c = FigureCanvasAgg(f)

        ax  = f.add_subplot(111)
        pp = PdfPages(fname)

        for i in range(len(self.n_hist)):
            histdata=self.n_hist[i]
            histedges=self.n_hist_edges[i]
            ax.cla()
            ax.set_title("$\gamma=%f$"%self.gammas[i])
            ax.bar( histedges[:-1], histdata, width=(histedges[1:]-histedges[:-1]) )
            ax.set_xscale('log')
            ax.set_xlim( 0.1 , self.N )
            pp.savefig(f)

        pp.close()

    def plot_nmean(self, fname=None):
        if fname:
            from matplotlib.backends.backend_agg import Figure, FigureCanvasAgg
            f = Figure()
            c = FigureCanvasAgg(f)
        else:
            from matplotlib import pyplot
            f = pyplot.gcf()

        ax_vi  = f.add_subplot(111)
        ax_vi.set_xscale('log')
        ax_n = ax_vi.twinx()

        l2 = ax_vi.plot(self.gammas, self.VIs,
                        color='blue')
        l3 = ax_vi.plot(self.gammas, self.Ins, '--',
                        color='red')
        l = ax_n.plot(self.gammas, self.n_mean,':',c='black')

        ax_n.legend((l2, l3,l), ("$VI$", "$I_n$","$\langle n \\rangle$"), loc=0)
        ax_n.set_ylabel('$\langle n \\rangle$')
        ax_n.set_yscale('log')
#        ax_n.set_ylim(bottom=0)

        ax_vi.set_ylabel('$VI$ and $I_n$')
        ax_vi.set_xlabel('$\gamma$')

        if fname:
            c.print_figure(fname, bbox_inches='tight')

    def plot(self, fname=None):
        if fname:
            from matplotlib.backends.backend_agg import Figure, FigureCanvasAgg
            f = Figure()
            c = FigureCanvasAgg(f)
        else:
            from matplotlib import pyplot
            f = pyplot.gcf()
        #ax = f.add_subplot(111)
        #ax.plot(array[:,0], array[:,1]/50., label="q")
        #ax.set_xscale('log')

        ax_vi  = f.add_subplot(111)
        ax_vi.set_xscale('log')
        ax_q = ax_vi.twinx()

        #old style. next is q on left, vi on right
        #ax_q  = f.add_subplot(111)
        #ax_vi = ax_q.twinx()

        #from fitz import interactnow
        l2 = ax_vi.plot(self.gammas, self.VIs,
                        color='blue')
        l3 = ax_vi.plot(self.gammas, self.Ins, '--',
                        color='red')
        l = ax_q.plot(self.gammas, self.qs,':',c='black')

        ax_q.legend((l2, l3,l), ("$VI$", "$I_n$","$q$"), loc=0)
        ax_q.set_ylabel('$q$')
        ax_q.set_ylim(bottom=0)

        ax_vi.set_ylabel('$VI$ and $I_n$')
        ax_vi.set_xlabel('$\gamma$')

        if fname:
            c.print_figure(fname, bbox_inches='tight')

    def viz(self):
        import matplotlib.pyplot as pyplot
        gammas    = self.gammas
        qs        = self.qs
        Es        = self.Es
        entropies = self.entropies

        Is        = self.Is
        VIs       = self.VIs
        Ins       = self.Ins
        pyplot.xlim(gammas[0], gammas[-1])
        pyplot.semilogx(gammas, qs)
        pyplot.xlabel('\gamma')
        pyplot.ylabel('q')
        #pyplot.show()
        pyplot.ion()
        from fitz import interactnow




if __name__ == "__main__":
    command = None
    if len(sys.argv) > 1:
        command = sys.argv[1]

    if command == "test":

        random.seed(169)
        G = random_graph(size=20, layout=True)
        random.seed(time.time())
        G.cmtyCreate()
        G.check()
        #G.test()
        G.minimize(gamma=1.0)
        #G.remapCommunities()
        #G.remapCommunities()
        #G.check()
        G.viz()

    if command == "multi":
        Gs = [ random_graph(size=20) for _ in range(10) ]
        M = MultiResolution(low=.01, high=100)
        M.do(Gs=Gs, trials=3)
        M.print_()
