.PHONY: install run test check docker-build docker-run

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements-dev.txt

run:
	./run.sh

test:
	.venv/bin/python -m pytest

check:
	.venv/bin/python -m compileall -q app tools
	.venv/bin/python -m pytest

docker-build:
	docker build -t incident-response-agent .

docker-run:
	docker run --rm -p 8000:8000 incident-response-agent
