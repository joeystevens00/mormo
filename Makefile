runargs = $(filter-out $@,$(MAKECMDGOALS))
ec =
ifeq ($(REMOTE), 1)
	ec = make ec
endif

.PHONY: default
default: clean
	poetry install
	poetry build
	poetry run pip3 install dist/mormo-*.whl

.PHONY: clean
clean:
	test "`ls dist`" && rm dist/* || return 0
	test "`ls .hypothesis`" && rm -rf .hypothesis/ || return 0
	test "`ls newman`" && rm -rf newman/ || return 0

.PHONY: test-nobuild
test-nobuild:
	poetry run pytest -s

.PHONY: test
test: default test-nobuild

.PHONY: bumpversion
bumpversion:
	poetry version patch

.PHONY: build
build: bumpversion default requirements.txt
		git commit requirements.txt -m "Requirements $(poetry version)"

.PHONY: requirements.txt
requirements.txt:
	poetry export -f requirements.txt > requirements.txt

.PHONY: docker_test
docker_test: requirements.txt
	docker build --build-arg target=test -t mormo:test .
	docker run --rm mormo:test

.PHONY: docker_api_image
docker_api_image: requirements.txt
	docker build --build-arg target=api -t mormo:api .

.PHONY: docker_api
docker_api: docker_api_image
	docker-compose up -d

.PHONY: api
api:
	poetry run uvicorn --port 8001 mormo.api:app

.PHONY: openapi_test_spec
.openapi_test_spec:
	curl localhost:8001/openapi.json > tests/data/openapi/json/openapi.json

.PHONY: test_against_local_api
test_against_local_api: openapi_test_spec
	poetry run python3 cli.py run -i tests/data/openapi/json/openapi.json -o o.json --host http://localhost:8001 --test -t data.yaml --verbose

.PHONY: test_against_local_api_curl
test_against_local_api_curl:
	bash scripts/test_api.sh
