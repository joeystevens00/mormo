import json
import pkg_resources
from jsonschema import validate

from mormo.schema.openapi_v3 import OpenAPISchemaV3

def test_openapi_schema():
    openapi_schema = json.loads(pkg_resources.resource_string('mormo', '../tests/data/openapi_3.json'))
    mormo_api_schema = json.loads(pkg_resources.resource_string('mormo', '../tests/data/openapi/json/openapi.json'))

    validate(instance=mormo_api_schema, schema=OpenAPISchemaV3(**mormo_api_schema).to_dict())
