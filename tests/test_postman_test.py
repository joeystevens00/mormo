import json
import pkg_resources
from jsonschema import validate

from mormo.postman_test import run_newman


def test_run_newman(postman_collection):
    res = postman_collection.run(host=None, json=True)
    assert 'invalid uri' in res.json_['run']['failures'][0]['error']['message'].lower()

def test_postman_schema(postman_collection):
    postman_schema = json.loads(pkg_resources.resource_string('mormo', '../tests/data/collection_2_1_0.json'))
    validate(instance=postman_collection.to_dict(), schema=postman_schema)
# Need to validate postman_collection against json schema validator
