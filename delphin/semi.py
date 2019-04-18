
"""
Semantic Interface (SEM-I)

Semantic interfaces (SEM-Is) describe the inventory of semantic
components in a grammar, including variables, properties, roles, and
predicates. This information can be used for validating semantic
structures or for filling out missing information in incomplete
representations.

.. seealso::
  The following DELPH-IN wikis contain more information:

  - Technical specifications: http://moin.delph-in.net/SemiRfc
  - Overview and usage: http://moin.delph-in.net/RmrsSemi

"""

import re
from os.path import dirname, join as pjoin
from operator import itemgetter
import warnings

from delphin import tfs
from delphin.exceptions import (
    PyDelphinException,
    PyDelphinSyntaxError,
    PyDelphinWarning
)


TOP_TYPE = '*top*'
STRING_TYPE = 'string'


_SEMI_SECTIONS = (
    'variables',
    'properties',
    'roles',
    'predicates',
)

_variable_entry_re = re.compile(
    r'(?P<var>[^ .]+)'
    r'(?: < (?P<parents>[^ &:.]+(?: & [^ &:.]+)*))?'
    r'(?: : (?P<properties>[^ ]+ [^ ,.]+(?:, [^ ]+ [^ ,.]+)*))?'
    r'\s*\.\s*(?:;.*)?$',
    re.U
)

_property_entry_re = re.compile(
    r'(?P<type>[^ .]+)'
    r'(?: < (?P<parents>[^ &.]+(?: & [^ &.]+)*))?'
    r'\s*\.\s*(?:;.*)?$',
    re.U
)

_role_entry_re = re.compile(
    r'(?P<role>[^ ]+) : (?P<value>[^ .]+)\s*\.\s*(?:;.*)?$',
    re.U
)

_predicate_entry_re = re.compile(
    r'(?P<pred>[^ ]+)'
    r'(?: < (?P<parents>[^ &:.;]+(?: & [^ &:.;]+)*))?'
    r'(?: : (?P<synposis>.*[^ .;]))?'
    r'\s*\.\s*(?:;.*)?$',
    re.U
)

_synopsis_re = re.compile(
    r'\s*(?P<optional>\[\s*)?'
    r'(?P<name>[^ ]+) (?P<value>[^ ,.{\]]+)'
    r'(?:\s*\{\s*(?P<properties>[^ ]+ [^ ,}]+(?:, [^ ]+ [^ ,}]+)*)\s*\})?'
    r'(?(optional)\s*\])'
    r'(?:\s*(?:,\s*|$))',
    re.U
)


class SemIError(PyDelphinException):
    """Raised when loading an invalid SEM-I."""


class SemISyntaxError(PyDelphinSyntaxError):
    """Raised when loading an invalid SEM-I."""


class SemIWarning(PyDelphinWarning):
    """Warning class for questionable SEM-Is."""


def load(fn, encoding='utf-8'):
    """
    Read the SEM-I beginning at the filename *fn* and return the SemI.

    Args:
        fn: the filename of the top file for the SEM-I. Note: this must
            be a filename and not a file-like object.
        encoding (str): the character encoding of the file
    Returns:
        The SemI defined by *fn*
    """

    data = _read_file(fn, dirname(fn), encoding)
    return SemI(**data)


def _read_file(fn, basedir, encoding):
    data = {
        'variables': {},
        'properties': {},
        'roles': {},
        'predicates': {},
    }
    section = None

    for lineno, line in enumerate(open(fn, 'r', encoding=encoding), 1):
        line = line.lstrip()

        if not line or line.startswith(';'):
            continue

        match = re.match(r'(?P<name>[^: ]+):\s*$', line)
        if match is not None:
            name = match.group('name')
            if name not in _SEMI_SECTIONS:
                raise SemISyntaxError(
                    'invalid SEM-I section',
                    filename=fn, lineno=lineno, text=line)
            else:
                section = name
            continue

        match = re.match(r'include:\s*(?P<filename>.+)$', line, flags=re.U)
        if match is not None:
            include_fn = pjoin(basedir, match.group('filename').rstrip())
            include_data = _read_file(
                include_fn, dirname(include_fn), encoding)
            for key, val in include_data['variables'].items():
                _incorporate(data['variables'], key, val, include_fn)
            for key, val in include_data['properties'].items():
                _incorporate(data['properties'], key, val, include_fn)
            for key, val in include_data['roles'].items():
                _incorporate(data['roles'], key, val, include_fn)
            for pred, d in include_data['predicates'].items():
                if pred not in data['predicates']:
                    data['predicates'][pred] = {
                        'parents': [],
                        'synopses': []
                    }
                if d.get('parents'):
                    data['predicates'][pred]['parents'] = d['parents']
                if d.get('synopses'):
                    data['predicates'][pred]['synopses'].extend(d['synopses'])

        elif section == 'variables':
            # e.g. e < i : PERF bool, TENSE tense.
            match = _variable_entry_re.match(line)
            if match is not None:
                identifier = match.group('var')
                supertypes = match.group('parents') or []
                if supertypes:
                    supertypes = supertypes.split(' & ')
                properties = match.group('properties') or []
                if properties:
                    pairs = properties.split(', ')
                    properties = [pair.split() for pair in pairs]
                v = {'parents': supertypes, 'properties': properties}
                # v = type(identifier, supertypes, d)
                _incorporate(data['variables'], identifier, v, fn)
            else:
                raise SemISyntaxError(
                    'invalid variable',
                    filename=fn, lineno=lineno, text=line)

        elif section == 'properties':
            # e.g. + < bool.
            match = _property_entry_re.match(line)
            if match is not None:
                _type = match.group('type')
                supertypes = match.group('parents') or []
                if supertypes:
                    supertypes = supertypes.split(' & ')
                _incorporate(
                    data['properties'], _type, {'parents': supertypes}, fn)
            else:
                raise SemISyntaxError(
                    'invalid property',
                    filename=fn, lineno=lineno, text=line)

        elif section == 'roles':
            # e.g. + < bool.
            match = _role_entry_re.match(line)
            if match is not None:
                role, value = match.group('role'), match.group('value')
                _incorporate(data['roles'], role, {'value': value}, fn)
            else:
                raise SemISyntaxError(
                    'invalid role',
                    filename=fn, lineno=lineno, text=line)

        elif section == 'predicates':
            # e.g. _predicate_n_1 : ARG0 x { IND + }.
            match = _predicate_entry_re.match(line)
            if match is not None:
                pred = match.group('pred')
                if pred not in data['predicates']:
                    data['predicates'][pred] = {
                        'parents': [],
                        'synopses': []
                    }
                sups = match.group('parents')
                if sups:
                    data['predicates'][pred]['parents'] = sups.split(' & ')
                synposis = match.group('synposis')
                roles = []
                if synposis:
                    for rolematch in _synopsis_re.finditer(synposis):
                        d = rolematch.groupdict()
                        propstr = d['properties'] or ''
                        d['properties'] = dict(
                            pair.split() for pair in propstr.split(', ')
                            if pair.strip() != '')
                        d['optional'] = bool(d['optional'])
                        roles.append(d)
                    data['predicates'][pred]['synopses'].append(
                        {'roles': roles})

    return data


def _incorporate(d, key, val, fn):
    if key in d:
        warnings.warn("'{}' redefined in {}".format(key, fn), SemIWarning)
    d[key] = val


class SynopsisRole(tuple):
    """
    Role data associated with a SEM-I predicate synopsis.

    Args:
        name (str): the role name
        value (str): the role value (variable type or `"string"`)
        properties (dict): properties associated with the role's value
        optional (bool): a flag indicating if the role is optional
    Example:

    >>> role = SynopsisRole('ARG0', 'x', {'PERS': '3'}, False)
    """

    name = property(itemgetter(0), doc='The role name.')
    value = property(
        itemgetter(1), doc='The role value (variable type or "string"')
    properties = property(itemgetter(2), doc='Property-value map.')
    optional = property(itemgetter(3), doc="`True` if the role is optional.")

    def __new__(cls, name, value, properties=None, optional=False):
        if not properties:
            properties = {}
        else:
            properties = {prop.upper(): val.lower()
                          for prop, val in dict(properties).items()}
        return super().__new__(cls, ([name.upper(),
                                      value.lower(),
                                      properties,
                                      bool(optional)]))

    def __repr__(self):
        return 'SynopsisRole({}, {}, {}, {})'.format(
            self.name, self.value, self.properties, self.optional)

    def _to_dict(self):
        d = {"name": self.name, "value": self.value}
        if self.properties:
            d['properties'] = dict(self.properties)
        if self.optional:
            d['optional'] = True
        return d

    @classmethod
    def _from_dict(cls, d):
        return cls(d['name'],
                   d['value'],
                   d.get('properties', []),
                   d.get('optional', False))


class Synopsis(tuple):
    """
    A SEM-I predicate synopsis.

    A synopsis describes the roles of a predicate in a semantic
    structure, so it is no more than a tuple of roles as
    :class:`SynopsisRole` objects. The length of the synopsis is thus
    the arity of a predicate while the individual role items detail
    the role names, argument types, associated properties, and
    optionality.
    """

    def __repr__(self):
        return 'Synopsis([{}])'.format(', '.join(map(repr, self)))

    @classmethod
    def from_dict(cls, d):
        """
        Create a Synopsis from its dictionary representation.

        Example:

        >>> synopsis = Synopsis.from_dict({
        ...     'roles': [
        ...         {'name': 'ARG0', 'value': 'e'},
        ...         {'name': 'ARG1', 'value': 'x',
        ...          'properties': {'NUM': 'sg'}}
        ...     ]
        ... })
        ...
        >>> len(synopsis)
        2
        """
        return cls(SynopsisRole._from_dict(role)
                   for role in d.get('roles', []))

    def to_dict(self):
        """
        Return a dictionary representation of the Synopsis.

        Example:

        >>> Synopsis([
        ...     SynopsisRole('ARG0', 'e'),
        ...     SynopsisRole('ARG1', 'x', {'NUM': 'sg'})
        ... ]).to_dict()
        {'roles': [{'name': 'ARG0', 'value': 'e'},
                   {'name': 'ARG1', 'value': 'x',
                    'properties': {'NUM': 'sg'}}]}
        """

        return {'roles': [role._to_dict() for role in self]}


class SemI(object):
    """
    A semantic interface.

    SEM-Is describe the semantic inventory for a grammar. These include
    the variable types, valid properties for variables, valid roles
    for predications, and a lexicon of predicates with associated roles.

    Args:
        variables: a mapping of (var, {'parents': [...], 'properties': [...]})
        properties: a mapping of (prop, {'parents': [...]})
        roles: a mapping of (role, {'value': ...})
        predicates: a mapping of (pred, {'parents': [...], 'synopses': [...]})
    Attributes:
        variables: a :class:`~delphin.tfs.TypeHierarchy` of variables;
            the `data` attribute of the
            :class:`~delphin.tfs.TypeHierarchyNode` contains its
            property list
        properties: a :class:`~delphin.tfs.TypeHierarchy` of properties
        roles: mapping of role names to allowed variable types
        predicates: a :class:`~delphin.tfs.TypeHierarchy` of predicates;
            the `data` attribute of the
            :class:`~delphin.tfs.TypeHierarchyNode` contains a list of
            synopses
    """

    def __init__(self,
                 variables=None,
                 properties=None,
                 roles=None,
                 predicates=None):
        self.properties = tfs.TypeHierarchy(TOP_TYPE)
        self.variables = tfs.TypeHierarchy(TOP_TYPE)
        self.roles = {}
        self.predicates = tfs.TypeHierarchy(TOP_TYPE)
        # validate and normalize inputs
        if properties:
            self._init_properties(properties)
        if variables:
            self._init_variables(variables)
        if roles:
            self._init_roles(roles)
        if predicates:
            self._init_predicates(predicates)

    def _init_properties(self, properties):
        subhier = {}
        for prop, data in properties.items():
            prop = prop.lower()
            parents = data.get('parents')
            _add_to_subhierarchy(subhier, prop, parents, None)
        self.properties.update(subhier)

    def _init_variables(self, variables):
        subhier = {}
        for var, data in variables.items():
            var = var.lower()
            parents = data.get('parents')
            properties = []
            for k, v in data.get('properties', []):
                k, v = k.upper(), v.lower()
                if v not in self.properties:
                    raise SemIError('undefined property value: {}'.format(v))
                properties.append((k, v))
            _add_to_subhierarchy(subhier, var, parents, properties)
        self.variables.update(subhier)

    def _init_roles(self, roles):
        for role, data in roles.items():
            role = role.upper()
            var = data['value'].lower()
            if not (var == STRING_TYPE or var in self.variables):
                raise SemIError('undefined variable type: {}'.format(var))
            self.roles[role] = var

    def _init_predicates(self, predicates):
        subhier = {}
        propcache = {v: dict(node.data) for v, node in self.variables.items()}
        for pred, data in predicates.items():
            pred = pred.lower()
            parents = data.get('parents')
            synopses = []
            for synopsis_data in data.get('synopses', []):
                synopses.append(
                    self._init_synopsis(pred, synopsis_data, propcache))
            _add_to_subhierarchy(subhier, pred, parents, synopses)
        self.predicates.update(subhier)

    def _init_synopsis(self, pred, synopsis_data, propcache):
        synopsis = Synopsis.from_dict(synopsis_data)
        for role in synopsis:
            if role.name not in self.roles:
                raise SemIError(
                    '{}: undefined role: {}'.format(pred, role.name))
            if role.value == STRING_TYPE:
                if role.properties:
                    raise SemIError('{}: strings cannot define properties'
                                    .format(pred))
            elif role.value not in self.variables:
                raise SemIError('{}: undefined variable type: {}'
                                .format(pred, role.value))
            else:
                for k, v in role.properties.items():
                    if v not in self.properties:
                        raise SemIError(
                            '{}: undefined property value: {}'
                            .format(pred, v))
                    if k not in propcache[role.value]:
                        # Just warn because of the current situation where
                        # 'i' variables are used for unexpressed 'x's
                        warnings.warn(
                            "{}: property '{}' not allowed on '{}'"
                            .format(pred, k, role.value),
                            SemIWarning)
                    else:
                        _v = propcache[role.value][k]
                        if not self.properties.compatible(v, _v):
                            raise SemIError(
                                '{}: incompatible property values: {}, {}'
                                .format(pred, v, _v))
        return synopsis

    @classmethod
    def from_dict(cls, d):
        """Instantiate a SemI from a dictionary representation."""

        return cls(**d)

    def to_dict(self):
        """Return a dictionary representation of the SemI."""

        def add_parents(d, node):
            ps = node.parents
            if ps and ps != [TOP_TYPE]:
                d['parents'] = ps

        variables = {}
        for var, node in self.variables.items():
            variables[var] = d = {}
            add_parents(d, node)
            if node.data:
                d['properties'] = [[k, v] for k, v in node.data]

        properties = {}
        for prop, node in self.properties.items():
            properties[prop] = d = {}
            add_parents(d, node)

        roles = {role: {'value': value} for role, value in self.roles.items()}

        predicates = {}
        for pred, node in self.predicates.items():
            predicates[pred] = d = {}
            add_parents(d, node)
            if node.data:
                d['synopses'] = [synopsis.to_dict() for synopsis in node.data]

        return {'variables': variables,
                'properties': properties,
                'roles': roles,
                'predicates': predicates}

    def find_synopsis(self, predicate, roles=None, variables=None):
        """
        Return the first matching synopsis for *predicate*.

        Synopses can be matched by a set of roles or an ordered list
        of variable types. If no condition is given, the first synopsis
        is returned.

        Args:
            predicate: predicate symbol whose synopsis will be returned
            roles: roles that all must be used in the synopsis
            variables: list of variable types (in order) that all must
                be used by roles in the synopsis
        Returns:
            matching synopsis as a `(role, value, properties, optional)`
            tuple
        Raises:
            :class:`SemIError`: if *predicate* is undefined or if no
                matching synopsis can be found
        Example:
            >>> smi.find_synopsis('_write_v_to')
            [('ARG0', 'e', [], False), ('ARG1', 'i', [], False),
             ('ARG2', 'p', [], True), ('ARG3', 'h', [], True)]
            >>> smi.find_synopsis('_write_v_to', variables='eii')
            [('ARG0', 'e', [], False), ('ARG1', 'i', [], False),
             ('ARG2', 'i', [], False)]
        """

        if predicate not in self.predicates:
            raise SemIError('undefined predicate: {}'.format(predicate))
        if roles is not None:
            roles = set(role.upper() for role in roles)
        if variables is not None:
            variables = [var.lower() for var in variables]
        found = False
        for synopsis in self.predicates[predicate]:
            if roles is not None and roles != set(d[0] for d in synopsis):
                continue
            if (variables is not None and (
                    len(synopsis) != len(variables) or
                    not all(self.subsumes(d[1], t)
                            for d, t in zip(synopsis, variables)))):
                continue
            found = synopsis
            break
        if found is False:
            raise SemIError('no valid synopsis for {}({})'
                            .format(predicate, ', '.join(variables)))
        return found


def _add_to_subhierarchy(subhier, typename, parents, data):
    if parents:
        parents = [parent.lower() for parent in parents]
    else:
        parents = [TOP_TYPE]
    subhier[typename] = tfs.TypeHierarchyNode(parents, data=data)