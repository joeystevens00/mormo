import json

from pydantic import BaseModel as PyDanticBaseModel

from .util import DB, strip_nulls
from . import redis_handle


class BaseModel(PyDanticBaseModel):
    def to_file(self, path):
        with open(path, 'w') as f:
            json.dump(json.loads(self.json()), f)

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

    class Config:
        extra = 'allow'
