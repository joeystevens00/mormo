import json

from shlex import quote
import subprocess
import tempfile

from .schema import NewmanResult
from .schema.postman_collection_v2 import (
    Event, Script,
)
from .util import (
    fingerprint, load_file, trim, uuidgen,
)


def run_newman(collection_file, host=None, verbose=None, json=False):
    cmdargs = []
    json_outfile, json_content = None, None
    if host:
        cmdargs.extend(['--env-var', f'baseUrl={quote(host)}'])
    if verbose:
        cmdargs.append('--verbose')
    cmdargs.extend(['--reporters', f'cli{",json" if json else ""}'])
    if json:
        json_outfile = tempfile.mktemp()
        cmdargs.extend(["--reporter-json-export", json_outfile])
    run_newman_args = ['newman', 'run', quote(collection_file), *cmdargs]
    e = subprocess.run(
        args=run_newman_args,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    print('EXEC', *run_newman_args)
    print('STDOUT', e.stdout.decode('utf-8'))
    print('STDERR', e.stderr.decode('utf-8'))
    if json_outfile:
        json_content = load_file(json_outfile, content_type='json')

    return NewmanResult(
        stderr=e.stderr.decode('utf-8'),
        stdout=e.stdout.decode('utf-8'),
        json_=json_content,
        code=e.returncode,
    )


def new_event(listen, script):
    if isinstance(script, list):
        if not len(script):
            return
        _script = script[0]
        for i in script[1:]:
            _script += i
        script = _script
    return Event(id=uuidgen(), listen=listen, script=script, disabled=False)


def javascript(name, exec):
    return Script(
        id=fingerprint([name, exec]),
        name=name,
        exec=trim(exec),
        type='text/javascript',
    )


def js_test_code(route, code):
    return javascript(
        name=f"{route} Test Code is {code}",
        exec="""
                pm.test("Status code is {code}", function () {{
                    return pm.response.to.have.status({code});
                }});
            """.format(code=code),
    )


def js_test_content_type(route, mimetype):
    return javascript(
        name=f"{route} Mimetype is {mimetype}",
        exec="""
                pm.test("Content-Type Header is {mimetype}", function () {{
                    return pm.expect(postman.getResponseHeader("Content-type")).to.be.eql("{mimetype}");
                }});
            """.format(mimetype=mimetype),
    )


def js_test_response_time(route, max_time_ms):
    return javascript(
        name=f"{route} responds in less than {max_time_ms}ms",
        exec="""
                pm.test("Response time is less than {max_time_ms}ms", function () {{
                    return pm.expect(pm.response.responseTime).to.be.below({max_time_ms});
                }});
            """.format(max_time_ms=max_time_ms),
    )


def js_test_validate_schema(route, schema, reference_schema):
    return javascript(
        name=f"{route} responds according to schema",
        exec="""
            pm.test('Schema is valid', function() {{
                var schema = {schema};
                tv4.addSchema({reference_schema});
                pm.expect(tv4.validate(pm.response.json(), schema)).to.be.true;
            }});
        """.format(schema=json.dumps(schema), reference_schema=json.dumps(reference_schema))
    )
