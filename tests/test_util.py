import json
import string
import tempfile
import uuid
import yaml

import pytest

from mormo.util import (
    blind_load,
    cls_from_str,
    fingerprint,
    flatten_iterables_in_dict,
    gen_string,
    get_http_reason,
    load_file,
    pick_one,
    uuidgen,
    strip_nulls,
    TemplateMap,
    trim,
)
from .conftest import generate_dict_expected



@pytest.mark.parametrize(
    "content,expected",
    [
        *generate_dict_expected(5, json.dumps),
        *generate_dict_expected(5, yaml.dump),
    ]
)
def test_blind_load(content, expected):
    assert blind_load(content) == expected


@pytest.mark.parametrize(
    "content,exc",
    [
        ('a : : b', json.decoder.JSONDecodeError),
        ('{', yaml.parser.ParserError),
    ]
)
def test_blind_load_invalid_json(content, exc):
    with pytest.raises(exc):
        blind_load(content)


def test_strip_nulls():
    assert strip_nulls({'a': None, 'b': 1}) == {'b': 1}
    assert strip_nulls({'a': 0}) == {'a': 0}
    assert strip_nulls({
        'a': None,
        'b': {
            'c': None,
            'd': {
                'e': None,
                'f': {
                    'g': 0
                }
            }
        }
    }) == {
        'b': {
            'd': {
                'f': {
                    'g': 0
                }
            }
        }
    }


def test_load_file(random_dict):
    f_map = {
        '.json': {'dump': json.dumps, 'load': json.load},
        '.yaml': {'dump': yaml.dump},
        '.yml': {'dump': yaml.dump},
    }
    for suffix in [".json", ".yaml", ".yml"]:
        x = tempfile.mktemp(suffix=suffix)
        with open(x, 'w') as f:
            f.write(f_map[suffix]['dump'](random_dict))
        assert load_file(x) == random_dict, "File loaded by suffix"
    x = tempfile.mktemp()
    with open(x, 'w') as f:
        f.write(json.dumps(random_dict))
    assert load_file(x, content_type='json') == random_dict, "File loaded by specified content type"


def test_load_file_invalid_type():
    with pytest.raises(ValueError) as exc:
        load_file("schema.tf")
    assert "Unknown file type" in str(exc)


def test_trim():
    assert trim(" a ") == "a"
    assert trim("   a  ") == "a"


def test_cls_from_str():
    assert cls_from_str('mormo.model.BaseModel').__name__ == "BaseModel"
    assert cls_from_str('mormo.schema.api.SaveOpenAPISchema').__name__ == "SaveOpenAPISchema"


def test_fingerprint():
    d = [fingerprint("abc"), fingerprint(["abc"]), fingerprint({"a": "bc"})]
    assert d[0] != d[1] != d[2]
    for i in d:
        assert isinstance(i, str)
        assert len(i) == 128


def get_lens(x):
    return [len(i) for i in str(x).split('-')]


def test_get_http_reason():
    assert get_http_reason(200) == "OK", "Defined reason returns definition"
    assert get_http_reason(299) == "Success - The action was successfully received, "\
        "understood, and accepted", "Undefined reason returns class definition"


def test_secure_uuidgen_behaves_like_uuid1():
    for i in range(10):
        assert get_lens(uuidgen()) == get_lens(uuid.uuid1())


@pytest.mark.parametrize("charset", [string.printable, string.digits, string.ascii_letters])
def test_gen_string(charset):
    s = gen_string(10, charset=charset)
    for i in s:
        assert i in charset
    assert len(s) == 10


def test_flatten_iterables_in_dict():
    assert flatten_iterables_in_dict({'a':['b', 'bb'], 'b': {'c':['ddd']}}, min_length=2) == {'a':'bb', 'b':{'c':'ddd'}}
    assert flatten_iterables_in_dict({'a':[None, 'b']}, min_length=1, no_null=True) == {'a':'b'}


def test_template_map():
    mapping = {
        'var1': '{{ var1 }}',
        'nest': {
            'var1': '{{ var1 }}',
            'var2': '{{ var2 }}',
            'nest1': {
                'var1': '{{ var1 }}',
                'nest2': {
                    'var2': '{{ var2 }}',
                },
                'var3': 'abc',
            }
        }
    }
    defaults = {
        'nest': {
            'var3': '{{ var3 }}',
            'nest1': {
                'var3': '{{ var3 }}'
            }
        }
    }
    template_args = {
        'var1': gen_string(20),
        'var2': gen_string(20),
        'var3': gen_string(20),
    }
    tm = TemplateMap(mapping, defaults, template_args)

    def validate_map(d: dict, path=None):
        for k, v in d.items():
            if isinstance(v, dict):
                if path:
                    path.append(k)
                else:
                    path = [k]
                validate_map(v, path)
            else:
                if k == 'var3' and path and path == ['nest', 'nest1', 'nest2']:
                    assert v == 'abc'
                elif k in template_args:
                    assert v == template_args[k]
    validate_map(tm.res)


def test_pick_one():
    assert pick_one((n for n in [range(10), range(10)])) in range(10)
