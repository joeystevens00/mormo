from collections import ChainMap
from typing import Any, Callable, Iterable, Union
import os
import uuid
import json
import importlib
import logging
import hashlib
import random
import secrets
from shlex import quote
import subprocess
import string
import tempfile
import jinja2
import yaml

from . import logger

HTTP_VERBS = [
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
]

def strip_nulls(d: dict):
    nd = {}
    for k, v in d.items():
        if v:
            if isinstance(v, dict):
                nd[k] = strip_nulls(v)
            else:
                nd[k] = v
    return nd


def load_file(f, content_type=None):
    if f.endswith('.yaml') or content_type == 'yaml':
        load_f = yaml.safe_load
    elif f.endswith('.json') or content_type == 'json':
        load_f = json.load
    else:
        raise ValueError(f"Unknown file type: {f}")
    with open(f, 'r') as fp:
        return load_f(fp)


def trim(s):
    return s.rstrip(' ').lstrip(' ')


def run_newman(collection_file, host=None, verbose=None, json=False):
    from .schema import NewmanResult
    cmdargs = []
    json_outfile, json_content = None, None
    if host:
        cmdargs.extend(['--env-var', f'baseUrl={quote(host)}'])
    if verbose:
        cmdargs.append('--verbose')
    cmdargs.extend(['--reporters', f'cli{",json" if json else ""}'])
    if json:
        json_outfile = tempfile.mktemp()
        cmdargs.extend(["--reporter-json-export", json_outfile])
    e = subprocess.run(args=['newman', 'run', quote(collection_file), *cmdargs], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    if json_outfile:
        json_content = load_file(json_outfile, content_type='json')
    print('STDOUT', e.stdout.decode('utf-8'))
    print('STDERR', e.stderr.decode('utf-8'))
    return NewmanResult(
        stderr=e.stderr.decode('utf-8'),
        stdout=e.stdout.decode('utf-8'),
        json_=json_content
    )


def cls_from_str(name):
    # Import the module .
    components = name.split('.')
    mod = __import__(components[0])
    module = importlib.import_module('.'.join(components[:len(components)-1]))
    a = module.__getattribute__(components[-1])
    print(a)
    return a
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod


def fingerprint(payload: Any):
    if isinstance(payload, Iterable) and not isinstance(payload, dict):
        payload = [p for p in payload]
    if isinstance(payload, (dict, list)):
        payload = repr(payload)
    else:
        payload = repr(payload)
    return hashlib.sha512(payload.encode('utf-8')).hexdigest()


class DB:
    def __init__(self, r, model=None, uid=None):
        if uid:
            model = self.load_model_from_uid(r, uid)
            if not model:
                raise ValueError("Unable to load by uid")
        elif model:
            self.uid = fingerprint(model.dict())
        else:
            raise ValueError("Model or uid is required")
        self.model = model
        self.cache_ttl = 60*60*24*7
        self.klass = type(self.model).__module__ + '.' + type(self.model).__name__
        self.json = json.dumps({ 'data': self.model.to_dict(), 'class': self.klass })
        self.r = r

    @classmethod
    def _get(cls, r, uid):
        logger.debug(f'Getting {uid} from Redis.')
        return r.get(uid).decode('utf-8')

    @classmethod
    def load_model_from_uid(cls, r, uid):
        raw = cls._get(r, uid)
        if raw:
            raw = json.loads(raw)
            return cls_from_str(raw['class']).construct(**raw['data'])

    def save(self):
        logger.debug(f'Creating {repr(self)} in Redis.')
        return self.r.setex(
            self.uid, self.cache_ttl,
            self.json.encode('utf-8'),
        )


HTTP_REASON_CLASS = {
    1: "Informational - Request received, continuing process",
    2: "Success - The action was successfully received, understood, and accepted",
    3: "Redirection - Further action must be taken in order to complete the request",
    4: "Client Error - The request contains bad syntax or cannot be fulfilled",
    5: "Server Error - The server failed to fulfill an apparently valid request",
}


HTTP_REASONS = {
    200: "OK",
    407: "Proxy Authentication Required",
    408: "Request Time-out",
    409: "Conflict",
    410: "Gone",
    411: "Length Required",
    412: "Precondition Failed",
    413: "Request Entity Too Large",
    414: "Request-URI Too Large",
    415: "Unsupported Media Type",
    416: "Requested range not satisfiable",
    417: "Expectation Failed",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Time-out",
    505: "HTTP Version not supported",
}


def get_http_reason(code):
    if isinstance(code, str) and not code.isdigit() and code[0].isdigit() and len(code) == 3:
        return HTTP_REASON_CLASS.get(int(code[0]))
    reason = HTTP_REASONS.get(int(code))
    if not reason:
        reason = HTTP_REASON_CLASS.get(int(str(code)[0]))
    return reason


def render_jinja2(template: str, **kwargs) -> str:
    return jinja2.Template(template).render(**kwargs)


def uuidgen(*_, **__):
    #t = str(uuid.uuid1())
    t = '-'.join([secrets.token_hex(i//2) for i in [8, 4, 4, 4, 12]])
    return t


def gen_string(length, charset=string.printable):
    return ''.join([random.choice(charset) for i in range(0, length)])


def flatten_iterables_in_dict(d: dict, index=0, no_null=True, min_length=0):
    nd = {}
    for k, v in d.copy().items():
        if isinstance(v, dict):
            nd[k] = flatten_iterables_in_dict(v, index=index, no_null=no_null, min_length=min_length)
        elif isinstance(v, Iterable):
            if (no_null and v[index] is None) or (isinstance(v[index], str) and len(v[index]) <= min_length):
                for i in v:
                    if (not no_null or i is not None) and len(i) >= min_length:
                        nd[k] = i
                        break
            else:
                nd[k] = v[index]
        else:
            nd[k] = v
    return nd


class TemplateMap:
    def __init__(self, map: dict, defaults: dict, template_args: dict):
        self.map = ChainMap(map, defaults)
        self.res = self.parse_map(self.map, template_args)

    @classmethod
    def parse_map_item(
        cls, map: dict, k: Any,
        v: Union[Callable, str, dict, Iterable],
        template_args: dict,
    ):
        if isinstance(v, Callable):
            res = v(map, k, template_args)
            if isinstance(res, dict):
                return cls.parse_map(res, template_args)
            else:
                return cls.parse_map_item(map, k, res, template_args)
        elif isinstance(v, str):
            return render_jinja2(v, **template_args)
        elif isinstance(v, dict):
            return cls.parse_map(v, template_args)
        elif isinstance(v, Iterable):
            res = []
            for i in v:
                res.append(cls.parse_map_item(map, k, i, template_args))
            return res
        else:
            raise ValueError(f"Unhandled type: {type(v)}")

    @classmethod
    def parse_map(cls, map: dict, template_args: dict) -> dict:
        res = {}
        for k, v in map.items():
            res[k] = cls.parse_map_item(map, k, v, template_args)
        return res
