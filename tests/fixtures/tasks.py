"""Reusable task functions for tests."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from pydantic import BaseModel

LOG: list[tuple[str, Any]] = []
COUNTS: defaultdict[str, int] = defaultdict(int)


class EmailPayload(BaseModel):
    """Pydantic payload model used by schema tests."""

    to: str
    subject: str
    body: str


def reset_state() -> None:
    """Reset global task state between tests."""
    LOG.clear()
    COUNTS.clear()


def record_sync(value: str) -> str:
    """Record a sync task execution."""
    LOG.append(("sync", value))
    return value


async def record_async(value: str) -> str:
    """Record an async task execution."""
    LOG.append(("async", value))
    return value


async def fail_once(key: str) -> str:
    """Fail once for a given key, then succeed."""
    COUNTS[key] += 1
    if COUNTS[key] == 1:
        raise RuntimeError("first failure")
    LOG.append(("retry-success", key))
    return key


async def always_fail(key: str) -> None:
    """Always fail for DLQ tests."""
    COUNTS[key] += 1
    raise RuntimeError(f"failure-{key}")


async def sleep_and_record(value: str, *, delay: float = 2.5) -> str:
    """Sleep past the initial visibility timeout, then record execution."""
    await asyncio.sleep(delay)
    LOG.append(("slept", value))
    return value


async def schema_task(payload: EmailPayload) -> str:
    """Schema-backed task used in tests."""
    LOG.append(("schema", payload.to))
    return payload.subject
