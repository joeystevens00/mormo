from mormo.postman_test import run_newman


def test_run_newman(postman_collection):
    res = postman_collection.run(host=None, json=True)
    assert 'invalid uri' in res.json_['run']['failures'][0]['error']['message'].lower()
