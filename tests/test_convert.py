from collections import ChainMap
import json
import pytest
from types import GeneratorType
from typing import Union

from mormo.convert import OpenAPIToPostman as oapi2pm, Route
from mormo.schema.openapi_v3 import Operation, OpenAPISchemaV3, Reference, Parameter as OpenAPIParameter


REF_OR_OPERATION = Union[dict, Operation, Reference]

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


def validate_no_ref(operation: REF_OR_OPERATION):
    assert not isinstance(operation, Reference)
    if isinstance(operation, Operation):
        operation = operation.to_dict()
    assert isinstance(operation, dict)
    for k, v in operation.items():
        if isinstance(v, REF_OR_OPERATION.__args__):
            validate_no_ref(v)
        elif isinstance(v, list):
            for i in v:
                if isinstance(i, REF_OR_OPERATION.__args__):
                    validate_no_ref(i)
        assert k != '$ref'
        assert k != 'ref', 'Unaliased reference key should not exist'


# def test_unresovled_refs(mormo):
#     for _, __, operation in mormo.routes:
#         validate_no_ref(operation)


def test_to_postman_collection_v2(mormo):
    postman_collection = mormo.to_postman_collection_v2()
    if mormo.host:
        assert mormo.host == postman_collection.variable[0].value
    global_vars = [v.id for v in postman_collection.variable]
    for verb, path, operation in mormo.routes:
        for param in mormo._resolve_object(operation.parameters or []):
            param = mormo._resolve_object(param, new_cls=OpenAPIParameter)
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
                    #print(param.name, request_vars, global_vars, collection_item.request)
                    #if collection_item.request.url.path == mormo.path_parts(path):
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
            param = mormo._resolve_object(param, new_cls=OpenAPIParameter)
            assert param.name in fake_data[param.in_.value]


def test_convert_parameters(mormo):
    for verb, path, operation in mormo.routes:
        (
            global_variables, request_url_variables,
            request_header, request_body
        ) = mormo.convert_parameters(path, operation)
        by_name = {
            'global': {v.id: v for v in global_variables},
            'request': {v.key: v for v in request_url_variables},
            'body': {k: v for k, v in (request_body.raw or {}).items()},
            'query': {v.key: v for v in request_body.urlencoded or []},
            'header': {v.key: v for v in request_header},
        }
        by_name['path'] = ChainMap(by_name['request'], by_name['global'])
        for param in mormo._resolve_object(operation.parameters or []):
            param = mormo._resolve_object(param, new_cls=OpenAPIParameter)
            in_ = param.in_.value
            if not param.required:
                continue
            assert param.name in by_name[in_]
            if param.example:
                assert param.example == by_name[in_][param.name].value
            if param.examples:
                assert param.examples[0] == by_name[in_][param.name].value


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
