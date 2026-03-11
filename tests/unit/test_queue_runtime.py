"""Additional queue behavior tests using a fake transport."""

from __future__ import annotations

from typing import Any

import pytest

from simpleq import SimpleQ
from simpleq.exceptions import QueueNotFoundError, QueueValidationError
from simpleq.job import Job
from simpleq.queue import BatchEntry


class FakeTransport:
    """Minimal transport stub for queue unit tests."""

    def __init__(self) -> None:
        self.ensured: list[tuple[str, dict[str, str], dict[str, str]]] = []
        self.deleted: list[str] = []
        self.purged: list[str] = []
        self.sent: list[dict[str, Any]] = []
        self.sent_batches: list[list[dict[str, Any]]] = []
        self.deleted_messages: list[str] = []
        self.visibility_changes: list[int] = []
        self.receive_calls: list[dict[str, Any]] = []
        self.receive_queue: list[list[dict[str, Any]]] = []
        self.queue_attributes: dict[str, dict[str, str]] = {}

    async def ensure_queue(
        self,
        name: str,
        *,
        attributes: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        self.ensured.append((name, attributes or {}, tags or {}))
        return f"https://example.com/{name}"

    async def queue_arn(self, name: str, queue_url: str) -> str:
        return f"arn:aws:sqs:us-east-1:000000000000:{name}"

    async def delete_queue(self, queue_name: str, queue_url: str) -> None:
        self.deleted.append(queue_name)

    async def purge_queue(self, queue_name: str, queue_url: str) -> None:
        self.purged.append(queue_name)

    async def send_message(self, queue_name: str, queue_url: str, **kwargs: Any) -> str:
        self.sent.append({"queue_name": queue_name, **kwargs})
        return "mid"

    async def send_message_batch(
        self, queue_name: str, queue_url: str, entries: list[dict[str, Any]]
    ) -> list[str]:
        self.sent_batches.append(entries)
        return [f"mid-{index}" for index, _entry in enumerate(entries, start=1)]

    async def receive_messages(
        self, queue_name: str, queue_url: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.receive_calls.append(kwargs)
        return self.receive_queue.pop(0) if self.receive_queue else []

    async def delete_message(
        self, queue_name: str, queue_url: str, receipt_handle: str
    ) -> None:
        self.deleted_messages.append(receipt_handle)

    async def change_message_visibility(
        self, queue_name: str, queue_url: str, receipt_handle: str, timeout_seconds: int
    ) -> None:
        self.visibility_changes.append(timeout_seconds)

    async def get_queue_attributes(
        self, queue_name: str, queue_url: str, attribute_names: list[str]
    ) -> dict[str, str]:
        if "QueueArn" in attribute_names:
            return {"QueueArn": f"arn:aws:sqs:us-east-1:000000000000:{queue_name}"}
        return self.queue_attributes.get(
            queue_name,
            {
                "ApproximateNumberOfMessages": "2",
                "ApproximateNumberOfMessagesNotVisible": "1",
                "ApproximateNumberOfMessagesDelayed": "0",
            },
        )


@pytest.mark.asyncio
async def test_queue_stats_include_dlq_depth(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", dlq=True, wait_seconds=0)
    simpleq_with_fake_transport.transport.queue_attributes = {
        queue.name: {
            "ApproximateNumberOfMessages": "2",
            "ApproximateNumberOfMessagesNotVisible": "1",
            "ApproximateNumberOfMessagesDelayed": "0",
        }
    }
    simpleq_with_fake_transport.transport.queue_attributes[queue.dlq_name] = {
        "ApproximateNumberOfMessages": "3",
        "ApproximateNumberOfMessagesNotVisible": "4",
        "ApproximateNumberOfMessagesDelayed": "5",
    }

    stats = await queue.stats()

    assert stats.available_messages == 2
    assert stats.in_flight_messages == 1
    assert stats.delayed_messages == 0
    assert stats.dlq_available_messages == 3
    assert stats.dlq_in_flight_messages == 4
    assert stats.dlq_delayed_messages == 5


@pytest.mark.asyncio
async def test_queue_stats_tolerates_malformed_attribute_values(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", dlq=True, wait_seconds=0)
    simpleq_with_fake_transport.transport.queue_attributes = {
        queue.name: {
            "ApproximateNumberOfMessages": "not-a-number",
            "ApproximateNumberOfMessagesNotVisible": "",
            "ApproximateNumberOfMessagesDelayed": "7",
        }
    }
    simpleq_with_fake_transport.transport.queue_attributes[queue.dlq_name] = {
        "ApproximateNumberOfMessages": "3x",
        "ApproximateNumberOfMessagesNotVisible": "2",
        "ApproximateNumberOfMessagesDelayed": "-",
    }

    stats = await queue.stats()

    assert stats.available_messages == 0
    assert stats.in_flight_messages == 0
    assert stats.delayed_messages == 7
    assert stats.dlq_available_messages == 0
    assert stats.dlq_in_flight_messages == 2
    assert stats.dlq_delayed_messages == 0


@pytest.mark.asyncio
async def test_queue_stats_clamps_negative_attribute_values_to_zero(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", dlq=True, wait_seconds=0)
    simpleq_with_fake_transport.transport.queue_attributes = {
        queue.name: {
            "ApproximateNumberOfMessages": "-1",
            "ApproximateNumberOfMessagesNotVisible": "-2",
            "ApproximateNumberOfMessagesDelayed": "-3",
        }
    }
    simpleq_with_fake_transport.transport.queue_attributes[queue.dlq_name] = {
        "ApproximateNumberOfMessages": "-4",
        "ApproximateNumberOfMessagesNotVisible": "5",
        "ApproximateNumberOfMessagesDelayed": "-6",
    }

    stats = await queue.stats()

    assert stats.available_messages == 0
    assert stats.in_flight_messages == 0
    assert stats.delayed_messages == 0
    assert stats.dlq_available_messages == 0
    assert stats.dlq_in_flight_messages == 5
    assert stats.dlq_delayed_messages == 0


@pytest.fixture
def simpleq_with_fake_transport() -> SimpleQ:
    simpleq = SimpleQ()
    simpleq.transport = FakeTransport()
    return simpleq


@pytest.mark.asyncio
async def test_queue_ensure_exists_delete_and_purge(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", dlq=True, wait_seconds=0)
    await queue.ensure_exists()
    await queue.ensure_exists()
    assert [
        name
        for name, _attributes, _tags in simpleq_with_fake_transport.transport.ensured
    ] == [
        "emails-dlq",
        "emails",
    ]
    await queue.purge()
    await queue.delete()
    assert simpleq_with_fake_transport.transport.purged == ["emails"]
    assert simpleq_with_fake_transport.transport.deleted == ["emails", "emails-dlq"]


@pytest.mark.asyncio
async def test_queue_enqueue_receive_and_iter_jobs(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", wait_seconds=0)
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a",),
        kwargs={},
        queue_name="emails",
    )
    await queue.enqueue(job, delay_seconds=3, attributes={"source": "tests"})
    assert simpleq_with_fake_transport.transport.sent[0]["delay_seconds"] == 3

    message = {
        "Body": job.to_message_body(),
        "ReceiptHandle": "receipt-1",
        "MessageId": "mid-1",
        "Attributes": {"ApproximateReceiveCount": "1"},
        "MessageAttributes": {},
    }
    simpleq_with_fake_transport.transport.receive_queue = [[message], []]
    received = await queue.receive(max_messages=1, wait_seconds=0)
    assert received[0].receipt_handle == "receipt-1"
    await queue.ack(received[0])
    await queue.change_visibility(received[0], 4)
    assert simpleq_with_fake_transport.transport.deleted_messages == ["receipt-1"]
    assert simpleq_with_fake_transport.transport.visibility_changes == [4]

    simpleq_with_fake_transport.transport.receive_queue = [[message], []]
    iterated = [job async for job in queue.iter_jobs(limit=1)]
    assert len(iterated) == 1


@pytest.mark.asyncio
async def test_queue_enqueue_recovers_from_stale_queue_url() -> None:
    class FlakySendTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self._failed_once = False

        async def send_message(
            self,
            queue_name: str,
            queue_url: str,
            **kwargs: Any,
        ) -> str:
            if not self._failed_once:
                self._failed_once = True
                raise QueueNotFoundError("Queue was deleted.")
            return await super().send_message(
                queue_name,
                queue_url,
                **kwargs,
            )

    simpleq = SimpleQ()
    transport = FlakySendTransport()
    simpleq.transport = transport
    queue = simpleq.queue("emails", wait_seconds=0)
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a",),
        kwargs={},
        queue_name="emails",
    )

    message_id = await queue.enqueue(job)

    assert message_id == "mid"
    assert [name for name, _attributes, _tags in transport.ensured] == [
        "emails",
        "emails",
    ]
    assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_queue_enqueue_recovers_when_transport_cache_is_stale() -> None:
    class CachedUrlTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self._valid_url = "https://example.com/emails-new"
            self._cached_url = "https://example.com/emails-stale"
            self.cache_invalidated = False

        async def ensure_queue(
            self,
            name: str,
            *,
            attributes: dict[str, str] | None = None,
            tags: dict[str, str] | None = None,
        ) -> str:
            self.ensured.append((name, attributes or {}, tags or {}))
            if self.cache_invalidated:
                return self._valid_url
            return self._cached_url

        def invalidate_queue_url(self, queue_name: str) -> None:
            if queue_name == "emails":
                self.cache_invalidated = True

        async def send_message(
            self,
            queue_name: str,
            queue_url: str,
            **kwargs: Any,
        ) -> str:
            if queue_url != self._valid_url:
                raise QueueNotFoundError("Queue was deleted.")
            return await super().send_message(
                queue_name,
                queue_url,
                **kwargs,
            )

    simpleq = SimpleQ()
    transport = CachedUrlTransport()
    simpleq.transport = transport
    queue = simpleq.queue("emails", wait_seconds=0)
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a",),
        kwargs={},
        queue_name="emails",
    )

    message_id = await queue.enqueue(job)

    assert message_id == "mid"
    assert transport.cache_invalidated is True
    assert [name for name, _attributes, _tags in transport.ensured] == [
        "emails",
        "emails",
    ]
    assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_queue_purge_recovers_from_stale_queue_url() -> None:
    class FlakyPurgeTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self._failed_once = False

        async def purge_queue(self, queue_name: str, queue_url: str) -> None:
            if not self._failed_once:
                self._failed_once = True
                raise QueueNotFoundError("Queue was deleted.")
            await super().purge_queue(queue_name, queue_url)

    simpleq = SimpleQ()
    transport = FlakyPurgeTransport()
    simpleq.transport = transport
    queue = simpleq.queue("emails", wait_seconds=0)

    await queue.purge()

    assert transport.purged == ["emails"]
    assert [name for name, _attributes, _tags in transport.ensured] == [
        "emails",
        "emails",
    ]


@pytest.mark.asyncio
async def test_queue_stats_recovers_from_stale_queue_url() -> None:
    class FlakyStatsTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self._failed_once = False

        async def get_queue_attributes(
            self, queue_name: str, queue_url: str, attribute_names: list[str]
        ) -> dict[str, str]:
            if not self._failed_once and "QueueArn" not in attribute_names:
                self._failed_once = True
                raise QueueNotFoundError("Queue was deleted.")
            return await super().get_queue_attributes(
                queue_name,
                queue_url,
                attribute_names,
            )

    simpleq = SimpleQ()
    transport = FlakyStatsTransport()
    simpleq.transport = transport
    queue = simpleq.queue("emails", wait_seconds=0)

    stats = await queue.stats()

    assert stats.available_messages == 2
    assert stats.in_flight_messages == 1
    assert stats.delayed_messages == 0
    assert [name for name, _attributes, _tags in transport.ensured] == [
        "emails",
        "emails",
    ]


@pytest.mark.asyncio
async def test_queue_receive_skips_and_deletes_malformed_messages(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", wait_seconds=0)
    valid_job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a",),
        kwargs={},
        queue_name="emails",
    )
    malformed_message = {
        "Body": "{not-json",
        "ReceiptHandle": "receipt-bad",
        "MessageId": "mid-bad",
        "Attributes": {"ApproximateReceiveCount": "1"},
        "MessageAttributes": {},
    }
    valid_message = {
        "Body": valid_job.to_message_body(),
        "ReceiptHandle": "receipt-good",
        "MessageId": "mid-good",
        "Attributes": {"ApproximateReceiveCount": "1"},
        "MessageAttributes": {},
    }
    simpleq_with_fake_transport.transport.receive_queue = [
        [malformed_message, valid_message]
    ]

    received = await queue.receive(max_messages=2, wait_seconds=0)

    assert [job.message_id for job in received] == ["mid-good"]
    assert simpleq_with_fake_transport.transport.deleted_messages == ["receipt-bad"]
    assert (
        simpleq_with_fake_transport.cost_tracker.metrics_for(
            "emails"
        ).jobs_decode_failed
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_seconds", [-1, 43_201])
async def test_queue_change_visibility_rejects_invalid_timeout(
    simpleq_with_fake_transport: SimpleQ,
    timeout_seconds: int,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", wait_seconds=0)
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a",),
        kwargs={},
        queue_name="emails",
        receipt_handle="receipt-1",
    )

    with pytest.raises(
        QueueValidationError,
        match="visibility_timeout must be between 0 and 43200",
    ):
        await queue.change_visibility(job, timeout_seconds)

    assert simpleq_with_fake_transport.transport.visibility_changes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"max_messages": 0}, "max_messages must be between 1 and 10"),
        ({"max_messages": 11}, "max_messages must be between 1 and 10"),
        ({"wait_seconds": -1}, "wait_seconds must be between 0 and 20"),
        ({"wait_seconds": 21}, "wait_seconds must be between 0 and 20"),
        (
            {"visibility_timeout": -1},
            "visibility_timeout must be between 0 and 43200",
        ),
        (
            {"visibility_timeout": 43_201},
            "visibility_timeout must be between 0 and 43200",
        ),
    ],
)
async def test_queue_receive_rejects_invalid_options(
    simpleq_with_fake_transport: SimpleQ,
    kwargs: dict[str, int],
    match: str,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails")
    with pytest.raises(QueueValidationError, match=match):
        await queue.receive(**kwargs)


@pytest.mark.asyncio
async def test_queue_batch_dlq_and_misc_branches(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", dlq=True, wait_seconds=0)
    base_job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a",),
        kwargs={},
        queue_name="emails",
    )
    await queue.enqueue_many([])
    await queue.enqueue_many(
        [
            BatchEntry(
                base_job,
                delay_seconds=1,
                attributes={"source": "tests"},
            )
        ]
    )
    assert len(simpleq_with_fake_transport.transport.sent_batches) == 1

    simpleq_with_fake_transport.transport.receive_queue = [
        [
            {
                "Body": base_job.with_attempt(2, error="boom").to_message_body(),
                "ReceiptHandle": "receipt-dlq",
                "MessageId": "mid-dlq",
                "Attributes": {"ApproximateReceiveCount": "2"},
                "MessageAttributes": {},
            }
        ],
        [],
    ]
    dlq_jobs = [job async for job in queue.get_dlq_jobs(limit=1)]
    assert len(dlq_jobs) == 1

    simpleq_with_fake_transport.transport.receive_queue = [
        [
            {
                "Body": base_job.with_attempt(2, error="boom").to_message_body(),
                "ReceiptHandle": "receipt-redrive",
                "MessageId": "mid-redrive",
                "Attributes": {"ApproximateReceiveCount": "1"},
                "MessageAttributes": {},
            }
        ],
        [],
    ]
    simpleq_with_fake_transport.transport.receive_calls.clear()
    assert await queue.redrive_dlq_jobs() == 1
    assert (
        simpleq_with_fake_transport.transport.receive_calls[0]["visibility_timeout"]
        == 1
    )
    assert "receipt-redrive" in simpleq_with_fake_transport.transport.deleted_messages

    no_dlq = simpleq_with_fake_transport.queue("plain", wait_seconds=0)
    with pytest.raises(QueueValidationError):
        [job async for job in no_dlq.get_dlq_jobs(limit=1)]
    with pytest.raises(QueueValidationError):
        await no_dlq.redrive_dlq_jobs()

    job_without_receipt = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a",),
        kwargs={},
        queue_name="plain",
    )
    await no_dlq.ack(job_without_receipt)
    await no_dlq.change_visibility(job_without_receipt, 0)
    await no_dlq.move_to_dlq(job_without_receipt, error="no-dlq")
    assert (
        simpleq_with_fake_transport.transport.deleted_messages.count("receipt-redrive")
        == 1
    )

    assert await queue.stats() == queue.stats_sync()
    assert (
        queue._create_queue_attributes(
            fifo=True, content_based_deduplication=False, dlq_arn="arn"
        )["FifoQueue"]
        == "true"
    )
    assert (
        queue._create_queue_attributes(
            fifo=False,
            content_based_deduplication=False,
        )["MaximumMessageSize"]
        == "1048576"
    )
    assert queue._create_queue_attributes(
        fifo=False, content_based_deduplication=False
    )["VisibilityTimeout"] == str(queue.visibility_timeout)
    assert queue.batch_size == simpleq_with_fake_transport.config.batch_size
    assert repr(queue)
    assert queue.ensure_exists_sync().endswith(queue.name)
    queue.delete_sync()
    queue.purge_sync()
    assert queue.dlq_name == "emails-dlq"


@pytest.mark.asyncio
async def test_fifo_dlq_and_redrive_preserve_group_and_rotate_deduplication_id(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue(
        "orders.fifo",
        fifo=True,
        dlq=True,
        content_based_deduplication=False,
        wait_seconds=0,
    )
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("order-1",),
        kwargs={},
        queue_name=queue.name,
    )

    await queue.enqueue(
        job,
        message_group_id="customer-1",
        deduplication_id="dedup-order-1",
    )

    sent_payload = Job.from_message_body(
        simpleq_with_fake_transport.transport.sent[-1]["message_body"]
    )
    assert sent_payload.metadata["message_group_id"] == "customer-1"
    assert sent_payload.metadata["deduplication_id"] == "dedup-order-1"

    received_job = Job.from_message_body(
        simpleq_with_fake_transport.transport.sent[-1]["message_body"],
        receipt_handle="receipt-main",
        message_id="mid-main",
    )

    await queue.move_to_dlq(received_job, error="boom")
    dlq_send = simpleq_with_fake_transport.transport.sent[-1]
    assert dlq_send["queue_name"] == "orders-dlq.fifo"
    assert dlq_send["message_group_id"] == "customer-1"
    assert dlq_send["deduplication_id"] != "dedup-order-1"
    assert dlq_send["deduplication_id"] is not None
    dlq_payload = Job.from_message_body(dlq_send["message_body"])
    assert dlq_payload.metadata["message_group_id"] == "customer-1"
    assert dlq_payload.metadata["deduplication_id"] == dlq_send["deduplication_id"]

    simpleq_with_fake_transport.transport.receive_queue = [
        [
            {
                "Body": dlq_send["message_body"],
                "ReceiptHandle": "receipt-dlq",
                "MessageId": "mid-dlq",
                "Attributes": {"ApproximateReceiveCount": "1"},
                "MessageAttributes": {},
            }
        ],
        [],
    ]

    simpleq_with_fake_transport.transport.receive_calls.clear()
    assert await queue.redrive_dlq_jobs(limit=1) == 1
    assert (
        simpleq_with_fake_transport.transport.receive_calls[0]["visibility_timeout"]
        == 1
    )
    redrive_send = simpleq_with_fake_transport.transport.sent[-1]
    assert redrive_send["queue_name"] == queue.name
    assert redrive_send["message_group_id"] == "customer-1"
    assert redrive_send["deduplication_id"] not in {
        "dedup-order-1",
        dlq_send["deduplication_id"],
    }
    redrive_payload = Job.from_message_body(redrive_send["message_body"])
    assert redrive_payload.metadata["message_group_id"] == "customer-1"
    assert (
        redrive_payload.metadata["deduplication_id"] == redrive_send["deduplication_id"]
    )
    assert "receipt-dlq" in simpleq_with_fake_transport.transport.deleted_messages


@pytest.mark.asyncio
async def test_fifo_content_based_dlq_and_redrive_rotate_deduplication_id(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue(
        "orders-content.fifo",
        fifo=True,
        dlq=True,
        content_based_deduplication=True,
        wait_seconds=0,
    )
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("order-1",),
        kwargs={},
        queue_name=queue.name,
        metadata={
            "message_group_id": "customer-1",
            "_simpleq_message_group_id": "customer-1",
            "deduplication_id": "sqs-original-dedup-id",
            "_simpleq_deduplication_id": "sqs-original-dedup-id",
        },
    )

    await queue.move_to_dlq(job, error="boom")
    dlq_send = simpleq_with_fake_transport.transport.sent[-1]
    assert dlq_send["queue_name"] == "orders-content-dlq.fifo"
    assert dlq_send["message_group_id"] == "customer-1"
    assert dlq_send["deduplication_id"] not in {None, "sqs-original-dedup-id"}

    simpleq_with_fake_transport.transport.receive_queue = [
        [
            {
                "Body": dlq_send["message_body"],
                "ReceiptHandle": "receipt-content-dlq",
                "MessageId": "mid-content-dlq",
                "Attributes": {"ApproximateReceiveCount": "1"},
                "MessageAttributes": {},
            }
        ],
        [],
    ]

    assert await queue.redrive_dlq_jobs(limit=1) == 1
    redrive_send = simpleq_with_fake_transport.transport.sent[-1]
    assert redrive_send["queue_name"] == queue.name
    assert redrive_send["message_group_id"] == "customer-1"
    assert redrive_send["deduplication_id"] not in {
        "sqs-original-dedup-id",
        dlq_send["deduplication_id"],
    }
    assert (
        "receipt-content-dlq" in simpleq_with_fake_transport.transport.deleted_messages
    )


def test_queue_string_metadata_and_validation(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    from simpleq.queue import string_metadata

    queue = simpleq_with_fake_transport.queue("emails")
    with pytest.raises(QueueValidationError):
        queue._validate_message_options(
            delay_seconds=-1, message_group_id=None, deduplication_id=None
        )
    assert string_metadata(None) is None
    assert string_metadata(123) == "123"


@pytest.mark.asyncio
async def test_get_dlq_jobs_ignores_visibility_reset_errors_after_yield(
    simpleq_with_fake_transport: SimpleQ,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", dlq=True, wait_seconds=0)
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a",),
        kwargs={},
        queue_name="emails",
    )
    message = {
        "Body": job.to_message_body(),
        "ReceiptHandle": "receipt-dlq",
        "MessageId": "mid-dlq",
        "Attributes": {"ApproximateReceiveCount": "1"},
        "MessageAttributes": {},
    }
    simpleq_with_fake_transport.transport.receive_queue = [[message], []]

    original_change_visibility = (
        simpleq_with_fake_transport.transport.change_message_visibility
    )

    async def flaky_change_visibility(
        queue_name: str,
        queue_url: str,
        receipt_handle: str,
        timeout_seconds: int,
    ) -> None:
        if timeout_seconds == 0:
            raise RuntimeError("message no longer available")
        await original_change_visibility(
            queue_name, queue_url, receipt_handle, timeout_seconds
        )

    simpleq_with_fake_transport.transport.change_message_visibility = (
        flaky_change_visibility
    )

    jobs = [received async for received in queue.get_dlq_jobs(limit=1)]
    assert len(jobs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_iter_jobs_rejects_non_positive_limit(
    simpleq_with_fake_transport: SimpleQ,
    limit: int,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", wait_seconds=0)

    with pytest.raises(QueueValidationError, match="limit must be at least 1"):
        [job async for job in queue.iter_jobs(limit=limit)]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_get_dlq_jobs_rejects_non_positive_limit(
    simpleq_with_fake_transport: SimpleQ,
    limit: int,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", dlq=True, wait_seconds=0)

    with pytest.raises(QueueValidationError, match="limit must be at least 1"):
        [job async for job in queue.get_dlq_jobs(limit=limit)]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_redrive_dlq_jobs_rejects_non_positive_limit(
    simpleq_with_fake_transport: SimpleQ,
    limit: int,
) -> None:
    queue = simpleq_with_fake_transport.queue("emails", dlq=True, wait_seconds=0)

    with pytest.raises(QueueValidationError, match="limit must be at least 1"):
        await queue.redrive_dlq_jobs(limit=limit)
