import json
import pkg_resources
from jsonschema import validate

from mormo.schema.postman_collection_v2 import Script


def test_postman_schema(postman_collection):
    postman_schema = json.loads(pkg_resources.resource_string('mormo', '../tests/data/collection_2_1_0.json'))
    validate(instance=postman_collection.to_dict(), schema=postman_schema)


def test_script_add():
    a = Script(type='text/javascript', name='a', exec='a')
    b = Script(type='text/html', name='b', exec=['b', 'b1'])
    c = a + b
    assert c.type == a.type, 'Type on left side of operand is used'
    assert c.name == a.name, 'Name on left side of operand is used'
    assert c.exec == [a.exec, *b.exec], 'Exec is combined'
