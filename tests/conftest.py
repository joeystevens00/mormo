import random
import os
from types import GeneratorType
from pathlib import Path
import pytest

from mormo import redis_handle
from mormo.convert import OpenAPIToPostman
from mormo.model import BaseModel
from mormo.util import DB, gen_string

tests_dir_path = Path(__file__).parent.absolute()


def get_test_data(format, limit=5):
    data_path = str(tests_dir_path) + f'/data/openapi/{format}'
    d = [f"{data_path}/{f}" for f in os.listdir(data_path)]
    if limit and limit < len(d):
        random.shuffle(d)
        d = d[0:limit]
    return d


def pytest_addoption(parser):
    parser.addoption(
        "--test_file",
        help="Execute tests against OpenAPI Schema at path",
    )

def test_data(paths, collection=False):
    for path in paths:
        o =  OpenAPIToPostman(path=path)
        if collection:
            o = o.to_postman_collection_v2()
        yield o

def pytest_generate_tests(metafunc):
    files = [*get_test_data('yaml'), *get_test_data('json')]
    if "mormo" in metafunc.fixturenames:
        if metafunc.config.getoption("test_file"):
            kwargs = {'paths': [metafunc.config.getoption("test_file")]}
        else:
            kwargs = {'paths': files}
        metafunc.parametrize("mormo", test_data(**kwargs))

    if "postman_collection" in metafunc.fixturenames:
        if metafunc.config.getoption("test_file"):
            kwargs = {'paths': [metafunc.config.getoption("test_file")], 'collection': True}
        else:
            kwargs = {'paths': files, 'collection': True}
        metafunc.parametrize("postman_collection", test_data(**kwargs))

    if "openapi_schema_file" in metafunc.fixturenames:
        if metafunc.config.getoption("test_file"):
            td = [
                metafunc.config.getoption("test_file"),
            ]
        else:
            td = files
        metafunc.parametrize("openapi_schema_file", td)



@pytest.fixture
def openapi_schema_paths(mormo):
    assert isinstance(mormo.paths, GeneratorType)
    yield mormo.paths


def generate_dicts(num):
    return [
        {gen_string(2): gen_string(5), gen_string(2): gen_string(2)}
        for _ in range(num)
    ]


def generate_dict_expected(num, f):
    x = []
    for _ in range(num):
        d = {gen_string(2): gen_string(5), gen_string(2): gen_string(2)}
        x.append(
            (f(d), d)
        )
    return x


@pytest.fixture
def random_dict():
    for d in generate_dicts(1):
        yield d


@pytest.fixture
def test_dbo(random_dict, redis):
    yield (DB(redis, model=BaseModel.construct(**random_dict)), random_dict)


@pytest.fixture(params=[
        (BaseModel.construct(**test_dict), test_dict)
        for test_dict in generate_dicts(3)
    ]
)
def test_object(request):
    yield request.param


@pytest.fixture
def redis(scope='session'):
    os.environ['TESTING'] = '1'
    yield redis_handle()
