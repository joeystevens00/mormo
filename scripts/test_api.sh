set -xeuo pipefail

ENDPOINT=http://localhost:8001
SCHEMA="$(curl $ENDPOINT/openapi.json)"

id=$(curl -XPOST -d "$SCHEMA" -H 'Content-Type: application/json' $ENDPOINT/schema | jq '.id' | tr -d '"')

curl $ENDPOINT/schema/$id | jq '.openapi'
postman_id=$(curl -XPOST $ENDPOINT/schema/$id/to_postman | jq '.id' | tr -d '"')
curl $ENDPOINT/postman/$postman_id | jq '.info'
#curl -XPOST -d "{\"host\": \"$ENDPOINT\", \"test_config\": { \"GET /schema/{id}\": {\"variables\": {\"id\": \"$id\"}}" $ENDPOINT/postman/$postman_id/test | jq '.result.json'
curl $ENDPOINT/postman/$postman_id/test?host=$ENDPOINT | jq '.result.json'
#curl -XPOST -d "$SCHEMA" -H 'Content-Type: application/json' $ENDPOINT/run/test/from_schema?host=$ENDPOIN
