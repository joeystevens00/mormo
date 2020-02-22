.. Mormo documentation master file, created by
   sphinx-quickstart on Tue Feb 11 18:24:34 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to Mormo's documentation!
=================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   schema
   openapi
   postman_collection
   api
   cli
   convert


.. start-badges

.. list-table::
    :stub-columns: 1

    * - docs
      - |docs|
    * - tests
      - | |travis| |coverage|
    * - package
      - | |commits-since|

.. |docs| image:: https://readthedocs.org/projects/mormo/badge/?version=0.7
    :target: https://mormo.readthedocs.io/en/0.7
    :alt: Documentation Status

.. |travis| image:: https://travis-ci.com/joeystevens00/mormo.svg?branch=0.7
    :alt: Travis-CI Build Status
    :target: https://travis-ci.com/joeystevens00/mormo

.. |coverage| image:: https://coveralls.io/repos/github/joeystevens00/mormo/badge.svg?branch=0.7
    :target: https://coveralls.io/github/joeystevens00/mormo?branch=0.7
    :alt: Coveralls Coverage Status

.. |commits-since| image:: https://img.shields.io/github/commits-since/joeystevens00/mormo/master/0.7.svg
    :alt: Commits since latest release
    :target: https://github.com/joeystevens00/mormo/compare/master...0.7

.. end-badges

Mormo is an API testing framework that attempts to automatically test APIs given their OpenAPI schema. It works by converting the OpenAPI schema into Postman collection schema with automatically generated tests, and executing the resulting collection with Newman.

Install
--------

::

  pip3 install mormo

CLI
----

::

  # Convert OpenAPI Schema to Postman Collection V2 Schema
  mormo run --in openapi.json --out postman_collection.json
  # Run the generated postman collection with Newman
  mormo run --in openapi.json --test --host http://127.0.0.1:8001
  # .. with a test config
  mormo run --in openapi.json --test --host http://127.0.0.1:8001 --test_file test_config.json


API
----

::

  mormo api

  # Or use uvicorn directly
  uvicorn --port 8001 mormo.api:app

See http://127.0.0.1:8001/docs for API documentation


Test Config
-----------
A test config can be provided to set test data, insert tests/prerequest scripts, override test expectations, set response values to global variables, and more.

Examples
#########

make_global
***********
The response from POST /operation is serialized as JSON and the JSON attribute 'operationId' set to a postman global variable named 'operation_id'. In the request to GET /operation/{id} the 'operation_id' global variable is used.

::

  POST /operation:
    make_global:
      operation_id: .operationId
    variables:
      summary: Test Operation
      tags: openapi
  GET /operation/{id}
    variables:
      id: {{operation_id}}


Collection Test Config
***********************
The collection test config can be used to set default test expectations, insert collection prerequest/test scripts, or global variables

::

  collection:
    expect:
      response_time: 200
      fake_data: True
      enabled_tests: [schema_validation, code, content_type, response_time]
    prerequest:
      - console.log('before every request');
    test:
      - console.log('some global test');


Setting expectations
*********************
::

  collection:
    expect:
      code: 200 # All routes should return 200 unless set otherwise
      response_time: 100 # All routes should reply within 100ms
  PUT /abc:
    expect:
      code: 202 # Override the default expectations for a route
      response_time: 125
  GET /removed/route:
    expect:
      code: 404
      response_time: 50

Disabling Tests
****************
The builtin tests can be disabled all together by setting Expect.enabled to False

::

  collection:
    expect:
      enabled: False # Disabled by default
  POST /abc:
    expect:
      enabled: True # Enabled for specific route


See :class:`mormo.schema.TestConfig` and  :class:`mormo.schema.Expect` for all options.

Test Data Precedence
-----------------------
- Test Data in Test Config
- example or examples field in schema :class:`mormo.schema.openapi_v3.Parameter`
- Randomly generated from schema :class:`mormo.schema.openapi_v3.ParameterSchema`

Builtin Tests
---------------
==================  ==========================================================================================
code                Response code should match the first 2XX response defined in the schema (or the Expect setting if set)

schema_validation   Response JSON is validated with Tiny Validator against the schema

content_type        Content-Type Header should match the mimetype defined in the schema

response_time       Server should respond within a number of milliseconds
==================  ==========================================================================================


Safe Ordering of CRUD Operations
---------------------------------
Mormo assumes your API is RESTFul so it orders operations to resources safely. It detects resources based on the path (/store, /store/{id}) and prioritizes HTTP verbs associated with create operations to ensure that the resource exists before reads/updates and deprioritizes deletes.

The ordering used can be seen in the `verb_ordering` parameter of the `order_routes_by_resource` method:
:meth:`mormo.convert.OpenAPIToPostman.order_routes_by_resource`



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
