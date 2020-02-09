import enum

from typing import Any, Dict, List, Optional, Union, Set

from ..model import BaseModel

VERSION = "3.0.2"

HeaderType = lambda: Optional[Dict[str, Union[Header, Reference]]]
ExampleType = lambda: Optional[Dict[str, Union[Any, Reference]]]
ContentType = lambda: Optional[Dict[str, MediaType]]  # str is mimetype
ResponsesType = lambda: Dict[str, Union[Response, Reference]]
Style = Optional[str]
CallBackType = Dict[str, Dict[str, Dict]]


class ParameterRequestData(BaseModel):
    body: dict = dict()
    requestBody: dict = dict()
    path: dict = dict()
    query: dict = dict()
    header: dict = dict()
    cookie: dict = dict()


class ParameterIn(enum.Enum):
    body = 'body'
    request_body = 'requestBody'
    path = 'path'
    query = 'query'
    header = 'header'
    cookie = 'cookie'


class Reference(BaseModel):
    ref: str

    class Config:
        fields = {'ref': '$ref'}


class ExternalDocs(BaseModel):
    description: Optional[str]
    url: str


class ParameterSchema(BaseModel):
    type: Optional[str]
    format: Optional[str]
    title: Optional[str]
    maximum: Optional[int]
    minimum: Optional[int]
    nullable: Optional[bool]


class ServerVariable(BaseModel):
    default: str
    enum: Optional[List[str]]
    description: Optional[str]


class Server(BaseModel):
    url: str
    description: Optional[str]
    variables: Optional[Dict[str, ServerVariable]]


class Contact(BaseModel):
    name: Optional[str]
    url: Optional[str]
    email: Optional[str]


class License(BaseModel):
    name: str
    url: Optional[str]


class Info(BaseModel):
    description: Optional[str]
    termsOfService: Optional[str]
    title: Optional[str]
    version: Optional[str]
    contact: Optional[Contact]
    license: Optional[License]


class Properties(BaseModel):
    description: Optional[str]
    type: Optional[str]
    format: Optional[str]
    default: Optional[Any]
    example: Optional[str]
    title: Optional[str]
    multipleOf: Optional[int]
    maximum: Optional[int]
    exclusiveMaximum: Optional[bool]
    minimum: Optional[int]
    exclusiveMinimum: Optional[bool]
    maxLength: Optional[int]
    minLength: Optional[int]
    pattern: Optional[str]
    additionalItems: Optional[Union[bool, dict, Reference]]
    items: Optional[Union[dict, Reference]]
    maxItems: Optional[int]
    minItems: Optional[int]
    uniqueItems: Optional[bool]
    maxProperties: Optional[int]
    minProperties: Optional[int]
    required: Optional[Set[str]]
    properties: Optional[Union[dict, Reference]]
    additionalProperties: Optional[Union[bool, dict, Reference]]
    enum: Optional[Set[Any]]
    allOf: Optional[List[Union[dict, Reference]]]
    oneOf: Optional[List[Union[dict, Reference]]]
    anyOf: Optional[List[Union[dict, Reference]]]
    not_: Optional[Union[dict, Reference]]
    nullable: Optional[bool]
    discriminator: Optional[dict]
    readOnly: Optional[bool]
    writeOnly: Optional[bool]
    xml: Optional[dict]
    externalDocs: Optional[ExternalDocs]
    example: Optional[Any]
    deprecated: Optional[bool]

    class Config:
        fields = {'not_': 'not'}


class Encoding(BaseModel):
    contentType: Optional[str]
    headers: Optional[Dict[str, Union[Reference, dict]]]
    style: Style
    explode: Optional[bool]
    allowReserved: Optional[bool]


class SchemaObject(BaseModel):
    description: Optional[str]
    required: Optional[List[str]]
    example: Optional[Any]
    examples: ExampleType()
    encoding: Optional[Dict[str, Encoding]]
    type: Optional[str]
    format: Optional[str]
    properties: Optional[Dict[str, Properties]]
    allOf: Optional[List[Union[dict, Reference]]]

    class Config:
        fields = {'type_': 'type'}


class MediaType(BaseModel):
    schema_: Union[SchemaObject, Reference, None]

    class Config:
        fields = {'schema_': 'schema'}


class Header(BaseModel):
    description: Optional[str]
    required: Optional[bool]
    schema_: ParameterSchema
    deprecated: Optional[bool]
    allowEmptyValue: Optional[bool]
    style: Style
    explode: Optional[bool]
    allowReserved: Optional[bool]
    example: Optional[Any]
    examples: ExampleType()
    content: ContentType()

    class Config:
        fields = {'schema_': 'schema'}


class Response(BaseModel):
    description: str
    content: ContentType()
    headers: HeaderType()


class Parameter(BaseModel):
    name: str
    in_: ParameterIn
    description: Optional[str]
    required: Optional[bool]
    schema_: ParameterSchema
    deprecated: Optional[bool]
    allowEmptyValue: Optional[bool]
    style: Style
    explode: Optional[bool]
    allowReserved: Optional[bool]
    example: Optional[Any]
    examples: ExampleType()
    content: ContentType()

    class Config:
        fields = {'schema_': 'schema', 'in_': 'in'}


class RequestBody(BaseModel):
    description: Optional[str]
    content: Dict[str, MediaType]
    required: Optional[bool]


class Operation(BaseModel):
    operationId: Optional[str]
    summary: Optional[str]
    responses: ResponsesType()
    parameters: Optional[List[Union[Parameter, Reference]]]
    tags: Optional[List[str]]
    externalDocs: Optional[ExternalDocs]
    requestBody: Optional[Union[RequestBody, Reference]]
    callbacks: Optional[Dict[str, Union[CallBackType, Reference]]]
    deprecated: Optional[bool]
    security: Optional[List[Dict[str, List]]]
    servers: Optional[List[Server]]


# class Components(BaseModel):
#     schemas: Optional[Dict[str, Union[SchemaObject, Reference]]]
#     responses: Optional[Dict[str, ResponsesType()]]
#     parameters: Optional[Dict[str, Union[Parameter, Reference]]]


class Path(BaseModel):
    # summary: Optional[str]
    # description: Optional[str]
    get: Optional[Operation]
    put: Optional[Operation]
    post: Optional[Operation]
    delete: Optional[Operation]
    options: Optional[Operation]
    head: Optional[Operation]
    patch: Optional[Operation]
    trace: Optional[Operation]
    # servers: Optional[List[Server]]
    # parameters: Optional[List[Union[Parameter, Reference]]]


class OpenAPISchemaV3(BaseModel):
    openapi: str
    paths: Dict[str, Path]
    info: Optional[Info]
    servers: Optional[List[Server]]
    components: Optional[dict]
    security: Optional[List[Dict[str, List]]]
    externalDocs: Optional[ExternalDocs]


class SaveDBResult(BaseModel):
    id: str
    object: OpenAPISchemaV3
