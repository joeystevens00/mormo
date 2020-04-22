import os
from collections import defaultdict, ChainMap, Counter, namedtuple
from typing import Generator, Iterable, List, Tuple, Optional
import json
import re
import requests
import yaml

from .model import BaseModel, ReferenceResolve
from .postman_test import (
    new_event, javascript, js_test_code,
    js_test_content_type, js_test_response_time,
    js_test_validate_schema,
)
from .schema import (
    Expect, OpenAPISchemaToPostmanRequest, PostmanTest,
    TestData, TestConfig,
    list_of_test_data_to_params,
)
from .schema import openapi_v3 as oapi
from .schema.openapi_v3 import (
    Operation, OpenAPISchemaV3, ParameterIn,
    ParameterRequestData, Reference, SchemaObject,
)
from .schema.postman_collection_v2 import (
    Auth, Collection, Item,
    Request, RequestBody, Response, OriginalRequest, Header,
    Info, Description, Parameter, Url, Variable,
)
from .util import (
    blind_load,
    fingerprint, flatten_iterables_in_dict, generate_from_schema,
    get_http_reason, hashable_lru, is_local_file_path, load_file, pick_one,
    uuidgen, trim, HTTP_VERBS,
)
from . import logger

RE_PATH_VARIABLE = re.compile(r'\{(.*?)\}')  # noqa: W605
RE_PATH_GLOBAL_VARIABLE = re.compile(r'\{\{(.*?)\}\}')  # noqa: W605
RE_PATH_VARIABLE_SEGMENT = re.compile(r'(\(\{(.*?)\}\))')  # noqa: W605
RE_PATH_CONVERTED_VARIABLE_SEGMENT = re.compile(r'(\{\{(.*?)\}\})')  # noqa: W605

Route = namedtuple('Route', ['verb', 'path', 'operation'])
ReferenceSearch = namedtuple('ReferenceSearch', ['ref', 'schema'])
PostmanConfig = namedtuple('PostmanConfig', [
    'expect',
    'test_data',
    'test_scripts',
    'prerequest_scripts',
    'collection_global_variables',
    'collection_test_scripts',
    'collection_prerequest_scripts',
])
PostmanVariables = namedtuple('PostmanVariables', [
    'global_',
    'query',
    'url',
    'header',
    'body',
])


class OpenAPIToPostman(ReferenceResolve):
    def __init__(
        self,
        request: Optional[OpenAPISchemaToPostmanRequest] = None,
        **kwargs,
    ):
        if not request:
            request = OpenAPISchemaToPostmanRequest(**kwargs)
        self.schema = None
        self.host = request.host
        self.test_scripts = defaultdict(lambda: [], request.test_scripts or [])
        self.prerequest_scripts = defaultdict(lambda: [], request.prerequest_scripts or [])  # noqa: E501
        self.collection_test_scripts = request.collection_test_scripts or []
        self.collection_prerequest_scripts = request.collection_prerequest_scripts or []  # noqa: E501
        self.collection_global_variables = request.collection_global_variables or []
        self.default_expect = Expect()
        self.expect = request.expect or defaultdict(self.get_default_expect)
        self.verbose = request.verbose
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
        elif request.target:
            self.host = request.target.split('/')[2:][0]
            self.schema = requests.get(request.target).json()
        else:
            raise ValueError(
                "Either path to schema, URL to OpenAPI schema, or schema is a required field",
            )
        if isinstance(self.schema, OpenAPISchemaV3):
            self.schema = self.schema.to_dict(no_empty=False)
        # Validate schema
        self.schema = OpenAPISchemaV3(**self.schema)
        self.test_data = self.load_test_data(
            request.test_data or [],
            request.test_data_file,
            request.test_config,
        )
        self.strict = True

    @classmethod
    def path_parts(cls, path: str) -> list:
        url = []
        for part in path.split('/')[1:]:
            is_path_variable = re.match(r'^{(\w+)}$', part)  # noqa: W605
            is_path_segment = RE_PATH_VARIABLE.findall(part)
            # queries = RE_PATH_VARIABLE_SEGMENT.findall(part)
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
        expect = defaultdict(self.get_default_expect)
        test_scripts = defaultdict(lambda: [])
        prerequest_scripts = defaultdict(lambda: [])
        collection_global_variables = []
        collection_test_scripts = []
        collection_prerequest_scripts = []
        for route, td_item in test_config.items():
            i = td_item
            if isinstance(i, dict):
                i = TestConfig(**td_item)
            if isinstance(i.variables, str):
                variables = load_file(i.variables)
            else:
                variables = i.variables
            if route.lower() == 'collection':
                collection_global_variables.extend([
                    Variable(id=k, type='string', value=v)
                    for k, v in (variables or {}).items()
                ])
                if i.expect:
                    self.default_expect = i.expect
                if i.test:
                    collection_test_scripts.extend([
                        javascript(
                            cmd=t,
                            name=f"{route} cmd({fingerprint(t)})"
                        ) for t in i.test
                    ])
                if i.prerequest:
                    collection_prerequest_scripts.extend([
                        javascript(
                            cmd=t,
                            name=f"{route} cmd({fingerprint(t)})"
                        ) for t in i.prerequest
                    ])
                continue
            verb, path = route.split(' ')
            route = f'{verb.upper()} {path}'
            for variable, response_path in (i.make_global or {}).items():
                response_path = ''.join(
                    '["' + trim(p) + '"]'
                    for p in response_path.split('.')[1:]
                )
                debug_global = lambda x: javascript(
                    name=f'[{x}] Debug {variable}',
                    cmd=f'console.log("[{x}] GLOBAL({variable}):", pm.globals.get("{variable}"));',  # noqa: E501
                )
                collection_prerequest_scripts.append(
                    debug_global('collection_prerequest'),
                )
                prerequest_scripts[route].append(
                    debug_global('prerequest'),
                )
                test_scripts[route].append(javascript(
                    name=f'Set response of {route}: JSON_RESPONSE{response_path} to {variable}',  # noqa: E501
                    cmd="""
                        pm.test('set {variable}', function() {{
                            pm.globals.set("{variable}", pm.response.json(){response_path});
                        }});
                    """.format(variable=variable, response_path=response_path),  # noqa: E501
                ))
            # self.collection_global_variables.append(
            # Variable(id=variable, type='string', value='default'))
            for k, v in (variables or {}).items():
                if is_local_file_path(v):
                    v = load_file(v)
                test_data.extend([
                    TestData(route=route, in_=in_, key=k, value=v)
                    for in_ in list(ParameterIn)
                ])
            if i.expect:
                expect[route] = i.expect

            if i.test:
                test_scripts[route].extend([
                    javascript(
                        cmd=t,
                        name=f"{route} cmd({fingerprint(t)})",
                    ) for t in i.test
                ])
            if i.prerequest:
                prerequest_scripts[route].extend([
                    javascript(
                        cmd=t,
                        name=f"{route} cmd({fingerprint(t)})",
                    ) for t in i.prerequest
                ])
        for verb, path, operation in self.routes:
            route_str = f"{verb.upper()} {path}"
            for code, response in operation.responses.items():
                if code == 'default':
                    code = 500
                appended_test_scripts = False
                for mimetype, media_type in (response.content or {}).items():
                    if appended_test_scripts:
                        continue
                    candidate_route = (
                        (expect[route_str].code == code and expect[route_str].enabled)
                        or str(code).startswith('2')
                    )
                    if candidate_route:
                        enabled_tests = expect[route_str].enabled_tests
                        if mimetype == 'application/json':
                            schema_ = self._resolve_object(media_type.schema_ or {})
                            mt_props = self._resolve_object(
                                schema_.get('properties') or {},
                            )
                            if PostmanTest.schema_validation in enabled_tests:
                                test_scripts[route_str].append(
                                    js_test_validate_schema(route_str, mt_props, self.schema.to_dict())
                                )
                        if PostmanTest.code in enabled_tests:
                            test_scripts[route_str].append(
                                js_test_code(route_str, code),
                            )
                        if PostmanTest.content_type in enabled_tests:
                            test_scripts[route_str].append(
                                js_test_content_type(route_str, mimetype),
                            )
                        if PostmanTest.response_time in enabled_tests:
                            test_scripts[route_str].append(
                                js_test_response_time(
                                    route_str,
                                    expect[route_str].response_time,
                                )
                            )
                        appended_test_scripts = True
        return PostmanConfig(
            expect, test_data, test_scripts,
            prerequest_scripts, collection_global_variables,
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
        self.collection_global_variables.extend(
            postman_config.collection_global_variables,
        )
        self.collection_test_scripts.extend(
            postman_config.collection_test_scripts,
        )
        self.collection_prerequest_scripts.extend(
            postman_config.collection_prerequest_scripts,
        )
        test_data.extend(postman_config.test_data)
        return test_data

    @property
    def paths(self):
        for path in self.schema.paths:
            yield (path, self.schema.paths[path])

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

    def verbose_msg(self, *msg, delim=','):
        if self.verbose:
            logger.debug(delim.join(msg))

    @classmethod
    def order_routes_by_resource(
        cls, routes: Iterable[Route],
        verb_ordering: Tuple = ('post', 'put', 'get', 'patch', 'delete',)
    ) -> List[Route]:
        """Identify REST resources and order CRUD operations safely."""
        by_resource = defaultdict(lambda: {})
        output = []
        for route in routes:
            verb, path, operation = route
            by_resource[cls.guess_resource(path)][verb] = route
        for resource, routes_by_verb in by_resource.items():
            for verb in verb_ordering:
                if routes_by_verb.get(verb):
                    output.append(routes_by_verb[verb])
        return output

    def fake_data_from_route_schema(
        self, verb: str, path: str, operation: Operation,
    ) -> ParameterRequestData:
        if not self.expect[f'{verb.upper()} {path}'].fake_data:
            logger.debug(f"Skipping fake_data generation for {verb} {path}")
            return ParameterRequestData()
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
                schema_ = self._resolve_object(media_type.schema_ or {})
                mt_props = self._resolve_object(
                    schema_.get('properties') or {},
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
                f"generating test data for it assuming it's a string."
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
            param_in = param.in_.value
            if param_in == 'body':
                examples['body'] = []
                target = examples['body']
            else:
                target = examples[param_in][param.name]
            if param.example:
                target.extend([param.example])
            if param.examples:
                target.extend(param.examples)
        return examples

    def _resolve_object(self, *args, **kwargs):
        return BaseModel.resolve_object(self.schema, *args, **kwargs)

    def convert_parameters(self, verb, path, operation: Operation):
        return ParameterBuilder(
            self, verb, path, operation, self.test_data,
        ).build()

    def _generate_postman_collections(self):
        build_url = lambda path, vars=None, query=[]: Url(
            host=["{{baseUrl}}"],
            path=self.path_parts(path),
            query=query,
            variable=vars or [],
        )
        items = []
        global_variables = self.collection_global_variables or []
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

            if global_variables:
                self.verbose_msg(f'{verb} {path} global variables {global_variables}')
            if query:
                self.verbose_msg(f'{verb} {path} query param variables {query}')
            if request_url_variables:
                self.verbose_msg(f'{verb} {path} url variables {request_url_variables}')
            if request_header:
                self.verbose_msg(f'{verb} {path} headers {request_header}')
            if request_body:
                self.verbose_msg(f'{verb} {path} request_body {request_body}')
            items.append(
                Item(
                    id=uuidgen(),
                    name=operation.summary or route_str,
                    request=Request(
                        auth=Auth(type='noauth'),
                        url=build_url(
                            path, vars=request_url_variables, query=query,
                        ),
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


class ParameterBuilder:
    def __init__(self, mormo, verb, path, operation, test_data):
        self.mormo, self.verb, self.path, self.operation, self.test_data = (
            mormo, verb, path, operation, test_data,
        )
        self.params = mormo._resolve_object(operation.parameters or [])
        self.config_test_data = list_of_test_data_to_params(
            f"{verb} {path}",
            self.test_data,
        ).dict()
        self.fake_data = mormo.fake_data_from_route_schema(
            verb, path, operation,
        ).dict()
        self.examples = flatten_iterables_in_dict(
            mormo.operation_param_examples(operation),
        )
        self.path_vars = [p[1:] for p in mormo.path_parts(path) if p.startswith(':')]

    def get_mapped_value(self, v):
        return ChainMap(
            self.config_test_data.get(v, {}),
            self.examples.get(v, {}),
            self.fake_data.get(v, {}),
        )

    @classmethod
    def build_test_data_from_param(self, param, mapped_value):
        return Parameter(
            key=param.name,
            value=str(mapped_value[param.name]),
        )

    def get_path_param_variables(self, url, param):
        global_ = []
        segment_vars = set(RE_PATH_VARIABLE.findall(self.path))\
            .difference(self.path_vars)
        found_var_location = False
        mapped_value = self.get_mapped_value('path')
        for v in segment_vars:
            if v == param.name:
                if v in mapped_value:
                    global_.append(
                        Variable(
                            id=v, type='string',
                            value=str(mapped_value[v])
                        )
                    )
                    found_var_location = True
                else:
                    logger.error(f"Path segment {v} not mapped to a value.")  # noqa; E501
        if found_var_location:
            return global_, url
        if param.name not in self.path_vars:
            not_processed_path_vars = set(self.path_vars).difference(
                {v.key for v in url},
            )
            if len(not_processed_path_vars) > 1:
                err = f"Path variable ({param.name}) not in path and multiple path variables ({not_processed_path_vars}) to choose from."  # noqa; E501
                if self.mormo.strict:
                    raise ValueError(err)
                logger.warning(err)
            elif len(not_processed_path_vars) == 1:
                first_var = not_processed_path_vars.pop()
                if first_var in mapped_value:
                    url.append(
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
                            f"Path variable doesn't exist in path ({param.name}), guessed to be path var ({self.path_vars[0]}) but not mapped to value"  # noqa; E501
                            " param is mapped to a value so using that value with the guessed name."  # noqa; E501
                        )
                        url.append(
                            Parameter(
                                key=self.path_vars[0],
                                value=str(mapped_value[param.name]),
                            )
                        )
                    else:
                        logger.error(f"Path variable doesn't exist in path ({param.name}).")  # noqa; E501
            else:
                logger.error(f"Path variable doesn't exist in path ({param.name}).")  # noqa; E501
        else:
            url.append(self.build_test_data_from_param(param, mapped_value))
        return global_, url

    def get_missing_path_variables(self, global_, url):
        global_ = global_.copy()
        url = url.copy()
        missing_variable = set(self.path_vars).difference(
            {
                *[p.key for p in url if p],
                *[p.id for p in global_ if p],
            },
        )

        for path_var in missing_variable:
            mapped_value = self.get_mapped_value('path')
            if mapped_value.get(path_var):
                url.append(
                    Parameter(
                        key=path_var,
                        value=str(mapped_value[path_var]),
                    )
                )
            else:
                logger.warning(f"Path variable {path_var} missing variable and no mapped value!")  # noqa: E501
        return global_, url

    def get_request_body(self):
        header = []
        body_args = {}
        for param in self.params:
            param = self.mormo._resolve_object(param, new_cls=oapi.Parameter)
            if param.in_.value != "body":
                continue
            mapped_value = self.get_mapped_value('body')
            if not mapped_value:
                logger.warning(
                    f"Missing content for body parameter: {param.name}",
                )
                continue
            body_args['mode'] = 'raw'
            body_args['raw'] = json.dumps(dict(mapped_value))
            header.append(
                Parameter(
                    key='Content-Type',
                    value='application/json',
                ),
            )

        request_body = self.mormo._resolve_object(
            self.operation.requestBody,
            new_cls=oapi.RequestBody,
        )

        if (
            request_body and not body_args.get('mode') == 'raw'
            and self.config_test_data.get('requestBody')
        ):
            body_args['mode'] = 'raw'
            body_args['raw'] = json.dumps(
                self.config_test_data.get('requestBody'),
            )
        if body_args:
            return header, RequestBody(
                **body_args,
            )
        return header, None

    def build(self) -> PostmanVariables:
        global_, query, url, header, body = ([], [], [], [], [])
        for param in self.params:
            param = self.mormo._resolve_object(param, new_cls=oapi.Parameter)
            if not param.required:
                continue
            param_in = param.in_.value
            mapped_value = self.get_mapped_value(param_in)
            if param_in == 'body':
                continue
            test_data = Parameter(
                key=param.name,
                value=str(mapped_value[param.name]),
            )
            if param_in == 'path':
                n_global, n_url = self.get_path_param_variables(url, param)
                if global_ != n_global:
                    global_.extend(n_global)
                if url != n_url:
                    url.extend(n_url)
            elif param_in == 'query':
                query.append(test_data)
            elif param_in == 'header':
                header.append(test_data)
            elif param_in == 'cookie':
                raise ValueError(f"unhandled param location: {param_in}")
            else:
                raise ValueError(f"unknown param location: {param_in}")

        n_header, body = self.get_request_body()
        if header != n_header:
            header.extend(n_header)

        n_global, n_url = self.get_missing_path_variables(global_, url)
        if global_ != n_global:
            global_.extend(n_global)
        if url != n_url:
            url.extend(n_url)
        return PostmanVariables(global_, query, url, header, body)
