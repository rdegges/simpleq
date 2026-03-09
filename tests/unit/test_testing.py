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
