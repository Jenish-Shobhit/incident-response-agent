PY := .venv/bin/python

.DEFAULT_GOAL := help
.PHONY: help setup run test lint format check demo live docker-build docker-run clean

help: ## Show this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-13s %s\n", $$1, $$2}'

setup: ## Create .venv, install the package with dev tools, and create .env from the example
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e ".[dev]"
	@[ -f .env ] || (cp .env.example .env && echo "created .env -- mock mode by default; add a key for live runs")

run: ## Start the app at http://127.0.0.1:8000 (reads .env)
	$(PY) -m uvicorn incident_agent.api:app --host $${HOST:-127.0.0.1} --port $${PORT:-8000} --reload

test: ## Run the test suite (always mock mode, no tokens)
	$(PY) -m pytest

lint: ## Check style and common bugs
	$(PY) -m ruff check .

format: ## Fix what the linter can fix
	$(PY) -m ruff check . --fix

check: lint test ## Everything CI runs, locally

demo: ## Re-record web/demo/frames.json from a mock run
	$(PY) scripts/record_demo.py

live: ## Run the bundled incident in the terminal with the mode .env selects
	$(PY) scripts/live_run.py

docker-build: ## Build the production image
	docker build -t incident-response-agent .

docker-run: ## Run the image in mock mode on port 8000
	docker run --rm -p 8000:8000 incident-response-agent

clean: ## Remove caches and generated run output
	rm -rf .pytest_cache .ruff_cache .cache runs
	find . -name __pycache__ -type d -prune -not -path "./.venv/*" -exec rm -rf {} +
