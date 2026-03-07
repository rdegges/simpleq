"""Unit tests for worker retry and invocation logic."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from simpleq import SimpleQ
from simpleq.job import Job
from simpleq.task import TaskDefinition, task_name_for
from simpleq.worker import Worker, reconstruct_arguments
from tests.fixtures.tasks import EmailPayload, record_sync


@dataclass
class FakeQueue:
    """Small fake queue used for worker behavior tests."""

    simpleq: Any
    name: str = "emails"
    max_retries: int = 3
    visibility_timeout: int = 8
    batch_size: int = 10
    acked: list[str] = field(default_factory=list)
    visibility_changes: list[int] = field(default_factory=list)
    dlq_moves: list[str] = field(default_factory=list)

    async def receive(self, *, max_messages: int, visibility_timeout: int) -> list[Job]:
        assert max_messages
        assert visibility_timeout == self.visibility_timeout
        return []

    async def ack(self, job: Job) -> None:
        self.acked.append(job.job_id)

    async def change_visibility(self, job: Job, timeout_seconds: int) -> None:
        self.visibility_changes.append(timeout_seconds)

    async def move_to_dlq(self, job: Job, *, error: str) -> None:
        self.dlq_moves.append(error)


def test_reconstruct_arguments_for_schema() -> None:
    args, kwargs = reconstruct_arguments(
        EmailPayload,
        ({"to": "a@example.com", "subject": "Hi", "body": "B"},),
        {},
    )
    assert kwargs == {}
    assert args[0].to == "a@example.com"


@pytest.mark.asyncio
async def test_worker_handles_retry_and_dlq() -> None:
    simpleq = SimpleQ()
    definition = TaskDefinition(
        name=task_name_for(record_sync),
        func=record_sync,
        retry_exceptions=(RuntimeError,),
    )
    simpleq.registry.register(definition)
    queue = FakeQueue(simpleq=simpleq)
    worker = Worker(simpleq, [queue], concurrency=1)
    job = Job(
        task_name=definition.name,
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
        receive_count=1,
    )
    await worker._handle_failure(queue, job, RuntimeError("boom"))
    assert queue.visibility_changes == [1]

    exhausted = Job(
        task_name=definition.name,
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
        receive_count=3,
    )
    await worker._handle_failure(queue, exhausted, RuntimeError("boom"))
    assert queue.dlq_moves == ["boom"]


@pytest.mark.asyncio
async def test_worker_handles_non_retryable_failure() -> None:
    simpleq = SimpleQ()
    definition = TaskDefinition(
        name=task_name_for(record_sync),
        func=record_sync,
        retry_exceptions=(ValueError,),
    )
    simpleq.registry.register(definition)
    queue = FakeQueue(simpleq=simpleq)
    worker = Worker(simpleq, [queue], concurrency=1)
    job = Job(
        task_name=definition.name, args=("hello",), kwargs={}, queue_name=queue.name
    )
    await worker._handle_failure(queue, job, RuntimeError("boom"))
    assert len(queue.acked) == 1


def test_retry_delay_strategies() -> None:
    simpleq = SimpleQ(backoff_strategy="exponential")
    queue = FakeQueue(simpleq=simpleq)
    worker = Worker(simpleq, [queue], concurrency=1)
    assert worker._retry_delay(queue, 1) == 1
    assert worker._retry_delay(queue, 3) == 4

    linear = Worker(SimpleQ(backoff_strategy="linear"), [queue], concurrency=1)
    assert linear._retry_delay(queue, 3) == 3

    constant = Worker(SimpleQ(backoff_strategy="constant"), [queue], concurrency=1)
    assert constant._retry_delay(queue, 3) == 1


@pytest.mark.asyncio
async def test_worker_stop_sleep_sync_and_sync_invoke() -> None:
    simpleq = SimpleQ()
    definition = TaskDefinition(name=task_name_for(record_sync), func=record_sync)
    simpleq.registry.register(definition)
    queue = FakeQueue(simpleq=simpleq)
    worker = Worker(simpleq, [queue], concurrency=1, poll_interval=0.01)

    task = asyncio.create_task(worker.work())
    await asyncio.sleep(0.02)
    await worker.stop()
    await task

    worker.work_sync(burst=True)

    result = await worker._invoke(
        queue,
        Job(
            task_name=definition.name, args=("hello",), kwargs={}, queue_name=queue.name
        ),
    )
    assert result == "hello"

    with pytest.raises(ValueError):
        reconstruct_arguments(EmailPayload, (), {"bad": "shape"})
