#!/usr/bin/env python3
import click
import json

from mormo.convert import OpenAPIToPostman
from mormo.postman_test import run_newman


@click.group()
def cli():
    """OpenAPI to Postman Collection V2 Conversion."""
    pass


def generate_schema(infile, outfile, test_file, **kwargs):
    oas = OpenAPIToPostman(path=infile, test_data_file=test_file, **kwargs)
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


if __name__ == "__main__":
    cli()
