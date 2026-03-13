# Contributing

## Development setup

```bash
uv sync --all-extras
pre-commit install
```

For LocalStack-backed integration tests:

```bash
docker compose up -d localstack
```

## Local checks

Use this order for fast feedback:

```bash
uv run pytest tests/unit
uv run pytest tests/unit/test_examples_and_docs.py
uv run ruff check .
uv run mypy simpleq
uv run mkdocs build --strict
uv run pytest tests/integration
uv run pytest -m "not live" --cov=simpleq --cov-report=term-missing --cov-fail-under=95
```

## Pull requests

Every PR should:

- include tests for behavior changes
- keep the executable docs and examples green
- keep type hints complete
- keep docs current when public behavior changes
- avoid breaking FIFO, DLQ, or LocalStack workflows

## Quality tracking

Quality work should stay visible in issues and PRs. The repository keeps a
starter label set in `.github/labels.yml` with:

- `quality`
- `docs-smoke`
- `reliability`
- `typing`

## Design expectations

- keep SQS-native concepts visible
- prefer small, explicit APIs over broker-agnostic abstraction
- preserve both async-first ergonomics and sync escape hatches
