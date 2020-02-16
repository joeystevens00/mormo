from hypothesis import given
from hypothesis_jsonschema._from_schema import from_schema

from mormo.schema import TestData, list_of_test_data_to_params, openapi_v3


random_test_data = from_schema({
    'type': 'object',
    'required': ['key', 'value'],
    'properties': {
        'key': {'type': 'string', 'minLength': 2},
        'value': {'type': 'string', 'minLength': 2},
    }
})


@given(random_test_data)
def test_test_data_to_hash(data):
    for route in ['POST /ab', 'GET /ab', 'POST /ab/:a']:
        d = {data['key']: data['value']}
        test_data = []
        for k, v in d.items():
            for in_ in list(openapi_v3.ParameterIn):
                test_data.append(
                    TestData(route=route, in_=in_, key=k, value=v)
                )
        v = list_of_test_data_to_params(route, test_data).dict()
        for td in test_data:
            assert v[td.in_.value][td.key] == d[td.key]
