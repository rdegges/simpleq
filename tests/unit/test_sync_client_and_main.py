"""Unit tests for sync helpers, client helpers, and module entrypoints."""

from __future__ import annotations

import asyncio
import runpy

import pytest

from simpleq import SimpleQ
from simpleq._sync import run_sync
from simpleq.queue import Queue
from simpleq.testing import InMemoryTransport


def test_run_sync_without_active_loop() -> None:
    assert run_sync(asyncio.sleep(0, result=5)) == 5


@pytest.mark.asyncio
async def test_run_sync_from_active_loop() -> None:
    assert run_sync(asyncio.sleep(0, result=7)) == 7


@pytest.mark.asyncio
async def test_run_sync_propagates_exception_from_thread() -> None:
    async def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        run_sync(boom())


def test_simpleq_queue_cache_and_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    simpleq = SimpleQ(default_queue_name="jobs", transport=InMemoryTransport())
    queue = simpleq.queue("emails")
    assert simpleq.queue("emails") is queue
    assert simpleq.resolve_queue(None).name == "jobs"
    assert simpleq.resolve_queue("orders.fifo").fifo is True
    assert simpleq.resolve_queue(queue) is queue
    custom = Queue(simpleq, "custom")
    assert simpleq.resolve_queue(custom) is custom

    async def fake_list(prefix: str | None) -> list[str]:
        assert prefix == "mail"
        return ["https://sqs.aws/123/emails"]

    monkeypatch.setattr(simpleq.transport, "list_queues", fake_list)
    assert simpleq.list_queues_sync("mail") == ["emails"]
    assert simpleq.run_sync(asyncio.sleep(0, result="ok")) == "ok"
    marker = object()
    assert simpleq.resolve_queue(marker) is marker


def test_resolve_queue_prefers_existing_configured_queue() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    configured = simpleq.queue(
        "emails",
        dlq=True,
        wait_seconds=0,
        visibility_timeout=7,
    )

    resolved = simpleq.resolve_queue("emails")

    assert resolved is configured
    assert resolved.dlq is True
    assert resolved.wait_seconds == 0
    assert resolved.visibility_timeout == 7


def test_resolve_queue_rebinds_foreign_queue_to_current_simpleq() -> None:
    source = SimpleQ(transport=InMemoryTransport())
    foreign = source.queue(
        "emails",
        dlq=True,
        wait_seconds=0,
        visibility_timeout=9,
    )
    target = SimpleQ(transport=InMemoryTransport())

    rebound = target.resolve_queue(foreign)

    assert rebound is not foreign
    assert rebound.simpleq is target
    assert rebound.name == "emails"
    assert rebound.dlq is True
    assert rebound.wait_seconds == 0
    assert rebound.visibility_timeout == 9


def test_simpleq_defers_transport_creation_until_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory_calls = {"count": 0}
    monkeypatch.setattr("simpleq.config._endpoint_reachable", lambda url: False)

    class StubSQSClient:
        def list_queues(self, **_: object) -> dict[str, list[str]]:
            return {"QueueUrls": ["https://sqs.aws/123/emails"]}

    class StubSession:
        def client(
            self,
            service_name: str,
            *,
            region_name: str | None = None,
            endpoint_url: str | None = None,
        ) -> StubSQSClient:
            assert service_name == "sqs"
            assert region_name == "us-east-1"
            assert endpoint_url is None
            return StubSQSClient()

    def session_factory() -> StubSession:
        session_factory_calls["count"] += 1
        return StubSession()

    simpleq = SimpleQ(session_factory=session_factory)
    assert session_factory_calls["count"] == 0
    assert simpleq.list_queues_sync() == ["emails"]
    assert session_factory_calls["count"] == 1


def test_simpleq_worker_factory() -> None:
    simpleq = SimpleQ(concurrency=4)
    worker = simpleq.worker(queues=["emails"], poll_interval=0.2)
    assert worker.concurrency == 4
    assert worker.poll_interval == 0.2
    assert worker.queues[0].name == "emails"


def test_module_entrypoint_invokes_cli_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"value": False}
    monkeypatch.setattr("simpleq.cli.main", lambda: called.__setitem__("value", True))
    runpy.run_module("simpleq.__main__", run_name="__main__")
    assert called["value"] is True
