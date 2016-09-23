
import re

from delphin.mrs.components import sort_vid_split

_LR_OPS = set(['<>', '>>', '==', '=>'])
_RL_OPS = set(['<>', '<<', '==', '<='])
_SUBSUME_OPS = set(['<>', '<<', '>>'])
_EQUAL_OPS = set(['==', '<=', '=>'])


def load(fh, semi=None):
    typemap = []
    propmap = []
    curmap = typemap
    lh, rh = 1, 1  # number of elements expected on each side
    for line in fh:
        line = line.lstrip()

        if not line or line.startswith(';'):
            continue

        match = re.match(r'(?P<lfeats>[^:]+):(?P<rfeats>.+)', line)
        if match is not None:
            lfeats = match.group('lfeats').split()
            rfeats = match.group('rfeats').split()
            lh, rh = len(lfeats), len(rfeats)
            curmap = []
            propmap.append(((lfeats, rfeats), curmap))
            continue

        match = re.match(r'(?P<lvals>.*)(?P<op>[<>=]{2})(?P<rvals>.*)$', line)
        if match is not None:
            lvals = match.group('lvals').split()
            rvals = match.group('rvals').split()
            assert len(lvals) == lh
            assert len(rvals) == rh
            curmap.append((lvals, match.group('op'), rvals))
            continue

        raise ValueError('Invalid line in VPM file: {}'.format(line))

    return Vpm(typemap, propmap, semi)

class Vpm(object):
    def __init__(self, typemap, propmap, semi=None):
        self._typemap = typemap  # [(src, OP, tgt)]
        self._propmap = propmap  # [((srcfs, tgtfs), [(srcvs, OP, tgtvs)])]
        self._semi = semi

    def apply(self, var, props, reverse=False):
        vs, vid = sort_vid_split(var)
        if reverse:
            # variable type mapping is disabled in reverse
            # tms = [(b, op, a) for a, op, b in self._typemap if op in _RL_OPS]
            tms = []
        else:
            tms = [(a, op, b) for a, op, b in self._typemap if op in _LR_OPS]
        for src, op, tgt in tms:
            if _valmatch([vs], src, op, None, self._semi, 'variables'):
                vs = vs if tgt == ['*'] else tgt[0]
                break
        newvar = '{}{}'.format(vs, vid)

        newprops = {}
        for featsets, valmap in self._propmap:
            if reverse:
                tgtfeats, srcfeats = featsets
                pms = [(b, op, a) for a, op, b in valmap if op in _RL_OPS]
            else:
                srcfeats, tgtfeats = featsets
                pms = [(a, op, b) for a, op, b in valmap if op in _LR_OPS]
            vals = [props.get(f) for f in srcfeats]
            for srcvals, op, tgtvals in pms:
                if _valmatch(vals, srcvals, op, vs, self._semi, 'properties'):
                    for i, featval in enumerate(zip(tgtfeats, tgtvals)):
                        k, v = featval
                        if v == '*':
                            print(i, len(vals), vals, k, v)
                            if i < len(vals) and vals[i] is not None:
                                newprops[k] = vals[i]
                        elif v != '!':
                            newprops[k] = v
                    break

        return newvar, newprops


def _valmatch(vs, ss, op, varsort, semi, section):
    """
    Return True if for every paired *v* and *s* from *vs* and *ss*:
        v <> s (subsumption or equality if *semi* is `None`)
        v == s (equality)
        s == '*'
        s == '!' and v == `None`
        s == '[xyz]' and varsort == 'xyz'
    """
    if op in _EQUAL_OPS or semi is None:
        return all(
            s == v or  # value equality
            (s == '*' and v is not None) or  # non-null wildcard
            (
                v is None and (  # value is null (any or with matching varsort)
                    s == '!' or
                    (s[0], s[-1], s[1:-1]) == ('[', ']', varsort)
                )
            )
            for v, s in zip(vs, ss)
        )
    else:
        pass
