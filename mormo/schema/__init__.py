from typing import Any, Dict, Optional, Union
import tempfile
from collections import defaultdict
from typing import List

from pydantic import AnyHttpUrl, Field

from . import openapi_v3, postman_collection_v2
from ..model import BaseModel


class TestData(BaseModel):
    route: str # "VERB PATH"
    in_: openapi_v3.ParameterIn
    key: str
    value: Any


class Expect(BaseModel):
    code: Optional[Union[int, str]]
    enabled: Optional[bool] = True


class TestDataFileItem(BaseModel):
    #route: str
    variables: Optional[Union[Dict[str, str], str]] # If str, load file as JSON
    expect: Optional[Expect]
    make_global: Optional[Dict[str, str]] # id: .id creates a {{id}} global from JSON_RESPONSE.id
    test: Optional[List[str]]
    prerequest: Optional[List[str]]


def list_of_test_data_to_params(test_data: List[TestData]) -> openapi_v3.ParameterRequestData:
    d = defaultdict(lambda: {})
    for t in test_data:
        d[t.in_.value][t.key] = t.value
    return openapi_v3.ParameterRequestData(**dict(d))


class NewmanResult(BaseModel):
    stderr: Optional[str]
    stdout: str
    json_: Optional[dict]

    class Config:
        fields = {'json_': 'json'}


class TestResult(BaseModel):
    result: NewmanResult
    code: int
    message: str


class TestRun(BaseModel):
    schema_: openapi_v3.OpenAPISchemaV3
    test_data: List[TestData]
    url: AnyHttpUrl

    class Config:
        fields = {'schema_': 'schema'}

    def run(self, **kwargs) -> TestResult:
        from ..util import run_newman
        tmp_file = tempfile.mkfile()
        self.schema_.to_file(tmp_file)
        run_newman(tmp_file, **kwargs)
        return TestResult(
            result={'todo': 1},
            code=1,
            message="not implemented"
        )


class OpenAPISchemaToPostmanRequest(BaseModel):
    schema_: Optional[openapi_v3.OpenAPISchemaV3]
    path: Optional[str] = None
    host: Optional[str]
    test_data: Optional[Dict[str, TestDataFileItem]] = None # Old test_data_file_content
    test_data_file: Optional[str] = None
    extra_test_data: Optional[List[TestData]] = None # Old test_data
    test_scripts: Optional[Dict[str, postman_collection_v2.Script]] = None
    prerequest_scripts: Optional[Dict[str, postman_collection_v2.Script]] = None
    collection_test_scripts: Optional[List[postman_collection_v2.Script]] = None
    collection_prerequest_scripts: Optional[List[postman_collection_v2.Script]] = None
    postman_global_variables: Optional[List[postman_collection_v2.Variable]] = None
    expect: Optional[Dict[str, Expect]] = None
    verbose: Optional[bool] = False
    resolve_references: Optional[bool] = False

    class Config:
        fields = {'schema_': 'schema'}
