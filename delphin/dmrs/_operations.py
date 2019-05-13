
"""
Operations on DMRS structures
"""

from delphin import variable
from delphin import scope
from delphin import dmrs


def from_mrs(m):
    """
    Create a DMRS by converting from MRS *m*.

    In order for MRS to DMRS conversion to work, the MRS must satisfy
    the intrinsic variable property (see
    :func:`delphin.mrs.has_intrinsic_variable_property`).

    Args:
        m: the input MRS
    Returns:
        DMRS
    Raises:
        DMRSError when conversion fails.
    """
    hcmap = {hc.hi: hc for hc in m.hcons}
    reps = scope.representatives(m)
    # EP id to node id map; create now to keep ids consistent
    id_to_nid = {ep.id: i for i, ep in enumerate(m.rels, dmrs.FIRST_NODE_ID)}
    iv_to_nid = {ep.iv: id_to_nid[ep.id]
                 for ep in m.rels if not ep.is_quantifier()}

    top = _mrs_get_top(m.top, hcmap, reps, id_to_nid)
    index = iv_to_nid[m.index] if m.index else None
    nodes = _mrs_to_nodes(m, id_to_nid)
    links = _mrs_to_links(m, hcmap, reps, iv_to_nid, id_to_nid)

    return dmrs.DMRS(
        top=top,
        index=index,
        nodes=nodes,
        links=links,
        lnk=m.lnk,
        surface=m.surface,
        identifier=m.identifier)


def _mrs_get_top(top, hcmap, reps, id_to_nid):
    if top in hcmap:
        lbl = hcmap[top].lo
        rep = reps[lbl][0]
        top = id_to_nid[rep]
    elif top in reps:
        rep = reps[top][0]
        top = id_to_nid[rep]
    return top


def _mrs_to_nodes(m, id_to_nid):
    nodes = []
    for ep in m.rels:
        node_id = id_to_nid[ep.id]
        iv = ep.iv
        properties = None if ep.is_quantifier() else m.properties(ep.iv)
        nodes.append(
            dmrs.Node(node_id,
                      ep.predicate,
                      variable.type(iv),
                      properties,
                      ep.carg,
                      ep.lnk,
                      ep.surface,
                      ep.base))
    return nodes


def _mrs_to_links(m, hcmap, reps, iv_to_nid, id_to_nid):
    links = []
    # links from arguments
    for src, roleargs in m.arguments().items():
        start = id_to_nid[src]
        for role, tgt in roleargs.items():
            # non-scopal arguments
            if tgt in iv_to_nid:
                end = iv_to_nid[tgt]
                if m[src].label == m[tgt].label:
                    post = dmrs.EQ_POST
                else:
                    post = dmrs.NEQ_POST
            # scopal arguments
            elif tgt in reps and len(reps[tgt]) > 0:
                tgt = reps[tgt][0]
                end = id_to_nid[tgt]
                post = dmrs.HEQ_POST
            elif tgt in hcmap:
                lo = hcmap[tgt].lo
                tgt = reps[lo][0]
                end = id_to_nid[tgt]
                post = dmrs.H_POST
            # other (e.g., BODY, dropped arguments, etc.)
            else:
                continue
            links.append(dmrs.Link(start, end, role, post))
    # MOD/EQ links for shared labels without argumentation
    for label, ids in reps.items():
        if len(ids) > 1:
            end = id_to_nid[ids[0]]
            for src in ids[1:]:
                start = id_to_nid[src]
                links.append(
                    dmrs.Link(start, end, dmrs.BARE_EQ_ROLE, dmrs.EQ_POST))
    return links