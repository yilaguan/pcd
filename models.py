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

import networkx as nx


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
        attribute `weight` which is set to the

        `defaultweight` is the weight for all not explicitely defined
        pairs of nodes.  Note that positive weight is repulsive and
        negative weight is attractive.
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
        G.interactions[:] = defaultweight
        # Default diagonal weighting
        if diagonalweight is not None:
            for i in range(G.N):
                G.interactions[i, i] = diagonalweight
        # All explicit weighting from the graph
        for n0 in graph.nodes():
            for n1 in graph.neighbors(n0):
                i0 = graph.node[n0]['index']
                i1 = graph.node[n1]['index']
                G.interactions[i0,i1] = graph[n0][n1]['weight']
        # Check that the matrix is symmetric (FIXME someday: directed graphs)
        if not numpy.all(G.interactions == G.interactions.T):
            print "Note: interactions matrix is not symmetric"
        return G

    def _fillStruct(self, N=None):
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
        self._allocArray("interactions", shape=(N, N))

    def __getstate__(self):
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
        # make actual deep copies of all the arrays.
        new = pickle.loads(pickle.dumps(self, -1))
        #new._allocArray('interactions', array=self.interactions)
        return new

    def cmtyCreate(self, cmtys=None, randomize=True):
        """Create initial communities for a model.

        By default, arrays are initialized to one particle per
        community, in random order.

        cmtys=<array of length nNodes>: initialize for this initial
        array

        randomize=<bool>: if initial cmtys array is not given, should
        the innitial array be range(nNodes), or should it be randomized?
        """
        if cmtys:
            pass
        else:
            cmtys = numpy.arange(self.N)
            if randomize:
                numpy.random.shuffle(cmtys)
        self.Ncmty = numpy.max(cmtys)+1
        self.cmty[:] = cmtys
        #self.cmtyN[:] = 1   # done in cmtyListInit()
        self.cmtyListInit()
    def cmtyListInit(self):
        """Initialize community list.

        The community list (self.cmtyll[community_index, ...]) is a
        data structure optimized for the community lookups.  This
        function fills self.cmtyll from self.cmty[i].
        """
        print "cmtyListInit"
        cmodels.cmtyListInit(self._struct_p)
    def cmtyListCheck(self):
        print "cmtyListCheck"
        errors = cmodels.cmtyListCheck(self._struct_p)
        assert errors == 0, "We have %d errors"%errors
        assert self.q == len(set(self.cmty))
        return errors
    check = cmtyListCheck
    def cmtySet(self, n, c):
        """Set the community of a particle"""
        raise NotImplementedError("cmtySet not implemented yet.")
    def randomizeOrder(self, randomize=True):
        if not randomize:
            # Fake mode: actually sort them
            numpy.sort(self.randomOrder)  # FIXME
            numpy.sort(self.randomOrder2) # FIXME
        else:
            numpy.random.shuffle(self.randomOrder)  # FIXME
            numpy.random.shuffle(self.randomOrder2) # FIXME
        #print self.randomOrder
        #print self.randomOrder2

    def viz(self):
        """Visualize the detected communities (requires NetworkX rep)
        """
        print "vizing"
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
            print a,b,weight
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
        nx.draw(g,
                node_color=[colorMap[c] for c in cmtys],
                edge_color=[d.get('color', 'green') for a,b,d in g.edges(data=True)],
                width=[d.get('width', 1) for a,b,d in g.edges(data=True)],
                node_size=900,
                labels = dict((n, "%s (%s)"%(n, c))
                              for (n, c) in zip(g.nodes(), cmtys)),
                pos=self._layout)
        #plt.margins(tight=True)
        plt.show()
        return g

    def energy(self, gamma):
        """Return total energy of the graph."""
        return cmodels.energy(self._struct_p, gamma)
    def energy_cmty(self, gamma, c):
        """Return energy due to community c."""
        return cmodels.energy_cmty(self._struct_p, gamma, c)
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
    @property
    def entropy(self):
        """Return the entropy of this graph.
        """
        N = float(self.N)
        H = sum( (n/N)*log2(n/N)  for n in self.cmtyN
                 if n!=0 )
        return -H

    def minimize(self, gamma):
        """Minimize the communities at a certain gamma.

        This function requires a good starting configuration.  To do
        that, use self.cmtyCreate() first.
        """
        print "beginning minimization (n=%s, gamma=%s)"%(self.N, gamma)

        changesCombining = None
        for round_ in itertools.count():
            self.randomizeOrder()
            changes = self._minimize(gamma=gamma)
            print "  (r%2s) cmtys, changes: %4d %4d"%(round_, self.q, changes)

            if changes == 0 and changesCombining == 0:
                break

            # If we got no changes, then try combining communities
            # before breaking out.
            if changes == 0:
                changesCombining = self.combine_cmtys(gamma=gamma)
                print "  (r%2s) cmtys, changes: %4d %4d"%(
                                           round_, self.q, changesCombining), \
                      "(<-- combining communities)"

                self.remapCommunities(check=False)
            # If we have no changes in regular and combinations, escape
            if changes == 0 and changesCombining == 0:
                break
            if round_ > 100:
                print "  Exceeding maximum number of rounds."
                break
        #print set(self.cmty),
    def _minimize(self, gamma):
        return cmodels.minimize(self._struct_p, gamma)
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
            self.cmtyListCheck()
    def remapCommunities_c(self, check=True):
        print "        remapping communities: ",
        changes = cmodels.remap_cmtys(self._struct_p)
        print changes, "changes"
        if check:
            self.cmtyListCheck()
    remapCommunities = remapCommunities_c

    def _test(self):
        return cmodels.test(self._struct_p)
    def make_networkx(self, ignore_values=()):
        """Return a networkX representation of the interaction matrix.

        This could be useful where """

        g = util.networkx_from_matrix(self.interactions,
                                      ignore_values=ignore_values)
        return g

class MultiResolutionCorrelation(object):
    def __init__(self, gamma, Gs):
        pairs = [ ]
        for i, G0 in enumerate(Gs):
            for j, G1 in enumerate(Gs[i+1:]):
                pairs.append((G0, G1))

        Is = [ util.mutual_information(G0,G1) for G0,G1 in pairs ]

        VI = numpy.mean([G0.entropy + G1.entropy - 2*mi
                         for ((G0,G1), mi) in zip(pairs, Is)])
        In = numpy.mean([2*mi / (G0.entropy + G1.entropy)
                         for ((G0,G1), mi) in zip(pairs, Is)])

        self.gamma   = gamma
        self.q       = numpy.mean(tuple(G.q for G in Gs))
        self.qmin    = min(G.q for G in Gs)
        self.E       = numpy.mean(tuple(G.energy(gamma) for G in Gs))
        self.entropy = numpy.mean(tuple(G.entropy for G in Gs))

        self.I       = numpy.mean(Is)
        self.VI      = VI
        self.In      = In

class MultiResolution(object):
    """Class to do full multi-resolution analysis.
    """
    _output = None
    _lock = None
    def __init__(self, low, high, callback=None):
        """
        """
        self.indexLow  = int(floor(util.logTimeIndex(low )))
        self.indexHigh = int(ceil (util.logTimeIndex(high)))
        self.callback = callback

        self._data = { } #collections.defaultdict(dict)
    def _do_gammaindex(self, index):
        gamma = util.logTime(index)
        #minima = [ ]
        minGs = [ ]
        for G in self._Gs:
            if self._lock:  self._lock.acquire()
            G = G.copy()
            if self._lock:  self._lock.release()
            minE = float('inf')
            minG = None
            for i in range(self.trials):
                G.cmtyCreate() # randomizes it
                G.minimize(gamma)
                if minG is None:
                    minE = G.energy
                    minG = G.copy()
                elif G.energy < minE:
                    minE = G.energy
                    minG = G.copy()
            minGs.append(minG)
        self._data[index] = MultiResolutionCorrelation(gamma, minGs)
        if self._output is not None and self._writelock.acquire(False):
            self.write(self._output)
            self._writelock.release()
        if self.callback:
            totalminimum = min(minGs, key=lambda x: G.energy)
            self.callback(G=totalminimum, gamma=gamma,
                          mrc=self._data[index])
    def _thread(self):
        """Thread worker - do gammas until all are exhausted."""
        try:
            while True:
                index = self._queue.get_nowait()
                self._do_gammaindex(index)
                self._queue.task_done()
        except self._Empty:
            return
    def do(self, Gs, trials=10, output=None, threads=1):
        """Do multi-resolution analysis on replicas Gs with `trials` each."""
        if threads > 1:
            return self.do_mt(Gs, trials=trials, output=output, threads=threads)


        self._Gs = Gs
        self.replicas = len(Gs)
        self.trials = trials
        for index in range(self.indexLow, self.indexHigh+1):
            self._do_gammaindex(index)
            if output:
                self.write(output)

    def do_mt(self, Gs, trials=10, output=None, threads=2):
        """Do multi-resolution analysis on replicas Gs with `trials` each.

        Multi-threaded version"""
        self._Gs = Gs
        self.replicas = len(Gs)
        self.trials = trials

        import threading
        import Queue
        self._Empty = Queue.Empty
        self._lock = threading.Lock()
        self._writelock = threading.Lock()
        self._queue = Queue.Queue()
        self._output = output

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

        self.gammas    = gammas    = [mrc.gamma     for mrc in MRCs]
        self.qs        = qs        = [mrc.q         for mrc in MRCs]
        self.qmins     = minss     = [mrc.qmin      for mrc in MRCs]
        self.Es        = Es        = [mrc.E         for mrc in MRCs]
        self.entropies = entropies = [mrc.entropy   for mrc in MRCs]

        self.Is        = Is        = [mrc.I         for mrc in MRCs]
        self.VIs       = VIs       = [mrc.VI        for mrc in MRCs]
        self.Ins       = Ins       = [mrc.In        for mrc in MRCs]
        self.field_names = ("gammas", "qs", "Es", "entropies",
                            "Is", "VIs", "Ins", "qmins")
    def write(self, fname):
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
        G.cmtyListCheck()
        #G.test()
        G.minimize(gamma=1.0)
        #G.remapCommunities()
        #G.remapCommunities()
        #G.cmtyListCheck()
        G.viz()

    if command == "multi":
        Gs = [ random_graph(size=20) for _ in range(10) ]
        M = MultiResolution(low=.01, high=100)
        M.do(Gs=Gs, trials=3)
        M.print_()
