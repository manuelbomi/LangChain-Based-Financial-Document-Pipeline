.PHONY: install test lint typecheck run health-check build docker-build clean

install:
	python -m pip install --upgrade pip
	pip install -e ".[dev]"

test:
	pytest -v --cov=toolkit --cov-report=term-missing

lint:
	ruff check .

typecheck:
	mypy toolkit

# Runs the demo ingest pipeline against every bundled sample source.
run:
	toolkit ingest --source core-banking
	toolkit ingest --source relational-db
	toolkit ingest --source unstructured-files

health-check:
	toolkit health-check

build:
	python -m build

docker-build:
	docker build -t langchain-document-pipeline-toolkit:local .

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov data/state data/sample_bank.db
