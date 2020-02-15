import json
import pkg_resources
from jsonschema import validate


def test_postman_schema(postman_collection):
    postman_schema = json.loads(pkg_resources.resource_string('mormo', '../tests/data/collection_2_1_0.json'))
    validate(instance=postman_collection.to_dict(), schema=postman_schema)
