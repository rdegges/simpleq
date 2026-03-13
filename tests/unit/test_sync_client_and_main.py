"""Unit tests for sync helpers, client helpers, and module entrypoints."""

from __future__ import annotations

import asyncio
import runpy

import pytest

from simpleq import SimpleQ
from simpleq._sync import run_sync
from simpleq.client import queue_name_from_reference
from simpleq.exceptions import QueueValidationError
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
        return ["https://sqs.aws/123/mail-events"]

    monkeypatch.setattr(simpleq.transport, "list_queues", fake_list)
    assert simpleq.list_queues_sync("mail") == ["mail-events"]
    assert simpleq.run_sync(asyncio.sleep(0, result="ok")) == "ok"
    with pytest.raises(QueueValidationError, match="queue must be a Queue instance"):
        simpleq.resolve_queue(object())


def test_simpleq_resolve_queue_rejects_invalid_reference_type() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())

    with pytest.raises(QueueValidationError, match="int"):
        simpleq.resolve_queue(123)


def test_simpleq_resolve_queue_none_supports_fifo_default_queue() -> None:
    simpleq = SimpleQ(default_queue_name="events.fifo", transport=InMemoryTransport())

    resolved = simpleq.resolve_queue(None)

    assert resolved.name == "events.fifo"
    assert resolved.fifo is True


def test_simpleq_queue_uses_client_default_max_retries() -> None:
    simpleq = SimpleQ(max_retries=7, transport=InMemoryTransport())

    assert simpleq.queue("emails").max_retries == 7


def test_simpleq_queue_rejects_conflicting_redefinition() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    original = simpleq.queue(
        "emails",
        dlq=True,
        wait_seconds=0,
        visibility_timeout=7,
        tags={"env": "test"},
    )

    with pytest.raises(QueueValidationError, match="already configured differently"):
        simpleq.queue(
            "emails",
            dlq=True,
            wait_seconds=3,
            visibility_timeout=7,
            tags={"env": "test"},
        )

    with pytest.raises(QueueValidationError, match="already configured differently"):
        simpleq.queue("emails", dlq=False)

    assert (
        simpleq.queue(
            "emails",
            dlq=True,
            wait_seconds=0,
            visibility_timeout=7,
            tags={"env": "test"},
        )
        is original
    )


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


def test_resolve_queue_rejects_conflicting_foreign_queue() -> None:
    source = SimpleQ(transport=InMemoryTransport())
    foreign = source.queue("emails", wait_seconds=0)
    target = SimpleQ(transport=InMemoryTransport())
    target.queue("emails", wait_seconds=5)

    with pytest.raises(QueueValidationError, match="already configured differently"):
        target.resolve_queue(foreign)


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
    worker = simpleq.worker(
        queues=["emails"], poll_interval=0.2, receive_timeout_seconds=2.5
    )
    assert worker.concurrency == 4
    assert worker.poll_interval == 0.2
    assert worker.receive_timeout_seconds == 2.5
    assert worker.queues[0].name == "emails"


def test_simpleq_worker_factory_uses_configured_poll_interval_by_default() -> None:
    simpleq = SimpleQ(concurrency=4, poll_interval=0.3)

    worker = simpleq.worker(queues=["emails"])

    assert worker.poll_interval == 0.3


def test_simpleq_worker_factory_uses_configured_receive_timeout_by_default() -> None:
    simpleq = SimpleQ(concurrency=4, receive_timeout_seconds=12.5)

    worker = simpleq.worker(queues=["emails"])

    assert worker.receive_timeout_seconds == 12.5


def test_simpleq_worker_factory_rejects_invalid_concurrency_override() -> None:
    simpleq = SimpleQ(concurrency=4)
    with pytest.raises(ValueError, match="concurrency must be at least 1"):
        simpleq.worker(queues=["emails"], concurrency=0)


def test_simpleq_worker_factory_rejects_empty_queues() -> None:
    simpleq = SimpleQ(concurrency=4)
    with pytest.raises(ValueError, match="at least one queue"):
        simpleq.worker(queues=[])


@pytest.mark.asyncio
async def test_simpleq_list_queues_returns_sorted_unique_queue_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())

    async def fake_list(prefix: str | None) -> list[str]:
        assert prefix == "simpleq-test-"
        return [
            "https://sqs.aws/123/simpleq-test-c",
            "https://sqs.aws/123/simpleq-test-a",
            "https://sqs.aws/123/simpleq-test-b",
            "https://sqs.aws/123/simpleq-test-a",
        ]

    monkeypatch.setattr(simpleq.transport, "list_queues", fake_list)

    queues = await simpleq.list_queues("simpleq-test-")

    assert queues == [
        "simpleq-test-a",
        "simpleq-test-b",
        "simpleq-test-c",
    ]


@pytest.mark.asyncio
async def test_simpleq_list_queues_filters_transport_results_by_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())

    async def fake_list(prefix: str | None) -> list[str]:
        assert prefix == "simpleq-test-"
        return [
            "https://sqs.aws/123/simpleq-test-a",
            "https://sqs.aws/123/other-queue",
            "https://sqs.aws/123/simpleq-test-b",
        ]

    monkeypatch.setattr(simpleq.transport, "list_queues", fake_list)

    queues = await simpleq.list_queues("simpleq-test-")

    assert queues == ["simpleq-test-a", "simpleq-test-b"]


@pytest.mark.asyncio
async def test_simpleq_list_queues_treats_blank_prefix_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())

    async def fake_list(prefix: str | None) -> list[str]:
        assert prefix is None
        return ["https://sqs.aws/123/simpleq-test-a"]

    monkeypatch.setattr(simpleq.transport, "list_queues", fake_list)

    queues = await simpleq.list_queues("   ")

    assert queues == ["simpleq-test-a"]


@pytest.mark.asyncio
async def test_simpleq_list_queues_ignores_malformed_queue_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())

    async def fake_list(prefix: str | None) -> list[str]:
        assert prefix == "simpleq-test-"
        return [
            "https://sqs.aws/123/simpleq-test-a/",
            "https://sqs.aws/123/simpleq-test-b",
            "simpleq-test-c",
            "https://sqs.aws/123/not valid",
            "gopher://sqs.aws/123/simpleq-test-z",
            "https://sqs.aws/",
            "",
            "   ",
        ]

    monkeypatch.setattr(simpleq.transport, "list_queues", fake_list)

    queues = await simpleq.list_queues("simpleq-test-")

    assert queues == [
        "simpleq-test-a",
        "simpleq-test-b",
        "simpleq-test-c",
    ]


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("https://sqs.us-east-1.amazonaws.com/123456789012/emails", "emails"),
        (
            "https://sqs.us-east-1.amazonaws.com/123456789012/orders%2Efifo",
            "orders.fifo",
        ),
        ("arn:aws:sqs:us-east-1:123456789012:emails", "emails"),
        ("arn:aws-us-gov:sqs:us-gov-west-1:123456789012:orders.fifo", "orders.fifo"),
        ("arn:aws:sqs:us-east-1:123456789012", None),
        ("simpleq-plain-name", "simpleq-plain-name"),
        ("https://sqs.aws/123/invalid name", None),
        ("arn:aws:s3:us-east-1:123456789012:emails", None),
        ("arn:aws:sqs:us-east-1:123456789012:", None),
        ("gopher://sqs.aws/123/simpleq-test-z", None),
        ("", None),
        ("   ", None),
    ],
)
def test_queue_name_from_reference_parses_and_validates(
    reference: str,
    expected: str | None,
) -> None:
    assert queue_name_from_reference(reference) == expected


def test_resolve_queue_accepts_sqs_arn_reference() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())

    resolved = simpleq.resolve_queue("arn:aws:sqs:us-east-1:123456789012:emails")

    assert resolved.name == "emails"
    assert resolved.fifo is False


def test_resolve_queue_rejects_invalid_sqs_arn_reference() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())

    with pytest.raises(
        QueueValidationError,
        match="must be a valid queue name, queue URL, or SQS queue ARN",
    ):
        simpleq.resolve_queue("arn:aws:sqs:us-east-1:123456789012:")


def test_resolve_queue_rejects_invalid_queue_url_reference() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())

    with pytest.raises(
        QueueValidationError,
        match="must be a valid queue name, queue URL, or SQS queue ARN",
    ):
        simpleq.resolve_queue("https://sqs.us-east-1.amazonaws.com/123/not valid")


def test_resolve_queue_raises_for_ambiguous_string_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    queue_a = simpleq.queue("emails")
    queue_b = simpleq.queue("notifications")

    monkeypatch.setattr(simpleq, "_configured_queues", lambda _name: [queue_a, queue_b])

    with pytest.raises(QueueValidationError, match="is ambiguous"):
        simpleq.resolve_queue("emails")


def test_module_entrypoint_invokes_cli_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"value": False}
    monkeypatch.setattr("simpleq.cli.main", lambda: called.__setitem__("value", True))
    runpy.run_module("simpleq.__main__", run_name="__main__")
    assert called["value"] is True
