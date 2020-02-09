#!/usr/bin/env python3
from collections import defaultdict
import os
import click
import json
import tempfile
import yaml

from mormo.convert import OpenAPIToPostman
from mormo.schema.postman_collection_v2 import Script, Variable
from mormo.schema import TestData, OpenAPISchemaToPostmanRequest
from mormo.util import run_newman, uuidgen

@click.group()
def cli():
    """OpenAPI to Postman Collection V2 Conversion."""
    pass


def generate_schema(infile, outfile, test_file, **kwargs):
    # if test_file:
    #     kwargs['test_data'] = kwargs.get('test_data', [])
    #
    #     with open(test_file, 'r') as f:
    #         for data in yaml.load(f.read()):
    #             for route, td_item in data.items():
    #                 i = TestDataFileItem(**td_item)
    #                 if isinstance(i.variables, str):
    #                     if i.variables.endswith('.json'):
    #                         with open(i.variables, 'r') as f:
    #                             variables = json.load(f)
    #                     else:
    #                         raise ValueError(f"Unknown variable file type: {i.variables}")
    #                 else:
    #                     variables = i.variables
    #                 kwargs['test_data'].extend([
    #                     TestData(route=route, in_='requestBody', key=k, value=v)
    #                     for k, v in variables.items()
    #                 ])
    #                 for variable, response_path in (i.make_global or {}).items():
    #                     response_path = ''.join(['["' + trim(p) +'"]' for p in response_path.split('.')[1:]])
    #                     print(variable, response_path)
    #                     if not kwargs.get('test_scripts'):
    #                         kwargs['test_scripts'] = defaultdict(lambda: [])
    #                     if not kwargs.get('collection_prerequest_scripts'):
    #                         kwargs['collection_prerequest_scripts'] = []
    #                     kwargs['collection_prerequest_scripts'].append(Script(
    #                         id=uuidgen(),
    #                         name=f'Debug {variable}',
    #                         exec=f'console.log("{variable}:", pm.globals.get("{variable}"));',
    #                         type='text/javascript',
    #                     ))
    #                     kwargs['test_scripts'][route].append(Script(
    #                         id=uuidgen(),
    #                         name=f'Set response of {route}: JSON_RESPONSE{response_path} to {variable}',
    #                         #exec=f'pm.environment.set("{variable}", pm.response.json(){response_path});',
    #                         exec="""
    #                             pm.test("Set {variable} global from JSON Response", function () {{
    #                                 pm.globals.set("{variable}", pm.response.json(){response_path});
    #                             }});
    #                         """.format(variable=variable, response_path=response_path),
    #                         type='text/javascript',
    #                     ))
    #                 if not kwargs.get('postman_global_variables'):
    #                    kwargs['postman_global_variables'] = []
    #                 kwargs['postman_global_variables'].append(Variable(id=variable, type='string'))
    #                 for k, v in variables.items():
    #                     kwargs['test_data'].extend([
    #                         TestData(route=route, in_=in_,key=k, value=v)
    #                         for in_ in list(ParameterIn)
    #                     ])
    oas = OpenAPIToPostman(OpenAPISchemaToPostmanRequest(path=infile, test_data_file=test_file, **kwargs))
    postman_collection = oas.to_postman_collection_v2()
    with open(outfile, 'w') as f:
        json.dump(postman_collection.dict(by_alias=True), f)


@cli.command()
@click.option('-i', '--in', 'in_file', type=click.Path(),
              help='The OpenAPI Schema to convert.')
@click.option('-t', '--test_file', 'test_file', type=click.Path(),
              help='Load test_data from file.')
@click.option('-o', '--out', 'out_file', type=click.Path(),
              help='The path to write the Postman Collection to.',
              default='postman_collection_v2.json')
@click.option('--test', is_flag=True,
              help='Execute the generated schema with newman.')
@click.option('--host', 'host', help='Target API')
@click.option('--verbose', is_flag=True,
              help='Verbose option in newman.')
def run(in_file, test_file, out_file, test, host, verbose):
    """Generate Postman Collections."""
    generate_schema(in_file, out_file, test_file, host=host)
    if test:
        run_newman(out_file, host=host, verbose=verbose)


if __name__=="__main__":
    cli()
