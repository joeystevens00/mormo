from . import TestConfig
from .openapi_v3 import OpenAPISchemaV3
from .postman_collection_v2 import Collection
from ..model import BaseModel

class SaveOpenAPISchema(BaseModel):
    id: str
    object: OpenAPISchemaV3


class SaveTestConfig(BaseModel):
    id: str
    object: TestConfig


class SaveCollection(BaseModel):
    id: str
    object: Collection
