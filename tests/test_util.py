import json
import tempfile
import uuid
import yaml

from mormo.util import (
    flatten_iterables_in_dict,
    get_http_reason,
    load_file,
    uuidgen,
    strip_nulls,
    trim,
)


def get_lens(x):
    return [len(i) for i in str(x).split('-')]


def test_get_http_reason():
    assert get_http_reason(200) == "OK", "Defined reason returns definition"
    assert get_http_reason(299) == "Success - The action was successfully received, "\
        "understood, and accepted", "Undefined reason returns class definition"


def test_secure_uuidgen_behaves_like_uuid1():
    for i in range(10):
        assert get_lens(uuidgen()) == get_lens(uuid.uuid1())


def test_flatten_iterables_in_dict():
    assert flatten_iterables_in_dict({'a':['b', 'bb'], 'b': {'c':['ddd']}}, min_length=2) == {'a':'bb', 'b':{'c':'ddd'}}
    assert flatten_iterables_in_dict({'a':[None, 'b']}, min_length=1, no_null=True) == {'a':'b'}


def test_trim():
    assert trim(" a ") == "a"
    assert trim("   a  ") == "a"


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
