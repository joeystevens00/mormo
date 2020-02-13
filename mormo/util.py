from collections import ChainMap
from typing import Any, Callable, Iterable, Union
import functools
import importlib
import hashlib
import jinja2
import json
import random
import re
import secrets
import string
from types import GeneratorType
import yaml

import hypothesis
from hypothesis import given
from hypothesis_jsonschema._from_schema import from_schema

from . import logger, Settings

RE_WORDCHARS = re.compile('^\w+$')  # noqa: W605

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

FILTERS = {
    str: lambda x: len(x) >= Settings().test_data_str_min_length,
    int: lambda x: x >= Settings().test_data_int_min,
    'words': lambda x: RE_WORDCHARS.match(x),
}

# def filter_min_length(x):
#     min_len = Settings().test_data_str_min_length
#     if isinstance(x, str):
#         logger.warning(f"STR {len(x)}")
#         return len(x) >= min_len
#     elif isinstance(x, int):
#         logger.warning(f"INT {x}")
#         return x >= min_len
#     else:
#         logger.warning(f"Don't know how to check length of type({type(x)})")
#         return True


def strip_nulls(d: dict):
    nd = {}
    for k, v in d.items():
        if v is not None:
            if isinstance(v, dict):
                nd[k] = strip_nulls(v)
            else:
                nd[k] = v
    return nd


def blind_load(content):
    load_map = {
        'json': json.loads,
        'yaml': yaml.load,
    }
    if content.lstrip().startswith('{'):
        content_type = "json"
    else:
        content_type = "yaml"
    try:
        parsed_content = load_map[content_type](content)
    except (yaml.scanner.ScannerError, json.decoder.JSONDecodeError) as e:
        logger.warn(e)
        parsed_content = load_map[("yaml" if content_type == "json" else "json")](content)
    return parsed_content


def load_file(f, content_type=None):
    if f.endswith('.yaml') or f.endswith('.yml') or content_type == 'yaml':
        load_f = yaml.safe_load
    elif f.endswith('.json') or content_type == 'json':
        load_f = json.load
    else:
        raise ValueError(f"Unknown file type: {f}")
    with open(f, 'r') as fp:
        return load_f(fp)


def trim(s):
    return s.rstrip(' ').lstrip(' ')


def cls_from_str(name):
    # Import the module .
    components = name.split('.')
    module = importlib.import_module(
        '.'.join(components[:len(components) - 1]),
    )
    a = module.__getattribute__(components[-1])
    return a


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
        self.cache_ttl = 60 * 60 * 24 * 7
        self.klass = type(self.model).__module__ + '.'\
            + type(self.model).__name__
        self.json = json.dumps({
            'data': self.model.to_dict(),
            'class': self.klass,
        })
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
    2: "Success - The action was successfully received, understood, and accepted",  # noqa: E501
    3: "Redirection - Further action must be taken in order to complete the request",  # noqa: E501
    4: "Client Error - The request contains bad syntax or cannot be fulfilled",
    5: "Server Error - The server failed to fulfill an apparently valid request",  # noqa: E501
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
    if (
        isinstance(code, str)
        and not code.isdigit() and code[0].isdigit()
        and len(code) == 3
    ):
        return HTTP_REASON_CLASS.get(int(code[0]))
    reason = HTTP_REASONS.get(int(code))
    if not reason:
        reason = HTTP_REASON_CLASS.get(int(str(code)[0]))
    return reason


def render_jinja2(template: str, **kwargs) -> str:
    return jinja2.Template(template).render(**kwargs)


def uuidgen(*_, **__):
    t = '-'.join([secrets.token_hex(i // 2) for i in [8, 4, 4, 4, 12]])
    return t


def gen_string(length, charset=string.printable, choice_f=random.choice):
    return ''.join([choice_f(charset) for i in range(0, length)])


def flatten_iterables_in_dict(d: dict, index=0, no_null=True, min_length=0):
    nd = {}
    for k, v in d.copy().items():
        if isinstance(v, dict):
            nd[k] = flatten_iterables_in_dict(
                v, index=index, no_null=no_null,
                min_length=min_length,
            )
        elif isinstance(v, Iterable):
            if (
                (no_null and v[index] is None)
                or (isinstance(v[index], str) and len(v[index]) <= min_length)
            ):
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


def generate_from_schema(schema, no_empty=True, retry=5):
    test_data = []
    settings = Settings()
    if (
        schema.get('type') == 'string'
        and not schema.get('minLength')
        and not schema.get('format')
    ):
        schema['minLength'] = settings.test_data_str_min_length
        # schema['pattern'] = '^\w+$'
        generate_func = from_schema(schema)
        generate_func = generate_func.filter(FILTERS[str])
    elif schema.get('type') == 'integer' and not schema.get('minimum'):
        schema['minimum'] = settings.test_data_int_min
        generate_func = from_schema(schema)
        generate_func = generate_func.filter(FILTERS[int])
    else:
        generate_func = from_schema(schema)

    @given(generate_func)
    def f(x):
        if x or not no_empty:
            test_data.append(x)
    passed = False
    while retry > 0 or not passed:
        try:
            f()
            passed = True
            retry = 0
        except hypothesis.errors.Unsatisfiable:
            retry -= 1
    if not passed:
        raise hypothesis.errors.Unsatisfiable("Max retries hit")
    yield test_data


def pick_one(gen: GeneratorType, strategy="random"):
    """Given a generator which yields an iterable, get an element."""
    # it seems that the data from generate_from_schema
    # is better if you pick randomly
    # often enough the first element is rather boring like 0 or '0'
    if "rand" in strategy.lower():
        return random.choice(next(gen))
    else:
        return next(gen)[0]


def hashable_lru(func):
    cache = functools.lru_cache(maxsize=1024)

    def deserialise(value):
        try:
            return json.loads(value)
        except Exception:
            return value

    def func_with_serialized_params(*args, **kwargs):
        _args = tuple([deserialise(arg) for arg in args])
        _kwargs = {k: deserialise(v) for k, v in kwargs.items()}
        return func(*_args, **_kwargs)

    cached_function = cache(func_with_serialized_params)

    @functools.wraps(func)
    def lru_decorator(*args, **kwargs):
        _args = tuple([json.dumps(arg, sort_keys=True) if type(arg) in (list, dict) else arg for arg in args])  # noqa: E501
        _kwargs = {k: json.dumps(v, sort_keys=True) if type(v) in (list, dict) else v for k, v in kwargs.items()}  # noqa: E501
        return cached_function(*_args, **_kwargs)
    lru_decorator.cache_info = cached_function.cache_info
    lru_decorator.cache_clear = cached_function.cache_clear
    return lru_decorator
