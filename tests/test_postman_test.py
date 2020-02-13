import tempfile

from mormo.postman_test import run_newman


def test_run_newman(postman_collection):
    f = tempfile.mktemp()
    postman_collection.to_file(f)
    res = run_newman(f, host=None, json=True)
    assert 'invalid uri' in res.json_['run']['failures'][0]['error']['message'].lower()
