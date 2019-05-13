# -*- coding: utf-8 -*-

"""
EDS-PENMAN serialization and deserialization.

Example:

* *The new chef whose soup accidentally spilled quit and left.*

::

  (e18 / _quit_v_1
    :lnk "<45:49>"
    :type e
    :sf prop
    :tense past
    :mood indicative
    :prog -
    :perf -
    :ARG1 (x3 / _chef_n_1
      :lnk "<8:12>"
      :type x
      :pers 3
      :num sg
      :ind +
      :BV-of (_1 / _the_q
        :lnk "<0:3>"
        :type x
        :pers 3
        :num sg
        :ind +)
      :ARG1-of (e8 / _new_a_1
        :lnk "<4:7>"
        :type e
        :sf prop
        :tense untensed
        :mood indicative
        :prog bool
        :perf -)
      :ARG2-of (e14 / poss
        :lnk "<13:18>"
        :type e
        :sf prop
        :tense untensed
        :mood indicative
        :prog -
        :perf -
        :ARG1 (x10 / _soup_n_1
          :lnk "<19:23>"
          :type x
          :pers 3
          :num sg
          :BV-of (_2 / def_explicit_q
            :lnk "<13:18>"
            :type x
            :pers 3
            :num sg)
          :ARG1-of (e16 / _spill_v_1
            :lnk "<37:44>"
            :type e
            :sf prop
            :tense past
            :mood indicative
            :prog -
            :perf -
            :ARG1-of (e15 / _accidental_a_1
              :lnk "<24:36>"
              :type e
              :sf prop
              :tense untensed
              :mood indicative
              :prog -
              :perf -)))))
    :ARG1-of (e2 / _and_c
      :lnk "<50:53>"
      :type e
      :sf prop
      :tense past
      :mood indicative
      :prog -
      :perf -
      :ARG2 (e20 / _leave_v_1
        :lnk "<54:59>"
        :type e
        :sf prop
        :tense past
        :mood indicative
        :prog -
        :perf -
        :ARG1 x3)))

"""

import penman

from delphin.lnk import Lnk
from delphin.sembase import (role_priority, property_priority)
from delphin.eds import (EDS, Node)


def load(source):
    """
    Deserialize a EDS-PENMAN file (handle or filename) to EDS objects.

    Args:
        source: filename or file object
    Returns:
        a list of EDS objects
    """
    graphs = penman.load(source)
    xs = [from_triples(g.triples()) for g in graphs]
    return xs


def loads(s):
    """
    Deserialize a EDS-PENMAN string to EDS objects.

    Args:
        s (str): a EDS-PENMAN string
    Returns:
        a list of EDS objects
    """
    graphs = penman.loads(s)
    xs = [from_triples(g.triples()) for g in graphs]
    return xs


def dump(es, destination, properties=True, lnk=True,
         indent=False, encoding='utf-8'):
    """
    Serialize EDS objects to a EDS-PENMAN file.

    Args:
        destination: filename or file object
        es: iterator of :class:`~delphin.eds.EDS` objects to
            serialize
        properties: if `True`, encode variable properties
        lnk: if `False`, suppress surface alignments and strings
        indent: if `True`, adaptively indent; if `False` or `None`,
            don't indent; if a non-negative integer N, indent N spaces
            per level
        encoding (str): if *destination* is a filename, write to the
            file with the given encoding; otherwise it is ignored
    """
    text = dumps(es, properties=properties, lnk=lnk, indent=indent)
    if hasattr(destination, 'write'):
        print(text, file=destination)
    else:
        with open(destination, 'w', encoding=encoding) as fh:
            print(text, file=fh)


def dumps(es, properties=True, lnk=True, indent=False):
    """
    Serialize EDS objects to a EDS-PENMAN string.

    Args:
        es: iterator of :class:`~delphin.eds.EDS` objects to
            serialize
        properties: if `True`, encode variable properties
        lnk: if `False`, suppress surface alignments and strings
        indent: if `True`, adaptively indent; if `False` or `None`,
            don't indent; if a non-negative integer N, indent N spaces
            per level
    Returns:
        a EDS-PENMAN-serialization of the EDS objects
    """
    codec = penman.PENMANCodec()
    to_graph = codec.triples_to_graph
    graphs = [to_graph(to_triples(e, properties=properties, lnk=lnk))
              for e in es]
    return penman.dumps(graphs, indent=indent)


def decode(s):
    """
    Deserialize a EDS object from a EDS-PENMAN string.
    """
    return from_triples(penman.decode(s).triples())


def encode(eds, properties=True, lnk=True, indent=False):
    """
    Serialize a EDS object to a EDS-PENMAN string.

    Args:
        e: a EDS object
        properties (bool): if `False`, suppress variable properties
        lnk: if `False`, suppress surface alignments and strings
        indent (bool, int): if `True` or an integer value, add
            newlines and indentation
    Returns:
        a EDS-PENMAN-serialization of the EDS object
    """
    triples = to_triples(eds, properties=properties, lnk=lnk)
    g = penman.PENMANCodec().triples_to_graph(triples)
    return penman.encode(g, indent=indent)


def to_triples(e, properties=True, lnk=True):
    """
    Encode the Eds as triples suitable for PENMAN serialization.
    """
    # attempt to convert if necessary
    if not isinstance(e, EDS):
        e = EDS.from_xmrs(e)

    triples = []
    # sort node ids just so top var is first
    nodes = sorted(e.nodes, key=lambda n: n.id != e.top)
    for node in nodes:
        nid = node.id
        triples.append((nid, 'instance', node.predicate))
        if lnk and node.lnk:
            triples.append((nid, 'lnk', '"{}"'.format(str(node.lnk))))
        if node.carg:
            triples.append((nid, 'carg', '"{}"'.format(node.carg)))
        if node.type is not None:
            triples.append((nid, 'type', node.type))
        if properties:
            for prop in sorted(node.properties, key=property_priority):
                triples.append((nid, prop.lower(), node.properties[prop]))
        for role in sorted(node.edges, key=role_priority):
            triples.append((nid, role, node.edges[role]))
    return triples


def from_triples(triples):
    """
    Decode triples, as from :func:`to_triples`, into an EDS object.
    """
    nids, nd, edges = [], {}, []
    for src, rel, tgt in triples:
        if src not in nd:
            nids.append(src)
            nd[src] = {'pred': None, 'type': None, 'edges': {},
                       'props': {}, 'lnk': None, 'carg': None}
        if rel == 'predicate':
            nd[src]['pred'] = tgt
        elif rel == 'lnk':
            nd[src]['lnk'] = Lnk(tgt.strip('"'))
        elif rel == 'carg':
            if (tgt[0], tgt[-1]) == ('"', '"'):
                tgt = tgt[1:-1]
            nd[src]['carg'] = tgt
        elif rel == 'type':
            nd[src]['type'] = tgt
        elif rel.islower():
            nd[src]['props'][rel.upper()] = tgt
        else:
            nd[src]['edges'][rel] = tgt
    nodes = [Node(nid,
                  nd[nid]['pred'],
                  type=nd[nid]['type'],
                  edges=nd[nid]['edges'],
                  properties=nd[nid]['props'],
                  carg=nd[nid]['carg'],
                  lnk=nd[nid]['lnk'])
             for nid in nids]
    top = nids[0] if nids else None
    return EDS(top=top, nodes=nodes)