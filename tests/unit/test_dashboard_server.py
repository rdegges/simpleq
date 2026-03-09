"""Unit tests for dashboard HTTP serving."""

from __future__ import annotations

from dataclasses import dataclass
from http.client import HTTPConnection
from threading import Thread

from simpleq.dashboard import Dashboard, create_dashboard_server


@dataclass
class FakeStats:
    name: str
    available_messages: int
    in_flight_messages: int
    delayed_messages: int
    dlq_available_messages: int | None = None
    dlq_in_flight_messages: int | None = None
    dlq_delayed_messages: int | None = None


class FakeQueue:
    def __init__(self, name: str) -> None:
        self.name = name

    async def stats(self) -> FakeStats:
        return FakeStats(
            name=self.name,
            available_messages=1,
            in_flight_messages=0,
            delayed_messages=0,
            dlq_available_messages=2,
        )


class FakeCostTracker:
    def total_cost(self) -> float:
        return 0.5

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {"emails": {"total_requests": 1, "jobs_processed": 1, "jobs_retried": 0}}


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

    def queue(self, name: str, *, fifo: bool = False) -> FakeQueue:
        assert fifo is False
        return FakeQueue(name)


def test_dashboard_render_with_explicit_queue_names() -> None:
    html = Dashboard(FakeSimpleQ(), queue_names=["emails"]).render_sync()
    assert "SimpleQ Dashboard" in html
    assert "emails" in html
    assert "DLQ visible" in html
    assert "2" in html


def test_dashboard_server_routes() -> None:
    server = create_dashboard_server(FakeSimpleQ(), host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        connection = HTTPConnection(host, port)
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert "SimpleQ Dashboard" in body

        connection.request("GET", "/metrics")
        response = connection.getresponse()
        assert response.status == 200
        assert b"simpleq_jobs_enqueued_total" in response.read()

        connection.request("GET", "/missing")
        response = connection.getresponse()
        assert response.status == 404
        response.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
