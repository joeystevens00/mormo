from collections import Counter
import json

from pydantic import BaseModel as PyDanticBaseModel

from .util import DB, strip_nulls
from . import redis_handle


class ReferenceDepth:
    __shared_state = {}

    def __init__(self):
        self.__dict__ = self.__shared_state


class BaseModel(PyDanticBaseModel):
    __strict = True
    __ref_depth = Counter()
    __max_ref_depth = 5

    def to_file(self, path):
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f)

    def save(self):
        dbo = DB(redis_handle(), model=self)
        dbo.save()
        return dbo

    def to_dict(self, no_empty=True):
        """Fixes serialization of dict()"""
        d = json.loads(self.json(by_alias=True))
        if no_empty:
            d = strip_nulls(d)
        return d

    def resolve_ref(self, schema):
        from .convert import OpenAPIToPostman
        if issubclass(schema.__class__, BaseModel):
            schema = schema.to_dict()
        return OpenAPIToPostman.find_ref(self.ref, schema)

    def get_safe(self, v):
        try:
            return self.__getattribute__(v)
        except AttributeError:
            pass
            # if default:
            #     return default
    @classmethod
    def resolve_object(cls, s, o, new_cls=None, deep=False):
        from . import logger
        from .schema.openapi_v3 import Reference, SchemaObject
        if isinstance(o, Reference):
            logger.debug(f"Resolving reference {o.ref} Try #{s.__ref_depth[o.ref]}")  # noqa; E501
            if s.__ref_depth[o.ref] > s.__max_ref_depth:
                if s.__strict:
                    raise ValueError(f"Max reference recursion reached for {o.ref}")  # noqa; E501
                return
            s.__ref_depth[o.ref] += 1
            o = o.resolve_ref(s)
        elif '$ref' in dir(o):
            if isinstance(o, SchemaObject):
                logger.warning("SchemaObject should be a Reference object, catching serialization issue...")
                o = s.resolve_object(
                    s,
                    Reference(
                        **{'$ref': o.__getattribute__('$ref')},
                    ),
                    new_cls=new_cls,
                    deep=deep,
                )
            else:
                logger.error(
                    "Possible serialization issue with object,"
                    f" object of type ({type(o)}) shouldn't be a reference: ({o})"
                )
        elif isinstance(o, dict) and o.get('$ref'):
            o = s.resolve_object(
                s,
                Reference(**o),
                new_cls=new_cls,
                deep=deep,
            )
        if 'to_dict' in dir(o):
            o = o.to_dict()
        if deep and isinstance(o, dict):
            for k, v in o.items():
                if (isinstance(v, dict) and v.get('$ref')) or isinstance(v, Reference):
                    if isinstance(v, Reference):
                        v = v.to_dict()
                    o[k] = s.resolve_object(s, Reference(**v), deep=True)
                else:
                    o[k] = s.resolve_object(s, v, deep=True)
        if isinstance(o, dict) and new_cls:
            o = new_cls(**o)
        return o

    class Config:
        extra = 'allow'
