import json
import requests

with open('data/list.json') as f:
    data = json.load(f)

def get_remote_json(url):
    print(f"Fetching {url}")
    try:
        return requests.get(url).json()
    except Exception as e:
        print(f"Failed to get: {url}: {e}")

def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)

for site, d in data.items():
    json_url = d['versions'][d['preferred']]['swaggerUrl']
    remote = get_remote_json(json_url) or {}
    file_name = f'{site}.json'
    if remote.get('openapi'):
        write_file(f'data/3/{file_name}', json.dumps(remote))
    elif remote.get('swagger'):
        write_file(f'data/2/{file_name}', json.dumps(remote))
    else:
        print(f"Can't detect version of: {json_url}")
