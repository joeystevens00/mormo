from mormo.postman_test import javascript, new_event
from mormo.schema.postman_collection_v2 import Script


def test_javascript():
    j = javascript('a', 'b')
    assert isinstance(j, Script)
    assert j.type == 'text/javascript'
    assert j.exec == 'b'
    assert j.name == 'a'


def test_new_event():
    scripts = [Script(type='text/javascript', name=str(i), exec=str(i)) for i in range(5)]
    e = new_event('test', scripts)
    assert e.listen == 'test'
    for i in range(5):
        assert e.script.exec[i] == scripts[i].exec[0]


def test_run_newman(postman_collection):
    res = postman_collection.run(host=None, json=True)
    assert 'invalid uri' in res.json_['run']['failures'][0]['error']['message'].lower()
