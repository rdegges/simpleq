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
uv run ruff check .
uv run mypy simpleq
uv run mkdocs build --strict
uv run pytest tests/integration
```

## Pull requests

Every PR should:

- include tests for behavior changes
- keep type hints complete
- keep docs current when public behavior changes
- avoid breaking FIFO, DLQ, or LocalStack workflows

## Design expectations

- keep SQS-native concepts visible
- prefer small, explicit APIs over broker-agnostic abstraction
- preserve both async-first ergonomics and sync escape hatches
