from typing import Optional
import tempfile

from fastapi import FastAPI
from .schema import OpenAPISchemaToPostmanRequest, TestResult
from .schema.openapi_v3 import OpenAPISchemaV3, SaveDBResult
from .schema.postman_collection_v2 import (
    Collection,
    SaveDBResult as PostmanSaveDBResult,
)
from .util import DB, run_newman
from . import logger, redis_handle

app = FastAPI()


def save_db(o, response_cls):
    odb = DB(redis_handle(), model=o)
    if not odb.save():
        raise ValueError(f"Unable to save {o}(uid: {odb.uid}) to the DB.")
    logger.debug(f"New {type(o)}: {odb.uid}")
    return response_cls(id=odb.uid, object=o)


def load_db(id):
    return DB.load_model_from_uid(redis_handle(), id)


@app.post("/schema", response_model=SaveDBResult)
def new_schema(o: OpenAPISchemaV3) -> SaveDBResult:
    """New Schema."""
    logger.debug("NEW SCHEMA")
    return save_db(o, SaveDBResult).to_dict()


@app.get('/schema/{id}', response_model=OpenAPISchemaV3)
def get_schema(id: str) -> OpenAPISchemaV3:
    return load_db(id)


@app.post("/schema/{id}/to_postman", response_model=PostmanSaveDBResult)
def schema_to_postman(
    id: str, o: Optional[OpenAPISchemaToPostmanRequest] = None,
) -> PostmanSaveDBResult:
    """Convert schema to Collection."""
    from .convert import OpenAPIToPostman
    if o:
        kwargs = o.to_dict()
    else:
        kwargs = {}
    kwargs['schema_'] = load_db(id)
    o = OpenAPIToPostman(**kwargs).to_postman_collection_v2()
    return save_db(o, PostmanSaveDBResult).to_dict()


@app.get("/postman/{id}", response_model=Collection)
def get_postman(id: str) -> Collection:
    """Get Postman Collection by ID."""
    return load_db(id)


def run_postman_collection(
    collection, host: str, verbose: Optional[bool] = False,
):
    tmp_file = tempfile.mktemp()
    collection.to_file(tmp_file)
    e = run_newman(tmp_file, host=host, verbose=verbose, json=True)
    return TestResult(
        result=e,
        code=0,
        message="Newman executed"
    )


@app.post("/postman/{id}/test", response_model=TestResult)
def run_postman_test(
    id: str, host: str, verbose: Optional[bool] = False,
) -> TestResult:
    """Create a new test run from a postman collection."""
    return run_postman_collection(load_db(id), host=host, verbose=verbose)


# @app.post('/test/run', response_model=SaveDBResult)
# def new_test_run(o: TestRun) -> SaveDBResult:
#     """Create a new test run."""
#     return save_db(o)


@app.post('/run/test/from_schema', response_model=TestResult)
def run_test_run_from_schema(o: OpenAPISchemaToPostmanRequest) -> TestResult:
    """Create a new test run from OpenAPI Schema."""
    from .convert import OpenAPIToPostman
    return run_postman_collection(
        OpenAPIToPostman(o).to_postman_collection_v2(),
    )

# @app.get('/test/run/{id}/fire', response_model=TestResult)
# def run_test_run(id):
#     load_db(id)
