import os
from collections import defaultdict, ChainMap, Counter, namedtuple
from typing import Generator, Iterable, List, Optional
import json
import re
import yaml

from .postman_test import (
    new_event, javascript, js_test_code,
    js_test_content_type, js_test_response_time,
)
from .schema import (
    Expect, OpenAPISchemaToPostmanRequest, TestData, TestConfig,
    list_of_test_data_to_params,
)
from .schema import openapi_v3 as oapi
from .schema.openapi_v3 import (
    Operation, OpenAPISchemaV3, ParameterIn,
    ParameterRequestData, Reference,
)
from .schema.postman_collection_v2 import (
    Auth, Collection, Item,
    Request, RequestBody, Response, OriginalRequest, Header,
    Info, Description, Parameter, Url, Variable,
)
from .util import (
    blind_load,
    fingerprint, flatten_iterables_in_dict, generate_from_schema,
    get_http_reason, hashable_lru, load_file, pick_one,
    uuidgen, trim, HTTP_VERBS,
)
from . import logger

RE_PATH_VARIABLE = re.compile('\{(.*?)\}')  # noqa: W605
RE_PATH_GLOBAL_VARIABLE = re.compile('\{\{(.*?)\}\}')  # noqa: W605
RE_PATH_VARIABLE_SEGMENT = re.compile('(\(\{(.*?)\}\))')  # noqa: W605
RE_PATH_CONVERTED_VARIABLE_SEGMENT = re.compile('(\{\{(.*?)\}\})')  # noqa: W605

Route = namedtuple('Route', ['verb', 'path', 'operation'])
ReferenceSearch = namedtuple('ReferenceSearch', ['ref', 'schema'])
PostmanConfig = namedtuple('PostmanConfig', [
    'expect',
    'test_data',
    'test_scripts',
    'prerequest_scripts',
    'postman_global_variables',
    'collection_test_scripts',
    'collection_prerequest_scripts',
])


class OpenAPIToPostman:
    def __init__(
        self,
        request: Optional[OpenAPISchemaToPostmanRequest] = None,
        **kwargs,
    ):
        if not request:
            request = OpenAPISchemaToPostmanRequest(**kwargs)
        self.schema = None
        self.host = request.host
        self.max_ref_depth = 5
        self.ref_depth = Counter()
        self.strict = True
        self.test_scripts = defaultdict(lambda: [], request.test_scripts or [])
        self.prerequest_scripts = defaultdict(lambda: [], request.prerequest_scripts or [])  # noqa: E501
        self.collection_test_scripts = request.collection_test_scripts or []
        self.collection_prerequest_scripts = request.collection_prerequest_scripts or []  # noqa: E501
        self.postman_global_variables = request.postman_global_variables or []
        self.default_expect = Expect()
        self.expect = request.expect or defaultdict(self.get_default_expect)
        path = request.path
        schema = request.schema_
        if path:
            if path.endswith('.json'):
                self.schema = OpenAPISchemaV3.parse_file(path)
            elif path.endswith('.yaml') or path.endswith('.yml'):
                with open(path, "r") as f:
                    self.schema = yaml.safe_load(f)
            else:
                raise ValueError(f"Unknown file type for: {path}")
        elif schema:
            self.schema = schema
        else:
            raise ValueError(
                "Either path to schema or schema is a required field",
            )
        if isinstance(self.schema, OpenAPISchemaV3):
            self.schema = self.schema.to_dict(no_empty=False)
        if not isinstance(self.schema, dict):
            raise ValueError("Could not load schema")
        if request.resolve_references:
            self.schema = self.resolve_refs(self.schema)
        # Validate schema
        self.schema = OpenAPISchemaV3(**self.schema)
        self.test_data = self.load_test_data(
            request.test_data or [],
            request.test_data_file,
            request.test_config,
        )

    @classmethod
    def load_remote_refs(cls, schema_path):
        if isinstance(schema_path, str) and schema_path.startswith('http'):
            import requests
            ref_path = None
            if '#' in schema_path:
                ref_path = schema_path.split('#')[-1]
            try:
                logger.debug(f"Fetching remote reference: {schema_path}")
                schema_path = blind_load(requests.get(schema_path).content.decode('utf-8'))
                if ref_path:
                    schema_path = cls.find_ref(ref_path, schema_path)
            except Exception as e:
                logger.error(f"Exception: {type(e)}: {e}")
                raise e
        return schema_path

    @classmethod
    def load_local_refs(cls, schema_path):
        if isinstance(schema_path, str) and os.path.exists(schema_path):
            schema_path = load_file(schema_path)
        return schema_path

    @classmethod
    @hashable_lru
    def find_ref(cls, ref: str, schema_path):
        ref_path = ref.split('/')[1:]
        while len(ref_path):
            seek = ref_path.pop(0).replace('~1', '/').replace('~0', '~')
            if seek:
                if isinstance(schema_path, list) and seek.isdigit():
                    schema_path = schema_path[int(seek)]
                else:
                    schema_path = schema_path[seek]
        schema_path = cls.load_remote_refs(schema_path)
        schema_path = cls.load_local_refs(schema_path)

        return schema_path

    @classmethod
    def resolve_refs(cls, schema: dict):
        """Replace OpenAPI references in schema with Python references.

        Leaves the '$ref' key but points the value to the path in the schema."""
        logger.debug("Resolving references in schema")
        if isinstance(schema, OpenAPISchemaV3):
            schema = schema.to_dict()

        def traverse(d: dict):
            for k, v in d.copy().items():
                if isinstance(v, dict):
                    schema_ref = None
                    found_parent = None
                    # TODO: Support escape chars '~0' escapes '~' '~1' escapes '/'
                    # #/paths/~1cases~1/post/responses/200/content/application~1json/schema/properties/createdBy/oneOf/1
                    #
                    # TODO: Support array indexing (see above example)
                    for p in v.keys():
                        if isinstance(v[p], list):
                            for i, e in enumerate(v[p]):
                                if isinstance(e, dict):
                                    schema_ref = e.get('$ref')
                                    if schema_ref:
                                        v[p][i] = cls.find_ref(schema_ref, schema)
                                    else:
                                        logger.debug(
                                            f"No $ref found in List[dict]: {e}",
                                        )
                        if not isinstance(v[p], dict):
                            continue
                        if not schema_ref:
                            schema_ref = v.get(p, {}).get('$ref')
                            if schema_ref:
                                found_parent = p
                    if schema_ref and schema_ref.startswith('#/') and found_parent:
                        v[found_parent] = cls.find_ref(schema_ref, schema)
                    traverse(v)
            return d
        return traverse(schema)


    @classmethod
    def path_parts(cls, path: str) -> list:
        url = []
        for part in path.split('/')[1:]:
            is_path_variable = re.match('^{(\w+)}$', part)  # noqa: W605
            is_path_segment = RE_PATH_VARIABLE.findall(part)
            queries = RE_PATH_VARIABLE_SEGMENT.findall(part)
            if is_path_variable:
                part = f':{is_path_variable.group(1)}'
            elif is_path_segment:
                for group in is_path_segment:
                    part = part.replace(f"{{{group}}}", f"{{{{{group}}}}}")
            if '(' in part and ')' in part:
                part = part.replace('(', '').replace(')', '')
            url.append(part)
        return url

    def get_default_expect(self):
        return self.default_expect

    def test_config_to_postman_config(self, test_config) -> PostmanConfig:
        test_data = []
        expect = defaultdict(lambda: self.default_expect)
        test_scripts = defaultdict(lambda: [])
        prerequest_scripts = defaultdict(lambda: [])
        postman_global_variables = []
        collection_test_scripts = []
        collection_prerequest_scripts = []
        for route, td_item in test_config.items():
            i = TestConfig(**td_item)
            if isinstance(i.variables, str):
                variables = load_file(i.variables)
            else:
                variables = i.variables
            if route.lower() == 'collection':
                postman_global_variables.extend([
                    Variable(id=k, type='string', value=v)
                    for k, v in (variables or {}).items()
                ])
                if i.expect:
                    self.default_expect = i.expect
                if i.test:
                    collection_test_scripts.extend([
                        javascript(
                            exec=t,
                            name=f"{route} cmd({fingerprint(t)})"
                        ) for t in i.test
                    ])
                if i.prerequest:
                    collection_prerequest_scripts.extend([
                        javascript(
                            exec=t,
                            name=f"{route} cmd({fingerprint(t)})"
                        ) for t in i.prerequest
                    ])
                continue

            for variable, response_path in (i.make_global or {}).items():
                response_path = ''.join([
                    '["' + trim(p) + '"]'
                    for p in response_path.split('.')[1:]
                ])
                debug_global = lambda x: javascript(
                    name=f'[{x}] Debug {variable}',
                    exec=f'console.log("[{x}] GLOBAL({variable}):", pm.globals.get("{variable}"));',  # noqa: E501
                )
                collection_prerequest_scripts.append(
                    debug_global('collection_prerequest'),
                )
                prerequest_scripts[route].append(
                    debug_global('prerequest'),
                )
                test_scripts[route].append(javascript(
                    name=f'Set response of {route}: JSON_RESPONSE{response_path} to {variable}',  # noqa: E501
                    exec="""
                        pm.test('set {variable}', function() {{
                            pm.globals.set("{variable}", pm.response.json(){response_path});
                        }});
                    """.format(variable=variable, response_path=response_path),  # noqa: E501
                ))
            # self.postman_global_variables.append(
            # Variable(id=variable, type='string', value='default'))
            for k, v in (variables or {}).items():
                test_data.extend([
                    TestData(route=route, in_=in_, key=k, value=v)
                    for in_ in list(ParameterIn)
                ])
            if i.expect:
                expect[route] = i.expect

            if i.test:
                test_scripts[route].extend([
                    javascript(
                        exec=t,
                        name=f"{route} cmd({fingerprint(t)})",
                    ) for t in i.test
                ])
            if i.prerequest:
                prerequest_scripts[route].extend([
                    javascript(
                        exec=t,
                        name=f"{route} cmd({fingerprint(t)})",
                    ) for t in i.prerequest
                ])
        for verb, path, operation in self.routes:
            route_str = f"{verb.upper()} {path}"
            for code, response in operation.responses.items():
                if code == 'default':
                    code = 500
                appended_test_scripts = False
                for mimetype, route_definition in (response.content or {}).items():
                    if appended_test_scripts:
                        continue
                    candidate_route = (
                        (expect[route_str].code == code and expect[route_str].enabled)
                        or str(code).startswith('2')
                    )
                    if candidate_route:
                        test_scripts[route_str].append(
                            js_test_code(route_str, code),
                        )
                        test_scripts[route_str].append(
                            js_test_content_type(route_str, mimetype),
                        )
                        test_scripts[route_str].append(
                            js_test_response_time(
                                route_str,
                                expect[route_str].response_time,
                            )
                        )
                        appended_test_scripts = True
        return PostmanConfig(
            expect, test_data, test_scripts,
            prerequest_scripts, postman_global_variables,
            collection_test_scripts, collection_prerequest_scripts,
        )

    def load_test_data(
        self, test_data, test_data_file=None,
        test_config=None,
    ):
        if not (test_data_file or test_config):
            return test_data
        if test_data_file:
            test_config = load_file(test_data_file)
        postman_config = self.test_config_to_postman_config(test_config)
        self.test_scripts.update(postman_config.test_scripts)
        self.prerequest_scripts.update(postman_config.prerequest_scripts)
        self.postman_global_variables.extend(postman_config.postman_global_variables)
        self.collection_test_scripts.extend(postman_config.collection_test_scripts)
        self.collection_prerequest_scripts.extend(postman_config.collection_prerequest_scripts)
        test_data.extend(postman_config.test_data)
        return test_data

    @property
    def paths(self):
        for path in self.schema.paths:
            yield (path, self.schema.paths[path])

    @property
    def tags(self):
        tags = set()
        for path in self.paths:
            for _, definition in path[1].items():
                tags = tags.union(set(definition.get_safe('tags', [])))
        return tags

    @classmethod
    def guess_resource(cls, path: str):
        parts = cls.path_parts(path)
        last_part = None
        for i, part in enumerate(parts):
            is_variable = RE_PATH_GLOBAL_VARIABLE.match(part)\
                or part.startswith(':')
            segments = RE_PATH_CONVERTED_VARIABLE_SEGMENT.findall(part)
            for segment, var in segments:
                part = part.replace(segment, '')
            # If this segment is a variable, return the last one
            if is_variable and len(parts) - i == 1:
                return last_part
            last_part = part
        return last_part

    @classmethod
    def order_routes_by_resource(
        cls, routes: Iterable[Route],
        verb_ordering: Optional[List] = None
    ) -> List[Route]:
        """Identify REST resources and order CRUD operations safely."""
        by_resource = defaultdict(lambda: {})
        output = []
        if not verb_ordering:
            verb_ordering = ['post', 'put', 'get', 'patch', 'delete']
        for route in routes:
            verb, path, operation = route
            by_resource[cls.guess_resource(path)][verb] = route
        for resource, routes_by_verb in by_resource.items():
            for verb in verb_ordering:
                if routes_by_verb.get(verb):
                    output.append(routes_by_verb[verb])
        return output

    def fake_data_from_route_schema(
        self, path: str, operation: Operation,
    ) -> ParameterRequestData:
        d = defaultdict(lambda: {})
        all_path_vars = RE_PATH_VARIABLE.findall(path)
        parameters = self._resolve_object(operation.parameters)

        if parameters:
            for parameter in operation.parameters:
                parameter = self._resolve_object(
                    parameter,
                    new_cls=oapi.Parameter,
                )
                in_ = parameter.in_.value
                param_schema = parameter.schema_
                if in_ == 'body':
                    properties = param_schema.properties or {}
                    if isinstance(properties, Reference):
                        properties = properties.resolve_ref(self.schema)
                    for param, param_schema in properties.items():
                        d[in_][param] = pick_one(
                            generate_from_schema(param_schema),
                        )
                else:
                    d[in_][parameter.name] = pick_one(
                        generate_from_schema(param_schema.to_dict()),
                    )
        request_body = self._resolve_object(
            operation.requestBody,
            new_cls=oapi.RequestBody,
        )
        if request_body:
            for mimetype, media_type in request_body.content.items():
                mt_props = self._resolve_object(
                    media_type.schema_.properties or {},
                )
                for name, prop in mt_props.items():
                    prop = self._resolve_object(prop)
                    if not isinstance(prop, dict):
                        prop = prop.to_dict()
                    if prop.get('ref') or prop.get('$ref'):
                        logger.error(f"Unresolved reference in media type! {media_type}")  # noqa; E501
                    d['requestBody'][name] = pick_one(
                        generate_from_schema(prop),
                    )
        for path_var in set(all_path_vars).difference(set(d.get('path', []))):
            logger.warning(
                f"Path variable {path_var} isn't defined as a parameter "
                f" generating test data for it assuming it's a string."
            )
            d['path'][path_var] = pick_one(
                generate_from_schema({'type': 'string'}),
            )
        d = dict(d)
        return ParameterRequestData(**d)

    @property
    def routes(self) -> Generator[Route, None, None]:
        for path, operation in self.paths:
            for verb, operation in [
                (verb, operation.get_safe(verb))
                for verb in HTTP_VERBS if operation.get_safe(verb)
            ]:
                yield Route(verb, path, operation)

    @property
    def info(self):
        return self.schema.info

    @property
    def title_version(self):
        return f"{self.info.title} {self.info.version}"

    def operation_param_examples(self, operation: Operation):
        examples = defaultdict(lambda: defaultdict(lambda: []))
        for param in self._resolve_object(operation.parameters or []):
            param = self._resolve_object(param, new_cls=oapi.Parameter)
            if param.example:
                examples[param.in_.value][param.name].extend([param.example])
            if param.examples:
                examples[param.in_.value][param.name].extend(param.examples)
        return examples

    def _resolve_object(self, o, new_cls=None):
        if isinstance(o, Reference):
            logger.debug(f"Resolving reference {o.ref} Try #{self.ref_depth[o.ref]}")  # noqa; E501
            if self.ref_depth[o.ref] > self.max_ref_depth:
                if self.strict:
                    raise ValueError(f"Max reference recursion reached for {o.ref}")  # noqa; E501
                else:
                    return
            self.ref_depth[o.ref] += 1
            o = o.resolve_ref(self.schema)
        if isinstance(o, dict):
            if new_cls:
                o = new_cls(**o)
        return o

    def convert_parameters(self, verb, path, operation: Operation):
        params = defaultdict(lambda: {})
        config_test_data = list_of_test_data_to_params(f"{verb} {path}", self.test_data).dict()
        fake_data = self.fake_data_from_route_schema(path, operation).dict()
        examples = flatten_iterables_in_dict(
            self.operation_param_examples(operation),
        )
        request_headers = []
        request_url_variables = []
        global_variables = []
        query = []
        kwargs = {}
        params = self._resolve_object(operation.parameters or [])
        path_vars = [p[1:] for p in self.path_parts(path) if p.startswith(':')]
        segment_vars = set(RE_PATH_VARIABLE.findall(path))\
            .difference(path_vars)
        for param in params:
            param = self._resolve_object(param, new_cls=oapi.Parameter)
            param_in = param.in_.value
            # Parameter precedence:
            # Test Data,
            # Examples in OpenAPI Schema,
            # Fake Data generated from OpenAPI Schema
            mapped_value = ChainMap(
                config_test_data.get(param_in, {}),
                examples.get(param_in, {}),
                fake_data.get(param_in, {}),
            )
            if param.required:
                test_data = None
                if param_in != 'body':
                    test_data = Parameter(
                        key=param.name,
                        value=str(mapped_value[param.name]),
                    )
                if param_in == 'path':
                    # If path param not defined in path
                    found_var_location = False
                    for v in segment_vars:
                        if v == param.name:
                            if v in mapped_value:
                                global_variables.append(
                                    Variable(
                                        id=v, type='string',
                                        value=str(mapped_value[v])
                                    )
                                )
                                found_var_location = True
                            else:
                                logger.error(f"Path segment {v} not mapped to a value.")  # noqa; E501
                    if found_var_location:
                        continue
                    if param.name not in path_vars:
                        not_processed_path_vars = set(path_vars).difference(
                            {v.key for v in request_url_variables},
                        )
                        if len(not_processed_path_vars) > 1:
                            err = f"Path variable ({param.name}) not in path and multiple path variables ({not_processed_path_vars}) to choose from."  # noqa; E501
                            if self.strict:
                                logger.warning(err)
                            else:
                                raise ValueError(err)
                        elif len(not_processed_path_vars) == 1:
                            first_var = not_processed_path_vars.pop()
                            if first_var in mapped_value:
                                request_url_variables.append(
                                    Parameter(
                                        key=first_var,
                                        value=str(mapped_value[first_var]),
                                    )
                                )
                            else:
                                if mapped_value[param.name]:
                                    # if self.strict:
                                    #     raise ValueError("")
                                    logger.warning(
                                        f"Path variable doesn't exist in path ({param.name}), guessed to be path var ({path_vars[0]}) but not mapped to value"  # noqa; E501
                                        " param is mapped to a value so using that value with the guessed name."  # noqa; E501
                                    )
                                    request_url_variables.append(
                                        Parameter(
                                            key=path_vars[0],
                                            value=str(mapped_value[param.name]),
                                        )
                                    )
                                else:
                                    logger.error(f"Path variable doesn't exist in path ({param.name}).")  # noqa; E501
                        else:
                            logger.error(f"Path variable doesn't exist in path ({param.name}).")  # noqa; E501
                    else:
                        request_url_variables.append(test_data)
                elif param_in == 'query':
                    query.append(test_data)
                elif param_in == 'header':
                    request_headers.append(test_data)
                elif param_in == 'cookie':
                    raise ValueError(f"unhandled param location: {param_in}")
                elif param_in == 'body':
                    if mapped_value:
                        kwargs['mode'] = 'raw'
                        kwargs['raw'] = json.dumps(dict(mapped_value))
                        request_headers.append(
                            Parameter(
                                key='Content-Type',
                                value='application/json',
                            ),
                        )
                    else:
                        logger.warning(f"Missing content for body parameter: {param.name}")
                else:
                    raise ValueError(f"unknown param location: {param_in}")
        request_body = self._resolve_object(
            operation.requestBody,
            new_cls=oapi.RequestBody,
        )

        if (
            request_body and not kwargs.get('mode') == 'raw'
            and config_test_data.get('requestBody')
        ):
            kwargs['mode'] = 'raw'
            kwargs['raw'] = json.dumps(config_test_data.get('requestBody'))
        missing_variable = set(path_vars).difference(
            set([
                *[p.key for p in request_url_variables],
                *[p.id for p in global_variables],
            ]),
        )
        for path_var in missing_variable:
            mapped_value = ChainMap(
                config_test_data.get('path', {}),
                examples.get('path', {}),
                fake_data.get('path', {}),
            )
            if mapped_value.get(path_var):
                request_url_variables.append(
                    Parameter(
                        key=path_var,
                        value=str(mapped_value[path_var]),
                    )
                )
            else:
                logger.warning(f"Path variable {path_var} missing variable and no mapped value!")  # noqa: E501

        if kwargs:
            request_body = RequestBody(
                **kwargs,
            )
        else:
            request_body = None
        return (
            global_variables, query, request_url_variables, request_headers,
            request_body,
        )

    def _generate_postman_collections(self):
        build_url = lambda path, vars=None, query=[]: Url(
            host=["{{baseUrl}}"],
            path=self.path_parts(path),
            query=query,
            variable=vars or [],
        )
        items = []
        global_variables = self.postman_global_variables or []
        ordered_routes = self.order_routes_by_resource(self.routes)
        for verb, path, operation in ordered_routes:
            responses = []
            route_str = f"{verb.upper()} {path}"
            for code, response in operation.responses.items():
                if code == 'default':
                    code = 500
                if isinstance(code, str) and 'x' in code.lower():
                    code = code.lower().replace('x', '0')
                http_reason = get_http_reason(code)
                response = self._resolve_object(
                    response, new_cls=oapi.Response,
                )
                for mimetype, route_definition in (
                    response.content or {'text/html': {}}
                ).items():
                    responses.append(Response(
                        id=uuidgen(),
                        name=response.description,
                        originalRequest=OriginalRequest(
                            url=build_url(path),
                            method=verb.upper(),
                            body={},
                        ),
                        code=int(code),
                        status=http_reason,
                        header=[
                            Header(key='Content-Type', value=mimetype),
                        ],
                        cookie=[],
                        body=response.description,
                    ))
            (
                new_globals, query, request_url_variables,
                request_header, request_body
            ) = self.convert_parameters(verb, path, operation)
            global_variables.extend(new_globals)
            logger.debug('GLOBALS', new_globals)
            logger.debug('REQUEST', request_url_variables)
            items.append(
                Item(
                    id=uuidgen(),
                    name=operation.summary or route_str,
                    request=Request(
                        auth=Auth(type='noauth'),
                        url=build_url(path, vars=request_url_variables, query=query),
                        method=verb.upper(),
                        name=operation.summary or route_str,
                        description={},
                        body=request_body,
                        header=request_header,
                    ),
                    response=responses,
                    event=[
                        e for e in [
                            new_event(
                                'test',
                                self.test_scripts.get(route_str, []),
                            ),
                            new_event(
                                'prerequest',
                                self.prerequest_scripts.get(route_str, []),
                            ),
                        ] if e
                    ],
                )
            )

        return [
            global_variables, items
        ]

    def to_postman_collection_v2(self):
        global_variables, items = self._generate_postman_collections()
        return Collection(
            event=[
                e for e in [
                    new_event('test', self.collection_test_scripts),
                    new_event(
                        'prerequest',
                        self.collection_prerequest_scripts,
                    ),
                ] if e
            ],
            variable=[
                Variable(id='baseUrl', type='string', value=self.host or '/'),
                *global_variables,
            ],
            item=items,
            info=Info(
                _postman_id=uuidgen(),
                name=self.info.title,
                schema='https://schema.getpostman.com/json/collection/v2.1.0/collection.json',  # noqa: E501
                description=Description(
                    content=self.info.get_safe('description')\
                        or self.title_version,
                    type='text/plain',
                ),
            )
        )
