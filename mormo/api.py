from typing import Optional

from fastapi import FastAPI

from .convert import OpenAPIToPostman
from .schema import OpenAPISchemaToPostmanRequest, TestConfig, TestResult
from .schema.api import (
    SaveCollection, SaveOpenAPISchema, SaveTestConfig,
)
from .schema.openapi_v3 import OpenAPISchemaV3
from .schema.postman_collection_v2 import (
    Collection,
)
from .util import load_db, save_db
from . import logger

app = FastAPI(version='0.7.46')


@app.post("/schema", response_model=SaveOpenAPISchema)
def new_schema(o: OpenAPISchemaV3) -> SaveOpenAPISchema:
    """New Schema."""
    logger.debug("NEW SCHEMA")
    return save_db(o).to_dict()


@app.get('/schema/{digest}', response_model=OpenAPISchemaV3)
def get_schema(digest: str) -> OpenAPISchemaV3:
    return load_db(digest)


@app.post("/schema/{digest}/to_postman", response_model=SaveCollection)
def schema_to_postman(
    digest: str, o: Optional[OpenAPISchemaToPostmanRequest] = None,
) -> SaveCollection:
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


@app.get("/postman/{digest}/test", response_model=TestResult)
def run_postman_test(
    digest: str, host: str, verbose: Optional[bool] = False,
) -> TestResult:
    """Create a new test run from a postman collection."""
    return run_postman_collection(load_db(digest), host=host, verbose=verbose)


@app.post('/run/test/from_schema', response_model=TestResult)
def run_test_run_from_schema(o: OpenAPISchemaToPostmanRequest) -> TestResult:
    """Create a new test run from OpenAPI Schema."""
    from .convert import OpenAPIToPostman
    oapipm = OpenAPIToPostman(o)
    return run_postman_collection(
        oapipm.to_postman_collection_v2(),
        host=oapipm.host,
        verbose=oapipm.verbose,
    )
