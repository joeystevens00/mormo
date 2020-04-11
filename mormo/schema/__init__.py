import enum
from typing import Any, Dict, List, Optional, Union
from collections import defaultdict

from . import openapi_v3, postman_collection_v2
from ..model import BaseModel


class TestData(BaseModel):
    route: str
    in_: openapi_v3.ParameterIn
    key: str
    value: Any


class PostmanTest(enum.Enum):
    schema_validation = 'schema_validation'
    code = 'code'
    content_type = 'content_type'
    response_time = 'response_time'


class Expect(BaseModel):
    code: Optional[Union[int, str]]
    enabled: bool = True
    response_time: int = 200
    headers: Optional[Dict[str, str]]
    fake_data: bool = True
    enabled_tests: List[PostmanTest] = [
        PostmanTest.schema_validation,
        PostmanTest.code,
        PostmanTest.content_type,
        PostmanTest.response_time,
    ]


class TestConfig(BaseModel):
    variables: Optional[Union[str, Dict[str, Any]]]
    expect: Optional[Expect]
    make_global: Optional[Dict[str, str]]
    test: Optional[List[str]]
    prerequest: Optional[List[str]]
    headers: Optional[Dict[str, str]]


def list_of_test_data_to_params(
    route, test_data: List[TestData]
) -> openapi_v3.ParameterRequestData:
    d = defaultdict(lambda: {})
    for t in test_data:
        if t.route.lower() == route.lower():
            d[t.in_.value][t.key] = t.value
    return openapi_v3.ParameterRequestData(**dict(d))


class NewmanResult(BaseModel):
    stderr: Optional[str]
    stdout: str
    json_: Optional[dict]
    code: int

    class Config:
        fields = {'json_': 'json'}


class TestResult(BaseModel):
    result: NewmanResult
    code: int
    message: str


# class TestRun(BaseModel):
#     schema_: openapi_v3.OpenAPISchemaV3
#     test_data: List[TestData]
#     url: AnyHttpUrl
#
#     class Config:
#         fields = {'schema_': 'schema'}
#
#     def run(self, **kwargs) -> TestResult:
#         from ..util import run_newman
#         tmp_file = tempfile.mkfile()
#         self.schema_.to_file(tmp_file)
#         run_newman(tmp_file, **kwargs)
#         return TestResult(
#             result={'todo': 1},
#             code=1,
#             message="not implemented"
#         )


class OpenAPISchemaToPostmanRequest(BaseModel):
    schema_: Optional[openapi_v3.OpenAPISchemaV3]
    path: Optional[str]
    host: Optional[str]
    target: Optional[str]
    test_config: Optional[Dict[str, TestConfig]] = None
    test_data_file: Optional[str] = None
    test_data: Optional[List[TestData]] = None
    test_scripts: Optional[Dict[str, postman_collection_v2.Script]] = None
    prerequest_scripts: Optional[Dict[str, postman_collection_v2.Script]] = None  # noqa: E501
    collection_test_scripts: Optional[List[postman_collection_v2.Script]] = None  # noqa: E501
    collection_prerequest_scripts: Optional[List[postman_collection_v2.Script]] = None  # noqa: E501
    collection_global_variables: Optional[List[postman_collection_v2.Variable]] = None  # noqa: E501
    expect: Optional[Dict[str, Expect]] = None
    verbose: Optional[bool] = False

    class Config:
        fields = {'schema_': 'schema'}
