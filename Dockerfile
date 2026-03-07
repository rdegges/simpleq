FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/simpleq/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY pyproject.toml README.md ./
COPY simpleq ./simpleq
COPY tests ./tests
COPY docs ./docs
COPY mkdocs.yml ./

RUN uv sync --all-extras

CMD ["uv", "run", "pytest", "-q"]
