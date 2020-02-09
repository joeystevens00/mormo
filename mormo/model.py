import json

from pydantic import BaseModel as PyDanticBaseModel

from .util import DB, strip_nulls
from . import redis_handle


class BaseModel(PyDanticBaseModel):
    def to_file(self, path):
        with open(path, 'w') as f:
            json.dump(json.loads(self.json()), f)

    def save(self):
        DB(redis_handle(), model=self).save()

    def to_dict(self, no_empty=True):
        """Fixes serialization of dict()"""
        d = json.loads(self.json(by_alias=True))
        if no_empty:
            d = strip_nulls(d)
        return d

    def resolve_ref(self, schema):
        from .convert import find_ref
        if issubclass(schema.__class__, BaseModel):
            schema = schema.to_dict()
        # self._ref_count[self.ref] += 1
        # print(f'resolve_ref {self.ref} #{self._ref_count[self.ref]}')
        # if isinstance(schema, type(self)):
        #     schema = schema.to_dict()
        return find_ref(self.ref, schema)

    def get_safe(self, v):
        try:
            return self.__getattribute__(v)
        except AttributeError:
            pass
            # if default:
            #     return default

    class Config:
        extra = 'allow'
