import logging

import redis
from pydantic import BaseSettings

FAKE_REDIS_SERVER = None

logger = logging.Logger(__name__)
logging.basicConfig(level='DEBUG')


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


def redis_handle():
    settings = Settings().dict()
    if settings['testing']:
        import fakeredis
        global FAKE_REDIS_SERVER
        if not FAKE_REDIS_SERVER:
            FAKE_REDIS_SERVER = fakeredis.FakeServer()
        r = fakeredis.FakeRedis(server=FAKE_REDIS_SERVER)
    else:
        r = redis.Redis(
            host=settings['redis_host'],
            port=settings['redis_port'],
        )
    return r


from . import cli  # noqa: E402, F401
