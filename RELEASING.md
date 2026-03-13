# Releasing SimpleQ

Use this checklist for every tagged release.

## Before tagging

1. Update `CHANGELOG.md` with user-facing notes for the version being released.
2. Confirm docs and compatibility pages reflect any public API or runtime changes.
3. Run the full pre-release checks:

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run mypy simpleq
uv run mkdocs build --strict
uv run pytest -m "not live" --cov=simpleq --cov-report=term-missing --cov-fail-under=95
```

4. Verify executable examples still pass:

```bash
uv run pytest tests/unit/test_examples_and_docs.py
```

## Tagging and publish

1. Create the version tag after the checks above are green.
2. Push the tag and wait for the release workflow to complete.
3. Confirm the PyPI publish, GitHub release, and docs deployment all succeeded.

## After release

1. Start a fresh `Unreleased` section in `CHANGELOG.md` if the release closed it out.
2. Track any follow-up fixes with the `quality`, `docs-smoke`, `reliability`, or
   `typing` labels from `.github/labels.yml`.
