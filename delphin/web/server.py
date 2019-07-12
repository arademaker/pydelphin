
"""
DELPH-IN Web API Server
"""


import pathlib
import urllib.parse as urlparse
import datetime
import json
import functools

import falcon
from falcon import media

from delphin import ace
from delphin import dmrs
from delphin import eds
from delphin.codecs import (
    mrsjson,
    dmrsjson,
    edsjson,
)
from delphin import itsdb


def configure(api, parser=None, generator=None, testsuites=None):
    """
    Configure server application *api*.

    This is the preferred way to setup the server application, but the
    task-specific classes defined in this module can also be used to
    setup custom routes, for instance.

    If a path is given for *parser* or *generator*, it will be used to
    construct a :class:`ParseServer` or :class:`GenerationServer`
    instance, respectively, with default arguments to the underlying
    :class:`~delphin.ace.ACEProcessor`. If non-default arguments are
    needed, pass in the customized :class:`ParseServer` or
    :class:`GenerationServer` instances directly.

    Args:
        api: an instance of :class:`falcon.API`
        parser: a path to a grammar or a :class:`ParseServer` instance
        generator: a path to a grammar or a :class:`GenerationServer`
            instance
        testsuites: iterable of test suite descriptions with a unique
            `name` and a `path`.
    Example:
        >>> server.configure(
        ...     api,
        ...     parser='~/grammars/erg-2018-x86-64-0.9.30.dat',
        ...     testsuites=[
        ...         {'name': 'mrs',
        ...          'path': '~/grammars/erg/tsdb/gold/mrs'}])
    """
    if parser is not None:
        if isinstance(parser, (str, pathlib.Path)):
            parser = ParseServer(parser)
        api.add_route('/parse', parser)

    if generator is not None:
        if isinstance(generator, (str, pathlib.Path)):
            generator = GenerationServer(generator)
        api.add_route('/generate', generator)

    if testsuites is not None:
        testsuites = TestSuiteResource(testsuites)
        api.add_route('/testsuites', testsuites)
        api.add_route('/testsuites/{name}', testsuites, suffix='name')
        api.add_route('/testsuites/{name}/{table}', testsuites, suffix='table')

    api.req_options.strip_url_path_trailing_slash = True
    api.req_options.media_handlers['application/json'] = _json_handler
    api.resp_options.media_handlers['application/json'] = _json_handler


class ProcessorServer(object):
    """
    A server for results from an ACE processor.

    Note:

        This class is not meant to be used directly. Use a subclass
        instead.
    """

    processor_class = None

    def __init__(self, grammar, *args, **kwargs):
        self.grammar = grammar
        self.args = list(args)
        self.kwargs = kwargs

    def spawn(self, *args):
        cmdargs = self.args + list(args)
        return self.processor_class(
            self.grammar,
            cmdargs,
            **self.kwargs)

    def on_get(self, req, resp):
        inp = req.get_param('input', required=True)
        n = req.get_param_as_int('results', min_value=1, default=1)

        with self.spawn('-n', str(n)) as cpu:
            ace_resp = cpu.interact(inp)

        args = _get_args(req)
        resp.media = _make_response(inp, ace_resp, args)
        resp.status = falcon.HTTP_OK


class ParseServer(ProcessorServer):
    """
    A server for parse results from ACE.
    """

    processor_class = ace.ACEParser


class GenerationServer(ProcessorServer):
    """
    A server for generation results from ACE.
    """

    processor_class = ace.ACEGenerator


def _get_args(req):
    args = {}
    params = req.params
    for name in ('tokens', 'derivation', 'mrs', 'eds', 'dmrs'):
        if name in params:
            val = params[name]
            # handle 'json' and 'null' for ErgAPI compatibility
            args[name] = (val == 'json'
                          or (val != 'null'
                              and req.get_param_as_bool(name)))
        else:
            args[name] = False
    return args


def _make_response(inp, ace_response, params):
    tcpu = ace_response.get('tcpu')
    pedges = ace_response.get('pedges')
    readings = ace_response.get('readings')
    if readings is None:
        readings = len(ace_response.get('results', []))

    results = []
    for i, res in enumerate(ace_response.results()):
        m = res.mrs()
        d = res.derivation()
        result = {'result-id': i}

        if params['derivation']:
            result['derivation'] = d.to_dict(
                fields=['id', 'entity', 'score', 'form', 'tokens'])
        if params['mrs']:
            result['mrs'] = mrsjson.to_dict(m)
        if params['eds']:
            e = eds.from_mrs(m, predicate_modifiers=True)
            result['eds'] = edsjson.to_dict(e)
        if params['dmrs']:
            _d = dmrs.from_mrs(m)
            result['dmrs'] = dmrsjson.to_dict(_d)
        # surface is for generation
        if 'surface' in res:
            result['surface'] = res['surface']

        results.append(result)

    response = {
        'input': inp,
        'readings': readings,
        'results': results
    }
    if tcpu is not None:
        response['tcpu'] = tcpu
    if pedges is not None:
        response['pedges'] = pedges
    if params.get('tokens') == 'json':
        t1 = ace_response.tokens('initial')
        t2 = ace_response.tokens('internal')
        response['tokens'] = {
            'initial': t1.to_list(),
            'internal': t2.to_list()
        }

    return response


class TestSuiteResource(object):
    """
    A server for a collection of test suites.
    """

    def __init__(self, testsuites):
        self.testsuites = testsuites
        self.index = {entry['name']: entry for entry in testsuites}

    def on_get(self, req, resp):
        quote = urlparse.quote
        base = req.uri
        data = []
        for entry in self.testsuites:
            name = entry['name']
            uri = '/'.join([base, quote(name)])
            data.append({'name': name, 'url': uri})
        resp.media = data
        resp.status = falcon.HTTP_OK

    def on_get_name(self, req, resp, name):
        try:
            entry = self.index[name]
        except KeyError:
            raise falcon.HTTPNotFound()
        ts = itsdb.TestSuite(entry['path'])
        quote = urlparse.quote
        base = req.uri
        resp.media = {tablename: '/'.join([base, quote(tablename)])
                      for tablename in ts.schema}
        resp.status = falcon.HTTP_OK

    def on_get_table(self, req, resp, name, table):
        try:
            entry = self.index[name]
        except KeyError:
            raise falcon.HTTPNotFound()
        ts = itsdb.TestSuite(entry['path'])
        rows = ts[table]
        resp.media = [list(row) for row in rows]
        resp.status = falcon.HTTP_OK


# override default JSON handler so it can serialize datetime

def _datetime_default(obj):
    if isinstance(obj, datetime.datetime):
        return str(obj)
    else:
        raise TypeError(type(obj))


_json_handler = media.JSONHandler(
    dumps=functools.partial(json.dumps, default=_datetime_default),
    loads=json.loads
)
