## Summary

Describe the user-facing change.

## Testing

- [ ] `uv run pytest tests/unit`
- [ ] `uv run pytest tests/unit/test_examples_and_docs.py`
- [ ] `uv run pytest tests/integration`
- [ ] `uv run pytest -m "not live" --cov=simpleq --cov-report=term-missing --cov-fail-under=95`
- [ ] `uv run ruff check .`
- [ ] `uv run mypy simpleq`
- [ ] `uv run mkdocs build --strict`

## Checklist

- [ ] Docs updated when needed
- [ ] `CHANGELOG.md` updated for user-facing changes
- [ ] Type hints preserved
- [ ] Retry, FIFO, and DLQ behavior considered
