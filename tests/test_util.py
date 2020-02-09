import uuid
from mormo.util import flatten_iterables_in_dict, get_http_reason, uuidgen

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
