The test data file is a map of TestDataFileItem objects in either YAML or JSON. The key in the map is either the API Route (VERB /relative/path) or "Collection" E.g:
```
Collection:
  prerequest:
    - console.log("(Collection Prerequest Inserted)Happens before every request");
POST /schema:
  make_global:
      id: .id
  variables: ./tests/data/openapi/json/openapi.json
  expect:
      code: 200
GET /schema/{id}:
  variables:
      id: "{{id}}"
```
```
{"POST /schema": {"make_global": {"id": ".id"}, "variables": "./tests/data/openapi/json/openapi.json"}}
```
