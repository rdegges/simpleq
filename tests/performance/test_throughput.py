"""Performance regression tests."""

from __future__ import annotations

import pytest

from tests.performance.benchmark import run_benchmark


@pytest.mark.integration
@pytest.mark.performance
@pytest.mark.asyncio
async def test_throughput_smoke() -> None:
    results = await run_benchmark(50)
    assert results["jobs_per_second"] > 1
