import enum
from typing import Any, List, Optional, Union, Sequence

from ..model import BaseModel

VERSION = "2.1.0"

EventListen = enum.Enum(
    'listen',
    [('test', "test"), ('prerequest', "prerequest")],
)


class Url(BaseModel):
    path: Sequence[str]
    host: Sequence[str]
    query: list
    variable: list


class OriginalRequest(BaseModel):
    method: str
    url: Url
    body: dict


class Header(BaseModel):
    key: str
    value: str


class Parameter(BaseModel):
    key: str
    value: Any
    disabled: bool = False
    description: Optional[str]


class Response(BaseModel):
    id: str
    name: str
    originalRequest: OriginalRequest
    status: str
    code: str
    header: Sequence[Header]
    body: str
    cookie: list
    _postman_previewlanguage: Optional[str]


class Auth(BaseModel):
    type: str


class RequestBody(BaseModel):
    mode: Optional[str]
    raw: Optional[str]
    urlencoded: Optional[list]
    formdata: Optional[list]
    file: Optional[dict]
    graphql: Optional[dict]
    diabled: Optional[bool] = False


class Request(BaseModel):
    name: str
    description: dict
    method: str
    url: Url
    auth: Auth
    header: list
    body: Optional[RequestBody]


class Script(BaseModel):
    id: Optional[str]
    type: Optional[str]
    exec: Union[str, list]
    src: Optional[Union[str, Url]]
    name: Optional[str]

    def __add__(self, x):
        if isinstance(self.exec, str):
            self.exec = [self.exec]
        if isinstance(x.exec, str):
            x.exec = [x.exec]
        self.exec.extend(x.exec)
        return self


class Event(BaseModel):
    id: Optional[str]
    listen: str
    disabled: Optional[bool]
    script: Script


class Item(BaseModel):
    id: str
    name: str
    request: Request
    response: Sequence[Response]
    event: List[Event]


class Folder(BaseModel):
    id: str
    name: str
    item: Union[Sequence[Item], Item]
    event: list


class Variable(BaseModel):
    id: str
    type: str
    value: Optional[str]


class Description(BaseModel):
    content: str
    type: str


class Info(BaseModel):
    name: str
    postman_id: str
    schema_: str
    description: Description

    class Config:
        fields = {'postman_id': '_postman_id', 'schema_': 'schema'}


class Collection(BaseModel):
    item: Sequence[Union[Item, Folder]]
    event: Optional[list]
    variable: Optional[Sequence[Variable]]
    info: Info


class SaveDBResult(BaseModel):
    id: str
    object: Collection
