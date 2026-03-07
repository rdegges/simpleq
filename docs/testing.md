# Testing

SimpleQ is designed for three testing layers.

## Unit tests

Use the built-in in-memory transport when you want deterministic tests with no AWS credentials and no Docker dependency.

```python
from simpleq import SimpleQ
from simpleq.testing import InMemoryTransport

sq = SimpleQ(transport=InMemoryTransport())
queue = sq.queue("emails")
```

Recommended targets:

- task serialization and schema validation
- retry logic
- queue bookkeeping
- CLI commands

Run them with:

```bash
uv sync --extra dev
uv run pytest tests/unit
```

## Integration tests

Use LocalStack when you want real SQS semantics.

```bash
docker compose up -d localstack
uv run pytest tests/integration
```

The test suite now auto-selects `http://localhost:4566` on the host and `http://localstack:4566` inside the dev container.

## Live AWS smoke tests

Live tests remain opt-in and require explicit credentials:

```bash
uv run pytest tests/live --run-live-aws -m live
```

Use these sparingly for final confidence, not for daily feedback loops.
