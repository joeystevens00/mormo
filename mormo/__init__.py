import logging
import os

import redis
from pydantic import (
    AnyUrl, BaseModel, BaseSettings, PyObject, PostgresDsn, Field
)


class Settings(BaseSettings):
    redis_host: str = 'localhost'
    redis_port: int = 6379
    testing: bool = False
    test_data_str_min_length: int = 1
    test_data_int_min: int = 1

    class Config:
        env_file = '.env'
        fields = {
            'redis_dsn': {
                'env': 'redis_url',
            },
            'testing': {
                'env': 'testing'
            }
        }


FAKE_REDIS_SERVER = None
def redis_handle():
    settings = Settings().dict()
    if settings['testing']:
        import fakeredis
        global FAKE_REDIS_SERVER
        if not FAKE_REDIS_SERVER:
            FAKE_REDIS_SERVER = fakeredis.FakeServer()
        r = fakeredis.FakeRedis(server=FAKE_REDIS_SERVER)
    else:
        r = redis.Redis(host=settings['redis_host'], port=settings['redis_port'])
    return r
# Ideas:
# Optimize for automated execution:
# - Attempt to identify resource that is being modified then order operations safely
# so that Create (likely a POST) happens before Read (GET) or Update (PATCH/PUT) and that Delete (DELETE) happens last
# - Find different bucketing mechanism (such as api pathing) so that duplicates dont exist in collection
#
# Automatic test generation
# Response code, mimetype are easy to check
# Attempt model validation for json

# TODO:
# Conversion between OpenAPI data types to postman data types

# Build an API using FastAPI or something else which provides openapi easily
# use this to test it
#
# some useful api routes

# POST /schema
# PUT /schema/:id/test/:host

# POST /jsonschema
# GET /jsonschema/:id/data

# Generate test data given a json schema
# /test/data/from_schema

# Generate a postman collection given an openapi schema
# /postman_collection_v3/from_openapi_schema

# Generate a postman collection and run it with newman
# /run/test/from_schema?host=
logger = logging.Logger(__name__)
logging.basicConfig(level='DEBUG')

from . import cli
