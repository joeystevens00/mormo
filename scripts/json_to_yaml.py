import json
import yaml
import sys

with open(sys.argv[1]) as in_:
    data_in = json.load(in_)
    with open(sys.argv[2], 'w') as out:
        yaml.dump(data_in, out)
