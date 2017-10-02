"""
The itsdb module makes it easy to work with [incr tsdb()] profiles.
The ItsdbProfile class works with whole profiles, but it generally
relies on the module-level functions to do its work (such as
get_relations() or decode_row()). Queries over profiles can be
customized through the use of filters (see filter_rows()), applicators
(see apply_rows()), and selectors (see select_rows()). In addition,
one can create a new skeleton using the make_skeleton() function.
"""

from __future__ import print_function

import os
import re
from gzip import open as gzopen
import logging
from io import TextIOWrapper, BufferedReader
from collections import defaultdict, namedtuple, OrderedDict
from itertools import chain
from contextlib import contextmanager

from delphin.exceptions import ItsdbError
from delphin.util import safe_int

##############################################################################
# Module variables

_relations_filename = 'relations'
_field_delimiter = '@'
_default_datatype_values = {
    ':integer': '-1'
}
tsdb_coded_attributes = {
    'i-wf': '1',
    'i-difficulty': '1',
    'polarity': '-1'
}
_primary_keys = [
    ["i-id", "item"],
    ["p-id", "phenomenon"],
    ["ip-id", "item-phenomenon"],
    ["s-id", "set"],
    ["run-id", "run"],
    ["parse-id", "parse"],
    ["e-id", "edge"],
    ["f-id", "fold"]
]
tsdb_core_files = [
    "item",
    "analysis",
    "phenomenon",
    "parameter",
    "set",
    "item-phenomenon",
    "item-set"
]

#############################################################################
# Relations files

class Field(
        namedtuple('Field', 'name datatype key partial comment'.split())):
    '''
    A tuple describing a column in an [incr tsdb()] profile.

    Args:
        name: the column name
        datatype: e.g. ":string" or ":integer"
        key: True if the column is a key in the database
        partial: True if the column is a partial key
        comment: a description of the column
    '''
    def __new__(cls, name, datatype, key=False, partial=False, comment=None):
        return super(Field, cls).__new__(
            cls, name, datatype, key, partial, comment
        )

    def __str__(self):
        parts = [self.name, self.datatype]
        if self.key:
            parts += [':key']
        if self.partial:
            parts += [':partial']
        s = '  ' + ' '.join(parts)
        if self.comment:
            s = '{}# {}'.format(s.ljust(40), self.comment)
        return s


class Relations(object):
    """
    A "relations file" is a [incr tsdb()] database schema.
    """
    def __init__(self, tables):
        self.tables = tuple(t[0] for t in tables)
        self._data = dict(tables)

    @classmethod
    def from_file(cls, source):
        if hasattr(source, 'read'):
            relations = cls.from_string(source.read())
        else:
            with open(source) as f:
                relations = cls.from_string(f.read())
        return relations

    @classmethod
    def from_string(cls, s):
        tables = []
        seen = set()
        current_table = None
        lines = list(reversed(s.splitlines()))  # to pop() in right order
        while lines:
            line = lines.pop().strip()
            table_m = re.match(r'^(?P<table>\w.+):$', line)
            field_m = re.match(r'\s*(?P<name>\S+)'
                               r'(\s+(?P<attrs>[^#]+))?'
                               r'(\s*#\s*(?P<comment>.*)$)?',
                               line)
            if table_m is not None:
                table_name = table_m.group('table')
                if table_name in seen:
                    raise ItsdbError(
                        'Table {} already defined.'.format(table_name)
                    )
                current_table = (table_name, [])
                tables.append(current_table)
                seen.add(table_name)
            elif field_m is not None and current_table is not None:
                name = field_m.group('name')
                attrs = field_m.group('attrs').split()
                datatype = attrs.pop(0)
                key = ':key' in attrs
                partial = ':partial' in attrs
                comment = field_m.group('comment')
                current_table[1].append(
                    Field(name, datatype, key, partial, comment)
                )
            elif line != '':
                raise ItsdbError('Invalid line: ' + line)
        return cls(tables)

    def __getitem__(self, key):
        fields = self._data[key]
        return list(fields)

    def __iter__(self):
        return iter(self.tables)

    def __len__(self):
        return len(self.tables)

    def __str__(self):
        return '\n\n'.join(
            '{tablename}:\n{fields}'.format(
                tablename=tablename,
                fields='\n'.join(str(f) for f in self[tablename])
            )
            for tablename in self
        )

    def items(self):
        return [(table, self[table]) for table in self]


##############################################################################
# Non-class (i.e. static) functions


def get_relations(path):
    """
    Parse the relations file and return a Relations object that
    describes the database structure.

    **Note**: for backward-compatibility only; use Relations.from_file()

    Args:
        path: The path of the relations file.
    Returns:
        A dictionary mapping a table name to a list of Field tuples.
    """
    return Relations.from_file(path)


data_specifier_re = re.compile(r'(?P<table>[^:]+)?(:(?P<cols>.+))?$')
def get_data_specifier(string):
    """
    Return a tuple (table, col) for some [incr tsdb()] data specifier.
    For example::

        item              -> ('item', None)
        item:i-input      -> ('item', ['i-input'])
        item:i-input@i-wf -> ('item', ['i-input', 'i-wf'])
        :i-input          -> (None, ['i-input'])
        (otherwise)       -> (None, None)
    """
    match = data_specifier_re.match(string)
    if match is None:
        return (None, None)
    table = match.group('table')
    if table is not None:
        table = table.strip()
    cols = match.group('cols')
    if cols is not None:
        cols = list(map(str.strip, cols.split('@')))
    return (table, cols)


def decode_row(line):
    """
    Decode a raw line from a profile into a list of column values.

    Decoding involves splitting the line by the field delimiter ('@' by
    default) and unescaping special characters.

    Args:
        line: a raw line from a [incr tsdb()] profile.
    Returns:
        A list of column values.
    """
    fields = line.rstrip('\n').split(_field_delimiter)
    return list(map(unescape, fields))


def encode_row(fields):
    """
    Encode a list of column values into a [incr tsdb()] profile line.

    Encoding involves escaping special characters for each value, then
    joining the values into a single string with the field delimiter
    ('@' by default). It does not fill in default values (see
    make_row()).

    Args:
        fields: a list of column values
    Returns:
        A [incr tsdb()]-encoded string
    """
    return _field_delimiter.join(map(escape, map(str, fields)))


_character_escapes = {
    _field_delimiter: '\\s',
    '\n': '\\n',
    '\\': '\\\\'
}

def _escape(m):
    return _character_escapes[m.group(1)]


def escape(string):
    """
    Replace any special characters with their [incr tsdb()] escape
    sequences. Default sequences are::

        @         -> \s
        (newline) -> \\n
        \\         -> \\\\

    Also see unescape()

    Args:
        string: the string to escape
    Returns:
        The escaped string
    """
    return re.sub(r'(@|\n|\\)', _escape, string, flags=re.UNICODE)


_character_unescapes = {'\\s': _field_delimiter, '\\n': '\n', '\\\\': '\\'}

def _unescape(m):
    return _character_unescapes[m.group(1)]


def unescape(string):
    """
    Replace [incr tsdb()] escape sequences with the regular equivalents.
    See escape().

    Args:
        string: the escaped string
    Returns:
        The string with escape sequences replaced
    """
    return re.sub(r'(\\s|\\n|\\\\)', _unescape, string, flags=re.UNICODE)


def _table_filename(tbl_filename):
    if tbl_filename.endswith('.gz'):
        gzfn = tbl_filename
        txfn = tbl_filename[:-3]
    else:
        txfn = tbl_filename
        gzfn = tbl_filename + '.gz'
    
    if os.path.exists(txfn):
        if (os.path.exists(gzfn) and
                os.stat(gzfn).st_mtime > os.stat(txfn).st_mtime):
            tbl_filename = gzfn
        else:
            tbl_filename = txfn
    elif os.path.exists(gzfn):
        tbl_filename = gzfn
    else:
        raise ItsdbError(
            'Table does not exist at {}(.gz)'
            .format(tbl_filename)
        )
    
    return tbl_filename


@contextmanager
def _open_table(tbl_filename):
    path = _table_filename(tbl_filename)
    if path.endswith('.gz'):
        # text mode only from py3.3; until then use TextIOWrapper
        with TextIOWrapper(
                BufferedReader(gzopen(tbl_filename + '.gz', mode='r'))
             ) as f:
            yield f
    else:
        with open(tbl_filename) as f:
            yield f


def _write_table(profile_dir, table_name, rows, fields,
                 append=False, gzip=False):
    # don't gzip if empty
    rows = iter(rows)
    try:
        first_row = next(rows)
    except StopIteration:
        gzip = False
    else:
        rows = chain([first_row], rows)
    if gzip and append:
        logging.warning('Appending to a gzip file may result in '
                        'inefficient compression.')

    if not os.path.exists(profile_dir):
        raise ItsdbError('Profile directory does not exist: {}'
                         .format(profile_dir))

    tbl_filename = os.path.join(profile_dir, table_name)
    mode = 'a' if append else 'w'
    if gzip:
        # text mode only from py3.3; until then use TextIOWrapper
        #mode += 't'  # text mode for gzip
        f = TextIOWrapper(gzopen(tbl_filename + '.gz', mode=mode))
    else:
        f = open(tbl_filename, mode=mode)

    for row in rows:
        f.write(make_row(row, fields) + '\n')

    f.close()


def make_row(row, fields):
    """
    Encode a mapping of column name to values into a [incr tsdb()]
    profile line. The *fields* parameter determines what columns are
    used, and default values are provided if a column is missing from
    the mapping.

    Args:
        row: a dictionary mapping column names to values
        fields: an iterable of [Field] objects
    Returns:
        A [incr tsdb()]-encoded string
    """
    row_fields = [row.get(f.name, str(default_value(f.name, f.datatype)))
                  for f in fields]
    return encode_row(row_fields)


def default_value(fieldname, datatype):
    """
    Return the default value for a column.

    If the column name (e.g. *i-wf*) is defined to have an idiosyncratic
    value, that value is returned. Otherwise the default value for the
    column's datatype is returned.

    Args:
        fieldname: the column name (e.g. `i-wf`)
        datatype: the datatype of the column (e.g. `:integer`)
    Returns:
        The default value for the column.
    """
    if fieldname in tsdb_coded_attributes:
        return tsdb_coded_attributes[fieldname]
    else:
        return _default_datatype_values.get(datatype, '')


def filter_rows(filters, rows):
    """
    Yield rows matching all applicable filters.

    Filter functions have binary arity (e.g. `filter(row, col)`) where
    the first parameter is the dictionary of row data, and the second
    parameter is the data at one particular column.

    Args:
        filters: a tuple of (cols, filter_func) where filter_func will
            be tested (filter_func(row, col)) for each col in cols where
            col exists in the row
        rows: an iterable of rows to filter
    Yields:
        Rows matching all applicable filters
    """
    for row in rows:
        if all(condition(row, row.get(col))
               for (cols, condition) in filters
               for col in cols
               if col is None or col in row):
            yield row


def apply_rows(applicators, rows):
    """
    Yield rows after applying the applicator functions to them.

    Applicators are simple unary functions that return a value, and that
    value is stored in the yielded row. E.g.
    `row[col] = applicator(row[col])`. These are useful to, e.g., cast
    strings to numeric datatypes, to convert formats stored in a cell,
    extract features for machine learning, and so on.

    Args:
        applicators: a tuple of (cols, applicator) where the applicator
            will be applied to each col in cols
        rows: an iterable of rows for applicators to be called on
    Yields:
        Rows with specified column values replaced with the results of
        the applicators
    """
    for row in rows:
        for (cols, function) in applicators:
            for col in (cols or []):
                value = row.get(col, '')
                row[col] = function(row, value)
        yield row


def select_rows(cols, rows, mode='list'):
    """
    Yield data selected from rows.

    It is sometimes useful to select a subset of data from a profile.
    This function selects the data in *cols* from *rows* and yields it
    in a form specified by *mode*. Possible values of *mode* are:

    | mode           | description       | example `['i-id', 'i-wf']` |
    | -------------- | ----------------- | -------------------------- |
    | list (default) | a list of values  | `[10, 1]`                  |
    | dict           | col to value map  | `{'i-id':'10','i-wf':'1'}` |
    | row            | [incr tsdb()] row | `'10@1'`                   |

    Args:
        cols: an iterable of column names to select data for
        rows: the rows to select column data from
        mode: the form yielded data should take

    Yields:
        Selected data in the form specified by *mode*.
    """
    mode = mode.lower()
    if mode == 'list':
        cast = lambda cols, data: data
    elif mode == 'dict':
        cast = lambda cols, data: dict(zip(cols, data))
    elif mode == 'row':
        cast = lambda cols, data: encode_row(data)
    else:
        raise ItsdbError('Invalid mode for select operation: {}\n'
                         '  Valid options include: list, dict, row'
                         .format(mode))
    for row in rows:
        data = [row.get(c) for c in cols]
        yield cast(cols, data)


def match_rows(rows1, rows2, key, sort_keys=True):
    """
    Yield triples of (value, left_rows, right_rows) where `left_rows`
    and `right_rows` are lists of rows that share the same column
    value for *key*.
    """
    matched = OrderedDict()
    for i, rows in enumerate([rows1, rows2]):
        for row in rows:
            val = row[key]
            try:
                data = matched[val]
            except KeyError:
                matched[val] = ([], [])
                data = matched[val]
            data[i].append(row)
    vals = matched.keys()
    if sort_keys:
        vals = sorted(vals, key=safe_int)
    for val in vals:
        left, right = matched[val]
        yield (val, left, right)


def make_skeleton(path, relations, item_rows, gzip=False):
    """
    Instantiate a new profile skeleton (only the relations file and
    item file) from an existing relations file and a list of rows
    for the item table. For standard relations files, it is suggested
    to have, as a minimum, the `i-id` and `i-input` fields in the
    item rows.

    Args:
        path: the destination directory of the skeleton---must not
              already exist, as it will be created
        relations: the path to the relations file
        item_rows: the rows to use for the item file
        gzip: if `True`, the item file will be compressed
    Returns:
        An ItsdbProfile containing the skeleton data (but the profile
        data will already have been written to disk).
    Raises:
        ItsdbError if the destination directory could not be created.
    """
    try:
        os.makedirs(path)
    except OSError:
        raise ItsdbError('Path already exists: {}.'.format(path))

    import shutil
    shutil.copyfile(relations, os.path.join(path, _relations_filename))
    prof = ItsdbProfile(path, index=False)
    prof.write_table('item', item_rows, gzip=gzip)
    return prof


##############################################################################
# Profile class

class ItsdbProfile(object):
    """
    A [incr tsdb()] profile, analyzed and ready for reading or writing.

    Args:
        path: The path of the directory containing the profile
        filters: A list of tuples [(table, cols, condition)] such
            that only rows in table where condition(row, row[col])
            evaluates to a non-false value are returned; filters are
            tested in order for a table.
        applicators: A list of tuples [(table, cols, function)]
            which will be used when reading rows from a table---the
            function will be applied to the contents of the column
            cell in the table. For each table, each column-function
            pair will be applied in order. Applicators apply after
            the filters.
        index: If `True`, indices are created based on the keys of
            each table.
    """

    # _tables is a list of table names to consider (for indexing, writing,
    # etc.). If `None`, all present in the relations file and on disk are
    # considered. Otherwise, only those present in the list are considered.
    _tables = None

    def __init__(self, path, filters=None, applicators=None, index=True):
        self.root = path
        self.relations = get_relations(
            os.path.join(self.root, _relations_filename)
        )

        if self._tables is None:
            self._tables = list(self.relations)

        self.filters = defaultdict(list)
        self.applicators = defaultdict(list)
        self._index = dict()

        for (table, cols, condition) in (filters or []):
            self.add_filter(table, cols, condition)

        for (table, cols, function) in (applicators or []):
            self.add_applicator(table, cols, function)

        if index:
            self._build_index()

    def add_filter(self, table, cols, condition):
        """
        Add a filter. When reading *table*, rows in *table* will be
        filtered by filter_rows().

        Args:
            table: The table the filter applies to.
            cols: The columns in *table* to filter on.
            condition: The filter function.
        """
        if table is not None and table not in self.relations:
            raise ItsdbError('Cannot add filter; table "{}" is not defined '
                             'by the relations file.'
                             .format(table))
        # this is a hack, though perhaps well-motivated
        if cols is None:
            cols = [None]
        self.filters[table].append((cols, condition))

    def add_applicator(self, table, cols, function):
        """
        Add an applicator. When reading *table*, rows in *table* will be
        modified by apply_rows().

        Args:
            table: The table to apply the function to.
            cols: The columns in *table* to apply the function on.
            function: The applicator function.
        """

        if table not in self.relations:
            raise ItsdbError('Cannot add applicator; table "{}" is not '
                             'defined by the relations file.'
                             .format(table))
        if cols is None:
            raise ItsdbError('Cannot add applicator; columns not specified.')
        fields = set(f.name for f in self.relations[table])
        for col in cols:
            if col not in fields:
                raise ItsdbError('Cannot add applicator; column "{}" not '
                                 'defined by the relations file.'
                                 .format(col))
        self.applicators[table].append((cols, function))

    def _build_index(self):
        self._index = {key: None for key, _ in _primary_keys}
        tables = self._tables
        if tables is not None:
            tables = set(tables)
        for (keyname, table) in _primary_keys:
            if table in tables:
                ids = set()
                try:
                    for row in self.read_table(table):
                        key = row[keyname]
                        ids.add(key)
                except ItsdbError:
                    logging.info('Failed to index {}.'.format(table))
                self._index[keyname] = ids

    def table_relations(self, table):
        if table not in self.relations:
            raise ItsdbError(
                'Table {} is not defined in the profiles relations.'
                .format(table)
            )
        return self.relations[table]

    def read_raw_table(self, table):
        """
        Yield rows in the [incr tsdb()] *table*. A row is a dictionary
        mapping column names to values. Data from a profile is decoded
        by decode_row(). No filters or applicators are used.
        """

        field_names = [f.name for f in self.table_relations(table)]
        field_len = len(field_names)
        with _open_table(os.path.join(self.root, table)) as tbl:
            for line in tbl:
                fields = decode_row(line)
                if len(fields) != field_len:
                    # should this throw an exception instead?
                    logging.error('Number of stored fields ({}) '
                                  'differ from the expected number({}); '
                                  'fields may be misaligned!'
                                  .format(len(fields), field_len))
                row = OrderedDict(zip(field_names, fields))
                yield row

    def read_table(self, table, key_filter=True):
        """
        Yield rows in the [incr tsdb()] *table* that pass any defined
        filters, and with values changed by any applicators. If no
        filters or applicators are defined, the result is the same as
        from ItsdbProfile.read_raw_table().
        """
        filters = self.filters[None] + self.filters[table]
        if key_filter:
            for f in self.relations[table]:
                key = f.name
                if f.key and (self._index.get(key) is not None):
                    ids = self._index[key]
                    # Can't keep local variables (like ids) in the scope of
                    # the lambda expression, so make it a default argument.
                    # Source: http://stackoverflow.com/a/938493/1441112
                    function = lambda r, x, ids=ids: x in ids
                    filters.append(([key], function))
        applicators = self.applicators[table]
        rows = self.read_raw_table(table)
        return filter_rows(filters, apply_rows(applicators, rows))

    def select(self, table, cols, mode='list', key_filter=True):
        """
        Yield selected rows from *table*. This method just calls
        select_rows() on the rows read from *table*.
        """
        if cols is None:
            cols = [c.name for c in self.relations[table]]
        rows = self.read_table(table, key_filter=key_filter)
        for row in select_rows(cols, rows, mode=mode):
            yield row

    def join(self, table1, table2, key_filter=True):
        """
        Yield rows from a table built by joining *table1* and *table2*.
        The column names in the rows have the original table name
        prepended and separated by a colon. For example, joining tables
        'item' and 'parse' will result in column names like
        'item:i-input' and 'parse:parse-id'.
        """
        get_keys = lambda t: (f.name for f in self.relations[t] if f.key)
        keys = set(get_keys(table1)).intersection(get_keys(table2))
        if not keys:
            raise ItsdbError(
                'Cannot join tables "{}" and "{}"; no shared key exists.'
                .format(table1, table2)
            )
        key = keys.pop()
        # this join method stores the whole of table2 in memory, but it is
        # MUCH faster than a nested loop method. Most profiles will fit in
        # memory anyway, so it's a decent tradeoff
        table2_data = defaultdict(list)
        for row in self.read_table(table2, key_filter=key_filter):
            table2_data[row[key]].append(row)
        for row1 in self.read_table(table1, key_filter=key_filter):
            for row2 in table2_data.get(row1[key], []):
                joinedrow = OrderedDict(
                    [('{}:{}'.format(table1, k), v)
                     for k, v in row1.items()] +
                    [('{}:{}'.format(table2, k), v)
                     for k, v in row2.items()]
                )
                yield joinedrow

    def write_table(self, table, rows, append=False, gzip=False):
        """
        Encode and write out *table* to the profile directory.

        Args:
            table: The name of the table to write
            rows: The rows to write to the table
            append: If `True`, append the encoded rows to any existing
                data.
            gzip: If `True`, compress the resulting table with `gzip`.
                The table's filename will have `.gz` appended.
        """
        _write_table(self.root,
                     table,
                     rows,
                     self.table_relations(table),
                     append=append,
                     gzip=gzip)

    def write_profile(self, profile_directory, relations_filename=None,
                      key_filter=True,
                      append=False, gzip=None):
        """
        Write all tables (as specified by the relations) to a profile.

        Args:
            profile_directory: The directory of the output profile
            relations_filename: If given, read and use the relations
                at this path instead of the current profile's
                relations
            key_filter: If True, filter the rows by keys in the index
            append: If `True`, append profile data to existing tables
                in the output profile directory
            gzip: If `True`, compress tables using `gzip`. Table
                filenames will have `.gz` appended. If `False`, only
                write out text files. If `None`, use whatever the
                original file was.
        """
        if relations_filename:
            src_rels = os.path.abspath(relations_filename)
            relations = get_relations(relations_filename)
        else:
            src_rels = os.path.abspath(os.path.join(self.root,
                                                    _relations_filename))
            relations = self.relations
        
        tgt_rels = os.path.abspath(os.path.join(profile_directory,
                                                _relations_filename))
        if not (os.path.isfile(tgt_rels) and src_rels == tgt_rels):
            with open(tgt_rels, 'w') as rel_fh:
                print(open(src_rels).read(), file=rel_fh)

        tables = self._tables
        if tables is not None:
            tables = set(tables)
        for table, fields in relations.items():
            if tables is not None and table not in tables:
                continue
            try:
                fn = _table_filename(os.path.join(self.root, table))
                _gzip = gzip if gzip is not None else fn.endswith('.gz')
                rows = list(self.read_table(table, key_filter=key_filter))
                _write_table(profile_directory, table, rows, fields,
                             append=append, gzip=_gzip)
            except ItsdbError:
                logging.warning(
                    'Could not write "{}"; table doesn\'t exist.'.format(table)
                )
                continue

        self._cleanup(gzip=gzip)

    def exists(self, table=None):
        """
        Return True if the profile or a table exist.

        If *table* is `None`, this function returns True if the root
        directory exists and contains a valid relations file. If *table*
        is given, the function returns True if the table exists as a
        file (even if empty). Otherwise it returns False.
        """
        if not os.path.isdir(self.root):
            return False
        if not os.path.isfile(os.path.join(self.root, _relations_filename)):
            return False
        if table is not None:
            try:
                _table_filename(os.path.join(self.root, table))
            except ItsdbError:
                return False
        return True

    def size(self, table=None):
        """
        Return the size, in bytes, of the profile or *table*.

        If *table* is `None`, this function returns the size of the
        whole profile (i.e. the sum of the table sizes). Otherwise, it
        returns the size of *table*.

        Note: if the file is gzipped, it returns the compressed size.
        """
        size = 0
        if table is None:
            for table in self.relations:
                size += self.size(table)
        else:
            try:
                fn = _table_filename(os.path.join(self.root, table))
                size += os.stat(fn).st_size
            except ItsdbError:
                pass
        return size

    def _cleanup(self, gzip=None):
        for table in self.relations:
            txfn = os.path.join(self.root, table)
            gzfn = os.path.join(self.root, table + '.gz')
            if os.path.isfile(txfn) and os.path.isfile(gzfn):
                if gzip is True:
                    os.remove(txfn)
                elif gzip is False:
                    os.remove(gzfn)
                elif os.stat(txfn).st_mtime < os.stat(gzfn).st_mtime:
                    os.remove(txfn)
                else:
                    os.remove(gzfn)

class ItsdbSkeleton(ItsdbProfile):
    """
    A [incr tsdb()] skeleton, analyzed and ready for reading or writing.

    See [ItsdbProfile] for initialization parameters.
    """

    _tables = tsdb_core_files
