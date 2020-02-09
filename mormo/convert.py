import os
from collections import defaultdict, ChainMap, Counter, namedtuple
from typing import Dict, Generator, Iterable, List, Optional, Union
import json
import logging
import re
import yaml
from types import GeneratorType
import random
import functools

import hypothesis
from hypothesis import given
from hypothesis_jsonschema._from_schema import from_schema

from .schema import Expect, OpenAPISchemaToPostmanRequest, TestData, TestDataFileItem, list_of_test_data_to_params
from .schema.openapi_v3 import (
    Operation, OpenAPISchemaV3, Parameter as OpenAPIParameter, ParameterIn, ParameterRequestData, Reference, Response as OpenAPIResponse, RequestBody as OpenAPIRequestBody,
)
from .schema.postman_collection_v2 import (
    Auth, Event, Collection, Item,
    Request, RequestBody, Response, OriginalRequest, Header,
    Info, Description, Parameter, Script, Url, Variable,
)
from .util import fingerprint, flatten_iterables_in_dict, get_http_reason, load_file, uuidgen, TemplateMap, trim, HTTP_VERBS
from . import logger, Settings

RE_PATH_VARIABLE = re.compile('\{(.*?)\}')
RE_PATH_GLOBAL_VARIABLE = re.compile('\{\{(.*?)\}\}')
RE_PATH_VARIABLE_SEGMENT = re.compile('(\(\{(.*?)\}\))')
RE_WORDCHARS = re.compile('^\w+$')

Route = namedtuple('Route', ['verb', 'path','operation'])
ReferenceSearch = namedtuple('ReferenceSearch', ['ref', 'schema'])



FILTERS = {
    str: lambda x: len(x) >= Settings().test_data_str_min_length,
    int: lambda x: x >= Settings().test_data_int_min,
    'words': lambda x: RE_WORDCHARS.match(x),
}

# TODO:
# Generate Postman tests for HTTP status, mimetype, and schema checking

# def filter_min_length(x):
#     min_len = Settings().test_data_str_min_length
#     if isinstance(x, str):
#         logger.warning(f"STR {len(x)}")
#         return len(x) >= min_len
#     elif isinstance(x, int):
#         logger.warning(f"INT {x}")
#         return x >= min_len
#     else:
#         logger.warning(f"Don't know how to check length of type({type(x)})")
#         return True

def get_path_variable_segments(path: str) -> dict:
    return {m[1]: m[0] for m in RE_PATH_VARIABLE_SEGMENT.findall(path)}


def generate_from_schema(schema, no_empty=True, retry=5):
    test_data = []
    settings = Settings()
    if schema.get('type') == 'string' and not schema.get('minLength') and not schema.get('format'):
        schema['minLength'] = settings.test_data_str_min_length
        #schema['pattern'] = '^\w+$'
        generate_func = from_schema(schema)
        generate_func = generate_func.filter(FILTERS[str])#.filter(FILTERS['words'])
    elif schema.get('type') == 'integer' and not schema.get('minimum'):
        schema['minimum'] = settings.test_data_int_min
        generate_func = from_schema(schema)
        generate_func = generate_func.filter(FILTERS[int])
    else:
        generate_func = from_schema(schema)
    @given(generate_func)
    def f(x):
        if x or not no_empty:
            test_data.append(x)
    passed = False
    while retry > 0 or not passed:
        try:
            f()
            passed = True
            retry = 0
        except hypothesis.errors.Unsatisfiable:
            retry -= 1
    if not passed:
        raise hypothesis.errors.Unsatisfiable("Max retries hit")
    yield test_data


def pick_one(gen: GeneratorType, strategy="random"):
    """Given a generator which yields an iterable, get an element."""
    # it seems that the data from generate_from_schema is better if you pick randomly
    # often enough the first element is rather boring like 0 or '0'
    if "rand" in strategy.lower():
        return random.choice(next(gen))
    else:
        return next(gen)[0]


def parse_url(urlstr: str) -> list:
    url = []
    for part in urlstr.split('/')[1:]:
        is_path_variable = re.match('^{(\w+)}$', part)
        is_path_segment = RE_PATH_VARIABLE.findall(part)
        if is_path_variable:
            part = f':{is_path_variable.group(1)}'
        elif is_path_segment:
            for group in is_path_segment:
                part = part.replace(f"{{{group}}}", f"{{{{{group}}}}}")
        url.append(part)
    return url


def strip_var_chars(s):
    return lstrip('{').lstrip(':').rstrip('}')


def load_remote_refs(schema_path):
    if isinstance(schema_path, str) and schema_path.startswith('http'):
        ref_path = None
        if '#' in schema_path:
            ref_path = schema_path.split('#')[-1]
        try:
            logger.debug(f"Fetching remote reference: {schema_path}")
            schema_path = requests.get(schema_path).json()
            if ref_path:
                schema_path = find_ref(ref_path, schema_path)
        except Exception as e:
            logger.error(f"Exception: {type(e)}: {e}")
            raise e
    return schema_path


def load_local_refs(schema_path):
    if isinstance(schema_path, str) and os.path.exists(schema_path):
        schema_path = load_file(schema_path)
    return schema_path


# def freezeargs(func):
#     """Transform mutable dictionnary
#     Into immutable
#     Useful to be compatible with cache
#     """
#
#     @functools.wraps(func)
#     def wrapped(*args, **kwargs):
#         args = tuple([frozendict(arg) if isinstance(arg, dict) else arg for arg in args])
#         kwargs = {k: frozendict(v) if isinstance(v, dict) else v for k, v in kwargs.items()}
#         return func(*args, **kwargs)
#     return wrapped
def hashable_lru(func):
    cache = functools.lru_cache(maxsize=1024)

    def deserialise(value):
        try:
            return json.loads(value)
        except Exception:
            return value

    def func_with_serialized_params(*args, **kwargs):
        _args = tuple([deserialise(arg) for arg in args])
        _kwargs = {k: deserialise(v) for k, v in kwargs.items()}
        return func(*_args, **_kwargs)

    cached_function = cache(func_with_serialized_params)

    @functools.wraps(func)
    def lru_decorator(*args, **kwargs):
        _args = tuple([json.dumps(arg, sort_keys=True) if type(arg) in (list, dict) else arg for arg in args])
        _kwargs = {k: json.dumps(v, sort_keys=True) if type(v) in (list, dict) else v for k, v in kwargs.items()}
        return cached_function(*_args, **_kwargs)
    lru_decorator.cache_info = cached_function.cache_info
    lru_decorator.cache_clear = cached_function.cache_clear
    return lru_decorator

@hashable_lru
def find_ref(ref: str, schema_path):
    ref_path = ref.split('/')[1:]
    while len(ref_path):
        seek = ref_path.pop(0).replace('~1', '/').replace('~0', '~')
        if seek:
            if isinstance(schema_path, list) and seek.isdigit():
                schema_path = schema_path[int(seek)]
            else:
                schema_path = schema_path[seek]
    schema_path = load_remote_refs(schema_path)
    schema_path = load_local_refs(schema_path)

    return schema_path

def resolve_refs(schema: dict):
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
                                    v[p][i] = find_ref(schema_ref, schema)
                                else:
                                    logger.debug(f"No $ref found in List[dict]: {e}")
                    if not isinstance(v[p], dict):
                        continue
                    if not schema_ref:
                        schema_ref = v.get(p, {}).get('$ref')
                        if schema_ref:
                            found_parent = p
                if schema_ref and schema_ref.startswith('#/') and found_parent:
                    v[found_parent] = find_ref(schema_ref, schema)
                traverse(v)
        return d
    return traverse(schema)


def new_event(listen, script):
    if isinstance(script, list):
        if not len(script):
            return
        _script = script[0]
        for i in script[1:]:
            _script += i
        script = _script
    return Event(id=uuidgen(), listen=listen, script=script, disabled=False)


def javascript(name, exec):
    return Script(
        id=uuidgen(),
        name=name,
        exec=exec,
        type='text/javascript',
    )


class OpenAPIToPostman:
    def __init__(
        self, request: Optional[OpenAPISchemaToPostmanRequest] = None, **kwargs,
        # path: str = None, schema: Union[OpenAPISchemaV3, dict] = None, resolve_references: bool = False,
        # test_data: Optional[List[TestData]] = None,
        # test_data_file: Optional[str] = None,
        # test_data_file_content: Optional[Dict[str, TestDataFileItem]] = None,
        # host: Optional[str] = None,
        # test_scripts: Optional[Dict[str, Script]] = None, prerequest_scripts: Optional[Dict[str, Script]] = None,
        # collection_test_scripts: Optional[List[Script]] = None, collection_prerequest_scripts: Optional[List[Script]] = None,
        # postman_global_variables: Optional[List[Variable]] = None,
        # expect: Optional[Dict[str, Expect]] = None,
    ):
        if not request:
            request = OpenAPISchemaToPostmanRequest(**kwargs)
        self.schema = None
        self.host = request.host
        self.max_ref_depth = 5
        self.ref_depth = Counter()
        self.strict = True
        self.test_scripts = defaultdict(lambda: [], request.test_scripts or [])
        self.prerequest_scripts = defaultdict(lambda: [], request.prerequest_scripts or [])
        self.collection_test_scripts = request.collection_test_scripts or []
        self.collection_prerequest_scripts = request.collection_prerequest_scripts or []
        self.postman_global_variables = request.postman_global_variables or []
        self.expect = request.expect or {}
        self.test_data = self.load_test_data(request.extra_test_data or [], request.test_data_file, request.test_data)
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
            raise ValueError("Either path to schema or schema is a required field")
        if isinstance(self.schema, OpenAPISchemaV3):
            self.schema = self.schema.to_dict(no_empty=False)
        if not isinstance(self.schema, dict):
            raise ValueError("Could not load schema")
        if request.resolve_references:
            self.schema = resolve_refs(self.schema)
        # Validate schema
        self.schema = OpenAPISchemaV3(**self.schema)

    def load_test_data(self, test_data, test_data_file=None, test_data_file_content=None):
        if test_data_file or test_data_file_content:
            if test_data_file:
                test_data_file_content = load_file(test_data_file)
            for route, td_item in test_data_file_content.items():
                i = TestDataFileItem(**td_item)
                if isinstance(i.variables, str):
                    variables = load_file(i.variables)
                else:
                    variables = i.variables
                if route.lower() == 'collection':
                    self.postman_global_variables.extend([
                        Variable(id=k, type='string', value=v) for k, v in (variables or {}).items()
                    ])
                    if i.test:
                        self.collection_test_scripts.extend([
                            javascript(exec=t, name=f"{route} cmd({fingerprint(t)}) inserted from test_data file") for t in i.test
                        ])
                    if i.prerequest:
                        self.collection_prerequest_scripts.extend([
                            javascript(exec=t, name=f"{route} cmd({fingerprint(t)}) inserted from test_data file") for t in i.prerequest
                        ])
                    continue
                test_data.extend([
                    TestData(route=route, in_='requestBody', key=k, value=v)
                    for k, v in (variables or {}).items()
                ])
                for variable, response_path in (i.make_global or {}).items():
                    response_path = ''.join(['["' + trim(p) +'"]' for p in response_path.split('.')[1:]])
                    debug_global = lambda x: javascript(
                        name=f'[{x}] Debug {variable}',
                        exec=f'console.log("[{x}] GLOBAL({variable}):", pm.globals.get("{variable}"));',
                    )
                    self.collection_prerequest_scripts.append(debug_global('collection_prerequest'))
                    self.prerequest_scripts[route].append(debug_global('prerequest'))
                    self.test_scripts[route].append(javascript(
                        name=f'Set response of {route}: JSON_RESPONSE{response_path} to {variable}',
                        #exec=f'pm.environment.set("{variable}", pm.response.json(){response_path});',
                        exec="""
                            pm.test('set {variable}', function() {{
                                pm.globals.set("{variable}", pm.response.json(){response_path});
                            }});
                        """.format(variable=variable, response_path=response_path),
                    ))
                #self.postman_global_variables.append(Variable(id=variable, type='string', value='default'))
                for k, v in (variables or {}).items():
                    test_data.extend([
                        TestData(route=route, in_=in_,key=k, value=v)
                        for in_ in list(ParameterIn)
                    ])
                if i.expect:
                    self.expect[route] = i.expect
                if i.test:
                    self.test_scripts[route].extend([
                        javascript(exec=t, name=f"{route} cmd({fingerprint(t)}) inserted from test_data file") for t in i.test
                    ])
                if i.prerequest:
                    self.prerequest_scripts[route].extend([
                        javascript(exec=t, name=f"{route} cmd({fingerprint(t)}) inserted from test_data file") for t in i.prerequest
                    ])
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
        parts = parse_url(path)
        last_part = None
        for i, part in enumerate(parts):
            is_variable = RE_PATH_GLOBAL_VARIABLE.match(part) or part.startswith(':')
            segments = get_path_variable_segments(part)
            for var, segment in segments.items():
                part = part.replace(segment, '')
            # If this segment is a variable, return the last one
            if is_variable and len(parts)-i == 1:
                return last_part
            last_part = part
        return last_part

    @classmethod
    def order_routes_by_resource(cls, routes: Iterable[Route], verb_ordering: Optional[List] = None) -> List[Route]:
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

    def fake_data_from_route_schema(self, path: str, operation: Operation) -> ParameterRequestData:
        d = defaultdict(lambda: {})
        all_path_vars = RE_PATH_VARIABLE.findall(path)
        parameters = self.resolve_object(operation.parameters)

        if parameters:
            for parameter in operation.parameters:
                parameter = self.resolve_object(parameter, new_cls=OpenAPIParameter)
                in_ = parameter.in_.value
                param_schema = parameter.schema_
                if in_ == 'body':
                    properties = param_schema.properties or {}
                    if isinstance(properties, Reference):
                        properties = properties.resolve_ref(self.schema)
                    for param, param_schema in properties.items():
                        d['body'][param] = pick_one(generate_from_schema(param_schema))
                else:
                    d[in_][parameter.name] = pick_one(generate_from_schema(param_schema.to_dict()))
        request_body = self.resolve_object(operation.requestBody, new_cls=OpenAPIRequestBody)
        if request_body:
            for mimetype, media_type in request_body.content.items():
                # def parse_all_of(all_of):
                #     all_of_props = {}
                #     if all_of:
                #         for o in all_of:
                #             if o.get('allOf'):
                #                 return parse_all_of(o['allOf'])
                #             if o.get('properties'):
                #                 all_of_props[o['title']] = o['properties']
                #             else:
                #                 raise ValueError(f"Missing properties in allOf schema: {o}")
                #     return all_of_props
                #
                # all_of_props = parse_all_of(media_type.schema_.allOf)
                #(media_type.schema_[k] for k in media_type.schema_.keys())
                mt_props = self.resolve_object(media_type.schema_.properties or {})
                for name, prop in mt_props.items():
                    prop = self.resolve_object(prop)
                    if not isinstance(prop, dict):
                        prop = prop.to_dict()
                    if prop.get('ref') or prop.get('$ref'):
                        logger.error(f"Unresolved reference in media type! {media_type}")
                    d['requestBody'][name] = pick_one(generate_from_schema(prop))
        for path_var in set(all_path_vars).difference(set(d.get('path', []))):
            logger.warning(
                f"Path variable {path_var} isn't defined as a parameter "
                f" generating test data for it assuming it's a string."
            )
            d['path'][path_var] = pick_one(generate_from_schema({'type': 'string'}))
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
        for param in self.resolve_object(operation.parameters or []):
            param = self.resolve_object(param, new_cls=OpenAPIParameter)
            if param.example:
                examples[param.in_.value][param.name].extend([param.example])
            if param.examples:
                examples[param.in_.value][param.name].extend(param.examples)
        return examples

    def resolve_object(self, o, new_cls=None):
        if isinstance(o, Reference):
            logger.debug(f"Resolving reference {o.ref} Try #{self.ref_depth[o.ref]}")
            if self.ref_depth[o.ref] > self.max_ref_depth:
                if self.strict:
                    raise ValueError(f"Max reference recursion reached for {o.ref}")
                else:
                    return
            self.ref_depth[o.ref] += 1
            o = o.resolve_ref(self.schema)
        if isinstance(o, dict):
            if new_cls:
                o = new_cls(**o)
        return o

    def convert_parameters(self, path, operation: Operation):
        params = defaultdict(lambda: {})
        config_test_data = list_of_test_data_to_params(self.test_data or []).dict()
        fake_data = self.fake_data_from_route_schema(path, operation).dict()
        examples = flatten_iterables_in_dict(self.operation_param_examples(operation))
        urlencoded = []
        request_headers = []
        request_url_variables = []
        global_variables = []
        kwargs = {}
        params = self.resolve_object(operation.parameters or [])
        path_vars = [p[1:] for p in parse_url(path) if p.startswith(':')]
        segment_vars = set(RE_PATH_VARIABLE.findall(path)).difference(path_vars)
        for param in params:
            param = self.resolve_object(param, new_cls=OpenAPIParameter)
            param_in = param.in_.value
            # Parameter precedence: Test Data, Examples in OpenAPI Schema, Fake Data generated from OpenAPI Schema
            mapped_value = ChainMap(
                config_test_data.get(param_in, {}),
                examples.get(param_in, {}),
                fake_data.get(param_in, {}),
            )
            if param.required:
                test_data = None
                if param_in != 'body':
                    test_data = Parameter(key=param.name, value=mapped_value[param.name])
                if param_in == 'path':
                    # If path param not defined in path
                    found_var_location = False
                    for v in segment_vars:
                        if v == param.name:
                            if v in mapped_value:
                                global_variables.append(Variable(id=v, type='string', value=str(mapped_value[v])))
                                found_var_location = True
                            else:
                                logger.error(f"Path segment {v} not mapped to a value.")
                        # else:
                        #     global_variables.append(Variable(id=v, type='string', value=mapped_value[v]))
                        # else:
                        #     request_url_variables.append(test_data)
                    if found_var_location:
                        continue
                    if param.name not in path_vars:
                        not_processed_path_vars = set(path_vars).difference({v.key for v in request_url_variables})
                        print('not_processed', not_processed_path_vars, 'path_vars', path_vars, 'request_vars', {v.key for v in request_url_variables})
                        if len(not_processed_path_vars) > 1:
                            err = f"Path variable ({param.name}) not in path and multiple path variables ({not_processed_path_vars}) to choose from."
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
                                        value=mapped_value[first_var]
                                    )
                                )
                            else:
                                if mapped_value[param.name]:
                                    # if self.strict:
                                    #     raise ValueError("")
                                    logger.warning(
                                        f"Path variable doesn't exist in path ({param.name}), guessed to be path var ({path_vars[0]}) but not mapped to value"
                                        " param is mapped to a value so using that value with the guessed name."
                                    )
                                    request_url_variables.append(Parameter(key=path_vars[0], value=mapped_value[param.name]))
                                else:
                                    logger.error(f"Path variable doesn't exist in path ({param.name}).")
                        else:
                            logger.error(f"Path variable doesn't exist in path ({param.name}).")
                    else:
                        request_url_variables.append(test_data)
                elif param_in == 'query':
                    urlencoded.append(test_data)
                elif param_in == 'header':
                    request_headers.append(test_data)
                elif param_in == 'cookie':
                    raise ValueError(f"unhandled param location: {param_in}")
                elif param_in == 'body':
                    kwargs['mode'] = 'raw'
                    kwargs['raw'] = json.dumps(mapped_value['body'])
                    request_headers.append(Parameter(key='Content-Type', value='application/json'))
                else:
                    raise ValueError(f"unknown param location: {param_in}")
        request_body = self.resolve_object(operation.requestBody, new_cls=OpenAPIRequestBody)

        if request_body and not kwargs.get('mode') == 'raw' and config_test_data.get('requestBody'):
            kwargs['mode'] = 'raw'
            kwargs['raw'] = json.dumps(config_test_data.get('requestBody'))

        for path_var in set(path_vars).difference(set([*[p.key for p in request_url_variables], *[p.id for p in global_variables]])):
            mapped_value = ChainMap(
                config_test_data.get('path', {}),
                examples.get('path', {}),
                fake_data.get('path', {}),
            )
            if mapped_value.get(path_var):
                #logger.warning(f"Path variable {path_var} missing parameter. Creating one.")
                request_url_variables.append(
                    Parameter(
                        key=path_var,
                        value=mapped_value[path_var]
                    )
                )
            else:
                logger.warning(f"Path variable {path_var} missing variable and no mapped value!")
        return global_variables, request_url_variables, request_headers, RequestBody(
            urlencoded=urlencoded,
            **kwargs,
        )

    def generate_postman_collections(self):
        build_url = lambda path, vars=None: Url(
            host=["{{baseUrl}}"],
            path=parse_url(path),
            query=[],
            variable=vars or [],
        )
        items = []
        global_variables = self.postman_global_variables or []

        for verb, path, operation in self.order_routes_by_resource(self.routes):
            responses = []
            route_str = f"{verb.upper()} {path}"
            for code, response in operation.responses.items():
                if code == 'default':
                    code = 500
                http_reason = get_http_reason(code)
                response = self.resolve_object(response, new_cls=OpenAPIResponse)
                appended_test_scripts = False
                for mimetype, route_definition in (response.content or {'text/html': {}}).items():
                    # Need to pick a response to EXPECT
                    # Possible default: First 2XX code encountered
                    # Need to provide a way to override
                    if not appended_test_scripts:
                        expect = self.expect.get(route_str)
                        candidate_route = (expect and expect.code == code and expect.enabled) or (not expect and str(code).startswith('2'))
                        if candidate_route:
                            self.test_scripts[route_str].append(
                                javascript(
                                    name=f"{route_str} Test Code is {code}",
                                    exec="""
                                            pm.test("Status code is {code}", function () {{
                                                pm.expect(pm.response).to.have.status({code});
                                            }});
                                        """.format(code=code),
                                ))
                            self.test_scripts[route_str].append(
                                javascript(
                                    name=f"{route_str} Mimetype is {mimetype}",
                                    exec="""
                                            pm.test("Content-Type Header is {mimetype}", function () {{
                                                pm.expect(postman.getResponseHeader("Content-type")).to.be.eql("{mimetype}");
                                            }});
                                        """.format(mimetype=mimetype),
                                ))
                            appended_test_scripts = True
                    responses.append(Response(
                        id=uuidgen(),
                        name=response.description,
                        originalRequest=OriginalRequest(
                            url=build_url(path),
                            method=verb.upper(),
                            body={},
                        ),
                        code=code,
                        status=http_reason,
                        header=[
                            Header(key='Content-Type', value=mimetype),
                        ],
                        cookie=[],
                        body=response.description,
                    ))
            new_globals, request_url_variables, request_header, request_body = self.convert_parameters(path, operation)
            global_variables.extend(new_globals)
            logger.debug('GLOBALS', new_globals)
            logger.debug('REQUEST', request_url_variables)
            items.append(
                Item(
                    id=uuidgen(),
                    name=operation.summary or route_str,
                    request=Request(
                        auth=Auth(type='noauth'),
                        url=build_url(path, request_url_variables),
                        method=verb.upper(),
                        name=operation.summary or route_str,
                        description={},
                        body=request_body,
                        header=request_header,
                    ),
                    response=responses,
                    event=[
                        e for e in [
                            new_event('test', self.test_scripts.get(route_str, [])),
                            new_event('prerequest', self.prerequest_scripts.get(route_str, [])),
                        ] if e
                    ],
                )
            )

        return [
            global_variables, items
        ]

    def to_postman_collection_v2(self):
        global_variables, items = self.generate_postman_collections()
        return Collection(
            event=[
                e for e in [
                    new_event('test', self.collection_test_scripts or []),
                    new_event('prerequest', self.collection_prerequest_scripts or []),
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
                schema='https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
                description=Description(
                    content=self.info.get_safe('description') or self.title_version,
                    type='text/plain',
                ),
            )
        )

    # @classmethod
    # def path_to_postman_collection_v3_item(cls, path: tuple, item_defaults: Union[dict, None] = None):
    #     path, definitions = path
    #     items = []
    #     def get_url(_, __, template_args):
    #         url = []
    #         for part in template_args['path'].split('/')[1:]:
    #             is_path_variable = re.match('^{(\w+)}$', part)
    #             if is_path_variable:
    #                 part = f':{is_path_variable.group(1)}'
    #             url.append(part)
    #         return url
    #
    #     def parse_headers(mimetype, response_definition):
    #         return [
    #             {'key': 'Content-Type', 'value': mimetype }
    #         ]
    #
    #     def parse_responses(map, k, template_args):
    #         responses = []
    #         for code, definition in template_args['responses'].items():
    #             for mimetype, response_definition in definition['content'].items():
    #                 responses.append({
    #                     'id': uuidgen,
    #                     'name': definition['description'],
    #                     'originalRequest': {
    #                         f: template_args['_template']['request'][f] for f in ['url', 'method']
    #                     },
    #                     'code': code,
    #                     'status': get_http_reason(code),
    #                     'header': parse_headers(mimetype, response_definition),
    #                 })
    #                 #print(responses[-1])
    #         return responses
    #
    #     _item_defaults = {
    #         'id': uuidgen,
    #         'name': '{{ summary or verb.upper() + " " + path }}',
    #         'request': {
    #             'url': {
    #                 'host': "{% raw %}{{baseUrl}}{% endraw %}",
    #                 #'query': [],
    #                 #'variable': [],
    #                 'path': get_url,
    #             },
    #             'method': '{{ verb.upper() }}',
    #             'auth': {
    #                 'type': 'noauth',
    #             },
    #             'description': {},
    #
    #         },
    #         'response': lambda *args: parse_responses(*args),
    #     }
    #
    #     for http_verb in definitions.keys():
    #         definition = definitions[http_verb]
    #         template_args = {
    #             'verb': http_verb,
    #             'path': path,
    #             **definition,
    #             '_template': _item_defaults,
    #         }
    #         items.append(TemplateMap(item_defaults or {}, _item_defaults, template_args).res)
    #     return items
