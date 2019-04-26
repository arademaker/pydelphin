
"""
Elementary Dependency Structures (EDS).
"""

from typing import Iterable

from delphin.lnk import Lnk
from delphin.sembase import Predication, SemanticStructure

BOUND_VARIABLE_ROLE     = 'BV'
PREDICATE_MODIFIER_ROLE = 'ARG1'


##############################################################################
##############################################################################
# EDS classes

class Node(Predication):
    """
    An EDS node.

    Args:
        id: node identifier
        predicate: semantic predicate
        type: node type (corresponds to the intrinsic variable type in MRS)
        edges: mapping of outgoing edge roles to target identifiers
        properties: morphosemantic properties
        carg: constant value (e.g., for named entities)
        lnk: surface alignment
        surface: surface string
        base: base form
    Attributes:
        id: node identifier
        predicate: semantic predicate
        type: node type (corresponds to the intrinsic variable type in MRS)
        edges: mapping of outgoing edge roles to target identifiers
        properties: morphosemantic properties
        carg: constant value (e.g., for named entities)
        lnk: surface alignment
        cfrom: surface alignment starting position
        cto: surface alignment ending position
        surface: surface string
        base: base form
    """

    __slots__ = ('type', 'edges', 'properties', 'carg')

    def __init__(self,
                 id: int,
                 predicate: str,
                 type: str = None,
                 edges: dict = None,
                 properties: dict = None,
                 carg: str = None,
                 lnk: Lnk = None,
                 surface=None,
                 base=None):

        if not edges:
            edges = {}
        if not properties:
            properties = {}

        super().__init__(id, predicate, lnk, surface, base)

        self.type = type
        self.edges = edges
        self.properties = properties
        self.carg = carg

    def __eq__(self, other):
        if not isinstance(other, Node):
            return NotImplemented
        return (self.predicate == other.predicate
                and self.type == other.type
                and self.edges == other.edges
                and self.properties == other.properties
                and self.carg == other.carg)


class EDS(SemanticStructure):
    """
    An Elementary Dependency Structure (EDS) instance.

    EDS are semantic structures deriving from MRS, but they are not
    interconvertible with MRS as the do not encode a notion of
    quantifier scope.

    Args:
        top: the id of the graph's top node
        nodes: an iterable of EDS nodes
        lnk: surface alignment
        surface: surface string
        identifier: a discourse-utterance identifier
    """

    __slots__ = ()

    def __init__(self,
                 top: str = None,
                 nodes: Iterable[Node] = None,
                 lnk: Lnk = None,
                 surface=None,
                 identifier=None):
        super().__init__(top, nodes, lnk, surface, identifier)

    @property
    def nodes(self):
        """Alias of :attr:`predications`."""
        return self.predications

    def edges(self):
        """Return the list of all edges."""
        edges = []
        for node in self.nodes:
            edges.append((node.id, role, target)
                         for role, target in node.edges.items())
        return edges

    ## SemanticStructure methods

    def arguments(self, types=None):
        args = {}
        if types is not None:
            ntypes = {node.id: node.type for node in self.nodes}
        else:
            ntypes = {}
        for node in self.nodes:
            for role, target in node.edges.items():
                if types is None or ntypes.get(target) in types:
                    args.setdefault(node.id, {})[role] = target
        return args

    def properties(self, id):
        return self[id].properties

    def is_quantifier(self, id):
        """
        Return `True` if *id* is the id of a quantifier node.
        """
        return BOUND_VARIABLE_ROLE in self[id].edges
