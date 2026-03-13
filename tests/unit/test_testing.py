"""Unit tests for the in-memory testing transport."""

from __future__ import annotations

import time

import pytest

from simpleq import SimpleQ
from simpleq.job import Job
from simpleq.testing import InMemoryTransport


@pytest.mark.asyncio
async def test_inmemory_transport_queue_round_trip() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    queue = simpleq.queue("emails", dlq=True, wait_seconds=0)
    await queue.ensure_exists()

    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
    )
    message_id = await queue.enqueue(job, attributes={"source": "tests"})
    assert message_id

    received = await queue.receive(max_messages=1, wait_seconds=0)
    assert len(received) == 1
    assert received[0].args == ("hello",)
    assert received[0].message_attributes == {"source": "tests"}

    stats = await queue.stats()
    assert stats.in_flight_messages == 1

    await queue.ack(received[0])
    assert (await queue.stats()).available_messages == 0


@pytest.mark.asyncio
async def test_inmemory_transport_lists_and_purges_queues() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    queue = simpleq.queue("emails", wait_seconds=0)
    await queue.ensure_exists()
    await queue.enqueue(
        Job(
            task_name="tests.fixtures.tasks:record_sync",
            args=("hello",),
            kwargs={},
            queue_name=queue.name,
        )
    )
    assert simpleq.list_queues_sync() == ["emails"]
    await queue.purge()
    assert (await queue.stats()).available_messages == 0


@pytest.mark.asyncio
async def test_inmemory_transport_fifo_deduplicates_same_deduplication_id() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    queue = simpleq.queue(
        "orders.fifo",
        fifo=True,
        wait_seconds=0,
        content_based_deduplication=False,
    )
    await queue.ensure_exists()

    first = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("order-1",),
        kwargs={},
        queue_name=queue.name,
    )
    second = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("order-2",),
        kwargs={},
        queue_name=queue.name,
    )
    first_id = await queue.enqueue(
        first,
        message_group_id="customer-1",
        deduplication_id="order-1",
    )
    second_id = await queue.enqueue(
        second,
        message_group_id="customer-1",
        deduplication_id="order-1",
    )

    assert second_id == first_id
    received = await queue.receive(max_messages=10, wait_seconds=0)
    assert [job.args[0] for job in received] == ["order-1"]


@pytest.mark.asyncio
async def test_inmemory_transport_fifo_content_based_deduplication() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    queue = simpleq.queue(
        "events.fifo",
        fifo=True,
        wait_seconds=0,
        content_based_deduplication=True,
    )
    await queue.ensure_exists()

    payload = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("same-body",),
        kwargs={},
        queue_name=queue.name,
    )
    first_id = await queue.enqueue(payload, message_group_id="group-1")
    second_id = await queue.enqueue(payload, message_group_id="group-1")

    assert second_id == first_id
    received = await queue.receive(max_messages=10, wait_seconds=0)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_inmemory_transport_fifo_blocks_later_messages_in_same_group() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    queue = simpleq.queue(
        "orders.fifo",
        fifo=True,
        wait_seconds=0,
        content_based_deduplication=False,
    )
    await queue.ensure_exists()

    for value in ("order-1", "order-2"):
        await queue.enqueue(
            Job(
                task_name="tests.fixtures.tasks:record_sync",
                args=(value,),
                kwargs={},
                queue_name=queue.name,
            ),
            message_group_id="customer-1",
            deduplication_id=value,
        )

    first_batch = await queue.receive(max_messages=1, wait_seconds=0)
    assert [job.args[0] for job in first_batch] == ["order-1"]

    blocked_batch = await queue.receive(max_messages=1, wait_seconds=0)
    assert blocked_batch == []

    await queue.ack(first_batch[0])

    second_batch = await queue.receive(max_messages=1, wait_seconds=0)
    assert [job.args[0] for job in second_batch] == ["order-2"]


@pytest.mark.asyncio
async def test_inmemory_transport_long_poll_waits_for_delayed_message() -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    queue = simpleq.queue("emails", wait_seconds=0)
    await queue.ensure_exists()

    await queue.enqueue(
        Job(
            task_name="tests.fixtures.tasks:record_sync",
            args=("delayed",),
            kwargs={},
            queue_name=queue.name,
        ),
        delay_seconds=1,
    )

    start = time.monotonic()
    received = await queue.receive(max_messages=1, wait_seconds=2)
    elapsed = time.monotonic() - start

    assert [job.args[0] for job in received] == ["delayed"]
    assert elapsed >= 0.8


@pytest.mark.asyncio
async def test_inmemory_transport_fifo_receive_request_attempt_id_replays_same_message() -> (
    None
):
    simpleq = SimpleQ(transport=InMemoryTransport())
    queue = simpleq.queue(
        "attempts.fifo",
        fifo=True,
        wait_seconds=0,
        content_based_deduplication=False,
    )
    await queue.ensure_exists()

    for value in ("first", "second"):
        await queue.enqueue(
            Job(
                task_name="tests.fixtures.tasks:record_sync",
                args=(value,),
                kwargs={},
                queue_name=queue.name,
            ),
            message_group_id="group-1",
            deduplication_id=f"dedup-{value}",
        )

    first_receive = await queue.receive(
        max_messages=1,
        wait_seconds=0,
        receive_request_attempt_id="attempt-1",
    )
    second_receive = await queue.receive(
        max_messages=1,
        wait_seconds=0,
        receive_request_attempt_id="attempt-1",
    )

    assert len(first_receive) == 1
    assert len(second_receive) == 1
    assert first_receive[0].job_id == second_receive[0].job_id
    assert first_receive[0].receipt_handle == second_receive[0].receipt_handle

    await queue.ack(first_receive[0])
    next_message = await queue.receive(max_messages=1, wait_seconds=0)
    assert [job.args[0] for job in next_message] == ["second"]


@pytest.mark.asyncio
async def test_inmemory_transport_fifo_receive_request_attempt_id_cache_invalidated_after_ack() -> (
    None
):
    simpleq = SimpleQ(transport=InMemoryTransport())
    queue = simpleq.queue(
        "attempts-ack.fifo",
        fifo=True,
        wait_seconds=0,
        content_based_deduplication=False,
    )
    await queue.ensure_exists()

    for value in ("first", "second"):
        await queue.enqueue(
            Job(
                task_name="tests.fixtures.tasks:record_sync",
                args=(value,),
                kwargs={},
                queue_name=queue.name,
            ),
            message_group_id="group-1",
            deduplication_id=f"dedup-{value}",
        )

    first_receive = await queue.receive(
        max_messages=1,
        wait_seconds=0,
        receive_request_attempt_id="attempt-1",
    )
    assert [job.args[0] for job in first_receive] == ["first"]

    await queue.ack(first_receive[0])

    replay_after_ack = await queue.receive(
        max_messages=1,
        wait_seconds=0,
        receive_request_attempt_id="attempt-1",
    )
    assert [job.args[0] for job in replay_after_ack] == ["second"]


@pytest.mark.asyncio
async def test_inmemory_transport_management_helpers() -> None:
    transport = InMemoryTransport()
    assert await transport.get_queue_url("emails") is None

    queue_url = await transport.create_queue(
        "emails",
        attributes={"VisibilityTimeout": "5"},
        tags={"env": "test"},
    )
    assert queue_url == "https://simpleq.test/emails"
    assert await transport.get_queue_url("emails") == queue_url
    assert (await transport.queue_arn("emails", queue_url)).endswith(":emails")

    await transport.set_queue_attributes(
        "emails",
        queue_url,
        {"DelaySeconds": "2"},
    )
    await transport.tag_queue("emails", queue_url, {"team": "backend"})
    await transport.untag_queue("emails", queue_url, ["env"])
    assert await transport.list_queue_tags("emails", queue_url) == {"team": "backend"}

    await transport.send_message("emails", queue_url, message_body="visible")
    await transport.send_message(
        "emails",
        queue_url,
        message_body="delayed",
        delay_seconds=60,
    )
    await transport.receive_messages(
        "emails",
        queue_url,
        max_messages=1,
        wait_seconds=0,
        visibility_timeout=None,
    )

    attributes = await transport.get_queue_attributes(
        "emails",
        queue_url,
        [
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesDelayed",
            "ApproximateNumberOfMessagesNotVisible",
            "QueueArn",
            "DelaySeconds",
        ],
    )
    assert attributes["ApproximateNumberOfMessages"] == "0"
    assert attributes["ApproximateNumberOfMessagesDelayed"] == "1"
    assert attributes["ApproximateNumberOfMessagesNotVisible"] == "1"
    assert attributes["DelaySeconds"] == "2"
    assert attributes["QueueArn"].endswith(":emails")
    assert await transport.list_queues(prefix="em") == [queue_url]

    await transport.delete_queue("emails", queue_url)
    assert await transport.get_queue_url("emails") is None


@pytest.mark.asyncio
async def test_inmemory_transport_send_message_batch_and_change_visibility() -> None:
    transport = InMemoryTransport()
    queue_url = await transport.ensure_queue(
        "emails",
        attributes={"VisibilityTimeout": "30"},
    )

    message_ids = await transport.send_message_batch(
        "emails",
        queue_url,
        [
            {"MessageBody": "first"},
            {
                "MessageBody": "second",
                "MessageAttributes": {
                    "source": {"DataType": "String", "StringValue": "tests"}
                },
            },
        ],
    )
    assert len(message_ids) == 2

    first_batch = await transport.receive_messages(
        "emails",
        queue_url,
        max_messages=1,
        wait_seconds=0,
        visibility_timeout=10,
    )
    await transport.change_message_visibility(
        "emails",
        queue_url,
        first_batch[0]["ReceiptHandle"],
        0,
    )

    second_batch = await transport.receive_messages(
        "emails",
        queue_url,
        max_messages=2,
        wait_seconds=0,
        visibility_timeout=0,
    )
    assert len(second_batch) == 2


@pytest.mark.asyncio
async def test_inmemory_transport_missing_queue_raises_keyerror() -> None:
    transport = InMemoryTransport()

    with pytest.raises(KeyError, match="Queue 'missing' is not defined."):
        await transport.list_queue_tags("missing", "https://simpleq.test/missing")


@pytest.mark.asyncio
async def test_inmemory_transport_fifo_without_deduplication_keeps_duplicates() -> None:
    transport = InMemoryTransport()
    queue_url = await transport.ensure_queue(
        "orders.fifo",
        attributes={"FifoQueue": "true"},
    )

    first = await transport.send_message(
        "orders.fifo",
        queue_url,
        message_body="same-body",
        message_group_id="group-1",
    )
    second = await transport.send_message(
        "orders.fifo",
        queue_url,
        message_body="same-body",
        message_group_id="group-1",
    )

    assert first != second
