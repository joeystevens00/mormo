from typing import Optional

from fastapi import FastAPI

from .convert import OpenAPIToPostman
from .schema import OpenAPISchemaToPostmanRequest, TestResult
from .schema.openapi_v3 import OpenAPISchemaV3, SaveDBResult
from .schema.postman_collection_v2 import (
    Collection,
    SaveDBResult as PostmanSaveDBResult,
)
from .util import load_db, save_db
from . import logger

app = FastAPI(version='0.7.44')


@app.post("/schema", response_model=SaveDBResult)
def new_schema(o: OpenAPISchemaV3) -> SaveDBResult:
    """New Schema."""
    logger.debug("NEW SCHEMA")
    return save_db(o).to_dict()


@app.get('/schema/{digest}', response_model=OpenAPISchemaV3)
def get_schema(digest: str) -> OpenAPISchemaV3:
    return load_db(digest)


@app.post("/schema/{digest}/to_postman", response_model=PostmanSaveDBResult)
def schema_to_postman(
    digest: str, o: Optional[OpenAPISchemaToPostmanRequest] = None,
) -> PostmanSaveDBResult:
    """Convert schema to Collection."""
    if o:
        kwargs = o.to_dict()
    else:
        kwargs = {}
    kwargs['schema_'] = load_db(digest)
    o = OpenAPIToPostman(**kwargs).to_postman_collection_v2()
    return save_db(o).to_dict()


@app.get("/postman/{digest}", response_model=Collection)
def get_postman(digest: str) -> Collection:
    """Get Postman Collection by ID."""
    return load_db(digest)


def run_postman_collection(
    collection, host: str, verbose: Optional[bool] = False,
):
    return TestResult(
        result=collection.run(host=host, verbose=verbose, json=True),
        code=0,
        message="Newman executed"
    )

# @app.post("/postman/{digest}/test", response_model=TestResult)
# def run_postman_test_from_args(digest: str, o: OpenAPISchemaToPostmanRequest) -> TestResult:
#     """Create a new test run from a postman collection."""
#     return run_postman_collection(OpenAPIToPostman(o), host=host, verbose=verbose)

@app.get("/postman/{digest}/test", response_model=TestResult)
def run_postman_test(
    digest: str, host: str, verbose: Optional[bool] = False,
) -> TestResult:
    """Create a new test run from a postman collection."""
    return run_postman_collection(load_db(digest), host=host, verbose=verbose)


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
        host=o.host,
        verbose=o.verbose,
    )

# @app.get('/test/run/{digest}/fire', response_model=TestResult)
# def run_test_run(digest):
#     load_db(digest)
