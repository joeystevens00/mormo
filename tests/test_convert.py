from collections import ChainMap
import tempfile
import json
import pytest
from types import GeneratorType
from typing import Union

from mormo.convert import OpenAPIToPostman as oapi2pm, ParameterBuilder, PostmanVariables, Route
from mormo.schema import TestData
from mormo.schema import postman_collection_v2 as pm
from mormo.schema.openapi_v3 import Operation, OpenAPISchemaV3, Reference, Parameter, ParameterSchema


REF_OR_OPERATION = Union[dict, Operation, Reference]

def test_invalid_schema():
    f = tempfile.mktemp(suffix='.json')
    with open(f, 'w') as fp:
        json.dump(['a'], fp)
    with pytest.raises(ValueError) as excinfo:
        oapi2pm(path=f)
    assert "expected dict not list" in str(excinfo)


def test_no_args():
    with pytest.raises(ValueError) as excinfo:
        oapi2pm()
    assert "required field" in str(excinfo)


def test_load_schema_invalid_file_type():
    with pytest.raises(ValueError) as excinfo:
        oapi2pm(path='schema.tf')
    assert "Unknown file type" in str(excinfo)


def test_parameter_builder_mapped_value(mormo):
    for verb, path, operation in mormo.routes:
        pb = ParameterBuilder(mormo, verb, path, operation, [])
        for param in mormo._resolve_object(operation.parameters or []):
            param = mormo._resolve_object(param, new_cls=Parameter)
            if not param.required:
                continue
            mapped_value = pb.get_mapped_value(param.in_.value)
            assert mapped_value[param.name]
            if param.example:
                assert param.example == mapped_value[param.name]
            if param.examples:
                assert param.examples[0] == mapped_value[param.name]
            assert pb.build_test_data_from_param(param, mapped_value).value == str(mapped_value[param.name])


@pytest.mark.parametrize("build_params, postman_variables", [
    (
        ['POST', '/test/route({id})', Operation(
            parameters=[Parameter(**{
                'in': 'path',
                'required': True,
                'name': 'id',
                'schema': {'type':'string'},
                'example': '1',
            })],
            responses={},
        ),
        []],
        PostmanVariables(global_=[pm.Variable(**{'id':'id', 'value':'1', 'type':'string'})], query=[], url=[], header=[], body=None),
    ),
    (
        ['POST', '/test/route', Operation(
            parameters=[Parameter(**{
                'in': 'query',
                'required': True,
                'name': 'id',
                'schema': {'type':'string'},
                'example': '1',
            })],
            responses={},
        ),
        []],
        PostmanVariables(global_=[], query=[pm.Parameter(key='id', value='1')], url=[], header=[], body=None),
    ),
    (
        ['POST', '/test/{id}', Operation(
            parameters=[Parameter(**{
                'in': 'path',
                'required': True,
                'name': 'id',
                'schema': {'type':'string'},
                'example': '1',
            })],
            responses={},
        ),
        []],
        PostmanVariables(global_=[], query=[], url=[pm.Parameter(key='id', value='1')], header=[], body=None),
    ),
    (
        ['POST', '/test/{id}', Operation(
            parameters=[Parameter(**{
                'in': 'path',
                'required': True,
                'name': 'id',
                'schema': {'type':'string'},
            })],
            responses={},
        ),
        [TestData(route='POST /test/{id}', in_='path', key='id', value='1')]],
        PostmanVariables(global_=[], query=[], url=[pm.Parameter(key='id', value='1')], header=[], body=None),
    ),
    (
        ['POST', '/test/route', Operation(
            parameters=[Parameter(**{
                'in': 'header',
                'required': True,
                'name': 'id',
                'schema': {'type':'string'},
                'example': '1',
            })],
            responses={},
        ),
        []],
        PostmanVariables(global_=[], query=[], url=[], header=[pm.Parameter(key='id', value='1')], body=None),
    ),
])
def test_parameter_builder_build(build_params, postman_variables):
    mormo = oapi2pm(schema_=OpenAPISchemaV3(
        openapi='3',
        paths={build_params[1]: {
            build_params[0].lower(): build_params[2]
        }},
    ))
    pb = ParameterBuilder(mormo, *build_params)
    assert pb.build() == postman_variables


def test_find_ref():
    assert oapi2pm.find_ref('#/abc/~1b~1/~0/a', {'abc': {'/b/': {'~': {'a': 1}}}}) == 1


def test_path_parts():
    assert oapi2pm.path_parts('/abc/{id}') == ['abc', ':id']
    assert oapi2pm.path_parts('/project({project_id})') == ['project{{project_id}}']


@pytest.mark.parametrize("url", [
    "https://raw.githubusercontent.com/OAI/OpenAPI-Specification/master/examples/v3.0/petstore-expanded.yaml",
    "https://raw.githubusercontent.com/OAI/OpenAPI-Specification/master/examples/v3.0/link-example.yaml",
])
def test_load_remote_refs(url):
    schema = oapi2pm.load_remote_refs(url)
    assert OpenAPISchemaV3(**schema).openapi


def validate_http_verb(verb):
    assert verb.lower() in ['post', 'get', 'delete', 'put', 'patch']


def test_to_postman_collection_v2(mormo):
    postman_collection = mormo.to_postman_collection_v2()
    if mormo.host:
        assert mormo.host == postman_collection.variable[0].value
    global_vars = [v.id for v in postman_collection.variable]
    for verb, path, operation in mormo.routes:
        for param in mormo._resolve_object(operation.parameters or []):
            param = mormo._resolve_object(param, new_cls=Parameter)
            if not param.required:
                continue
            if param.in_.value == 'path':
                param_in_global_vars = param.name in global_vars
                param_in_request_vars = False
                request_vars = None
                for collection_item in postman_collection.item:
                    if mormo.path_parts('/'.join(collection_item.request.url.path)) != mormo.path_parts(path):
                        continue
                    request_vars = [v.key for v in collection_item.request.url.variable]
                    param_in_request_vars = param.name in request_vars
                    param_in_vars = param_in_global_vars or param_in_request_vars
                    assert param_in_vars, f"{param.name} in request_vars({request_vars}) or global_vars({global_vars}) for path({path})"
    col = postman_collection.dict(by_alias=True)
    assert col['item']
    assert col['info']['_postman_id']
    assert col['info']['name']
    assert col['info']['schema']
    assert col['info']['description']
    assert col['info']['description']['content']
    assert col['info']['description']['type']


def test_fake_data_route_schema(mormo):
    for verb, path, operation in mormo.routes:
        fake_data = mormo.fake_data_from_route_schema(path, operation).dict()
        for param in mormo._resolve_object(operation.parameters or []):
            param = mormo._resolve_object(param, new_cls=Parameter)
            assert param.name in fake_data[param.in_.value]


def test_convert_parameters(mormo):
    for verb, path, operation in mormo.routes:
        (
            global_variables, query, request_url_variables,
            request_header, request_body
        ) = mormo.convert_parameters(verb, path, operation)
        by_name = {
            'global': {v.id: v for v in global_variables},
            'request': {v.key: v for v in request_url_variables},
            'body': {k: v for k, v in ((request_body and request_body.raw) or {}).items()},
            'query': {v.key: v for v in query},
            'header': {v.key: v for v in request_header},
        }
        by_name['path'] = ChainMap(by_name['request'], by_name['global'])
        for param in mormo._resolve_object(operation.parameters or []):
            param = mormo._resolve_object(param, new_cls=Parameter)
            in_ = param.in_.value
            if not param.required:
                continue
            assert param.name in by_name[in_]
            if param.example:
                assert str(param.example) == by_name[in_][param.name].value
            if param.examples:
                assert str(param.examples[0]) == by_name[in_][param.name].value


def test_guess_resource():
    assert oapi2pm.guess_resource('/pets') == 'pets'
    assert oapi2pm.guess_resource('/pets/{petId}') == 'pets'
    assert oapi2pm.guess_resource('/pets/{{petId}}') == 'pets'
    assert oapi2pm.guess_resource('/store/{{storeId}}/pets') == 'pets'
    assert oapi2pm.guess_resource('/store/{{storeId}}/pets/{petId}') == 'pets'
    assert oapi2pm.guess_resource('/store/catalog/pets') == 'pets'
    assert oapi2pm.guess_resource("/project({project_id})") == 'project'


def test_order_routes_by_resource():
    get = Route('get', '/pets', 'getpets')
    delete = Route('delete', '/pets', 'delpets')
    post = Route('post', '/pets', 'delpets')
    put = Route('put', '/pets', 'putpets')
    patch = Route('patch', '/pets', 'patchpets')
    ordering = ['post', 'put', 'get', 'patch', 'delete']
    assert oapi2pm.order_routes_by_resource(
        [get, delete, post], verb_ordering=ordering
    ) == [post, get, delete]
    assert oapi2pm.order_routes_by_resource(
        [delete, get, patch, put, post], verb_ordering=ordering
    ) == [post, put, get, patch, delete]
