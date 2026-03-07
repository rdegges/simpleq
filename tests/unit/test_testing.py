"""Unit tests for the in-memory testing transport."""

from __future__ import annotations

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
