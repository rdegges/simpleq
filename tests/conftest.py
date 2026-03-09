"""Shared pytest fixtures for the SimpleQ test suite."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from simpleq import SimpleQ
from simpleq.config import detect_localstack_endpoint
from tests.fixtures import tasks

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom pytest flags."""
    parser.addoption(
        "--run-live-aws",
        action="store_true",
        default=False,
        help="Run tests that hit real AWS resources.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip live AWS tests unless explicitly requested."""
    if config.getoption("--run-live-aws"):
        return
    skip_live = pytest.mark.skip(reason="Use --run-live-aws to run real AWS tests.")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def reset_task_state() -> Iterator[None]:
    """Reset shared task fixtures between tests."""
    tasks.reset_state()
    yield
    tasks.reset_state()


@pytest.fixture(autouse=True)
def clear_simpleq_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear SimpleQ-specific env vars between tests."""
    env_names = [
        "SIMPLEQ_ENDPOINT_URL",
        "SIMPLEQ_ENV",
        "LOCALSTACK_HOSTNAME",
        "CI",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_ENDPOINT_URL",
        "AWS_ENDPOINT_URL_SQS",
        "SIMPLEQ_BATCH_SIZE",
        "SIMPLEQ_WAIT_SECONDS",
        "SIMPLEQ_VISIBILITY_TIMEOUT",
        "SIMPLEQ_CONCURRENCY",
        "SIMPLEQ_GRACEFUL_SHUTDOWN_TIMEOUT",
        "SIMPLEQ_MAX_RETRIES",
        "SIMPLEQ_BACKOFF_STRATEGY",
        "SIMPLEQ_COST_TRACKING",
        "SIMPLEQ_ENABLE_METRICS",
        "SIMPLEQ_ENABLE_TRACING",
        "SIMPLEQ_LOG_LEVEL",
        "SIMPLEQ_SQS_PRICE_PER_MILLION",
        "SIMPLEQ_DEFAULT_QUEUE",
    ]
    original = {name: os.environ.get(name) for name in env_names}
    for name in env_names:
        monkeypatch.delenv(name, raising=False)
    yield
    for name, value in original.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


@pytest.fixture
def localstack_endpoint(monkeypatch: pytest.MonkeyPatch) -> str:
    """Configure environment variables for LocalStack-backed tests."""
    endpoint = (
        os.getenv("SIMPLEQ_ENDPOINT_URL")
        or detect_localstack_endpoint()
        or "http://localhost:4566"
    )
    monkeypatch.setenv("SIMPLEQ_ENDPOINT_URL", endpoint)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("SIMPLEQ_ENV", "test")
    return endpoint


@pytest.fixture
def simpleq_localstack(localstack_endpoint: str) -> SimpleQ:
    """Return a SimpleQ client configured for LocalStack."""
    return SimpleQ(
        endpoint_url=localstack_endpoint, wait_seconds=0, visibility_timeout=2
    )


@pytest.fixture
def unique_name() -> Callable[[str], str]:
    """Build unique queue names per test."""

    def factory(prefix: str) -> str:
        return f"{prefix}-{uuid4().hex[:8]}"

    return factory


@pytest.fixture
async def cleanup_queues(simpleq_localstack: SimpleQ) -> AsyncIterator[list]:
    """Delete created queues after each test."""
    created = []
    yield created
    for queue in reversed(created):
        with suppress(Exception):
            await queue.delete()


async def eventually(
    predicate: Callable[[], Awaitable[bool] | bool],
    *,
    timeout: float = 10.0,
    interval: float = 0.2,
) -> None:
    """Poll until a predicate is true or raise on timeout."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = predicate()
        if asyncio.iscoroutine(result):
            if await result:
                return
        elif result:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Timed out waiting for predicate.")
        await asyncio.sleep(interval)
