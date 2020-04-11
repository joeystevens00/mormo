import argparse
import requests
import json
import os
import yaml
import sys


def is_local_file_path(s):
    """Does not consider paths above cwd to be valid."""
    if (
        isinstance(s, str)
        and s.startswith('./')
        and os.path.exists(s)
        and os.path.isfile(s)
        and os.path.abspath(s).startswith(os.getcwd())
    ):
        return True


def load_file(f, content_type=None):
    if f.endswith('.yaml') or f.endswith('.yml') or content_type == 'yaml':
        load_f = yaml.safe_load
    elif f.endswith('.json') or content_type == 'json':
        load_f = json.load
    else:
        raise ValueError(f"Unknown file type: {f}")
    with open(f, 'r') as fp:
        return load_f(fp)


def resolve_local_file_refs(test_config):
    for path, td_item in test_config.items():
        variables = td_item.get('variables')
        if isinstance(variables, str) and is_local_file_path(variables):
            test_config[path]['variables'] = load_file(variables)
        elif isinstance(variables, dict):
            for k, v in (td_item.get('variables') or {}).items():
                if is_local_file_path(v):
                    test_config[path]['variables'] = load_file(v)
    return test_config


def main():
    parser = argparse.ArgumentParser(description='HTTP Service Build Server')
    parser.add_argument('--target', required=True, help='URL to OpenAPI schema on the host that will be tested')
    parser.add_argument('--test_config', help='Path to test config to use')
    parser.add_argument('--mormo_api', help='Host of mormo api to use')
    parser.add_argument('--verbose', action='store_true')

    args = parser.parse_args()
    req = {
        'target': args.target,
        'verbose': args.verbose,
    }
    if args.test_config:
        with open(args.test_config, 'r') as f:
            d = f.read()
        req['test_config'] = resolve_local_file_refs(yaml.safe_load(d))
    endpoint = f"{args.mormo_api}/run/test/from_schema"
    res = requests.post(endpoint, data=json.dumps(req))
    result = res.json()
    print(result['result']['stdout'])
    print(result['result']['stderr'])

if __name__ == "__main__":
    main()
