#!/usr/bin/env python3
import json
from multiprocessing import Process
import sys

import click
import uvicorn

from mormo.api import app
from mormo.convert import OpenAPIToPostman
from mormo.postman_test import run_newman


@click.group()
def cli():
    """OpenAPI to Postman Collection V2 Conversion."""
    pass


@cli.command()
def api():
    uvicorn.run(host="127.0.0.1", port=8001, log_level="info")


def generate_schema(infile, outfile, test_file, **kwargs):
    oas = OpenAPIToPostman(path=infile, test_data_file=test_file, **kwargs)
    postman_collection = oas.to_postman_collection_v2()
    with open(outfile, 'w') as f:
        json.dump(postman_collection.to_dict(), f)


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
@click.option('--test_mormo_api', is_flag=True,
              help='Spin up a mormo API with the binds in host.')
@click.option('--host', 'host', help='Target API')
@click.option('--verbose', is_flag=True,
              help='Verbose option in newman.')
def run(in_file, test_file, out_file, test, test_mormo_api, host, verbose):
    """Generate Postman Collections."""
    generate_schema(in_file, out_file, test_file, host=host)
    if test:
        if test_mormo_api:
            addr, port = host.split('/')[-1].split(':')
            port = port or 80
            print(addr, port)
            proc = Process(
                target=uvicorn.run,
                args=(app,),
                kwargs={
                    "host": addr,
                    "port": int(port),
                    "log_level": "info",
                },
                daemon=True,
            )
            proc.start()
        res = run_newman(out_file, host=host, verbose=verbose)
        if test_mormo_api:
            proc.terminate()
        sys.exit(res.code)


if __name__ == "__main__":
    cli()
