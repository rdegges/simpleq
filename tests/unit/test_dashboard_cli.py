"""Unit tests for dashboard and CLI helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass

from typer.testing import CliRunner

from simpleq.cli import app
from simpleq.dashboard import Dashboard

runner = CliRunner()


@dataclass
class FakeStats:
    name: str = "emails"
    available_messages: int = 3
    in_flight_messages: int = 1
    delayed_messages: int = 0


class FakeQueue:
    def __init__(self) -> None:
        self.name = "emails"

    async def stats(self) -> FakeStats:
        return FakeStats()


class FakeCostTracker:
    def total_cost(self) -> float:
        return 0.123

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            "emails": {
                "total_requests": 2,
                "jobs_processed": 1,
                "jobs_retried": 0,
                "jobs_decode_failed": 0,
            }
        }


class FakeMetrics:
    def render(self) -> bytes:
        return b"simpleq_jobs_enqueued_total 1"


class FakeSimpleQ:
    def __init__(self) -> None:
        self.cost_tracker = FakeCostTracker()
        self.metrics = FakeMetrics()

    async def list_queues(self, prefix: str | None = None) -> list[str]:
        assert prefix is None
        return ["emails"]

    def list_queues_sync(self, prefix: str | None = None) -> list[str]:
        assert prefix == "em"
        return ["emails"]

    def queue(self, name: str, *, fifo: bool = False, dlq: bool = False) -> FakeQueue:
        assert name == "emails"
        assert not fifo
        assert not dlq
        return FakeQueue()


def test_dashboard_render() -> None:
    html = Dashboard(FakeSimpleQ()).render_sync()
    assert "SimpleQ Dashboard" in html
    assert "emails" in html


def test_cli_queue_list(monkeypatch) -> None:
    monkeypatch.setattr("simpleq.cli.make_client", lambda **_: FakeSimpleQ())
    result = runner.invoke(app, ["queue", "list", "--prefix", "em"])
    assert result.exit_code == 0
    assert json.loads(result.stdout.strip()) == ["emails"]
