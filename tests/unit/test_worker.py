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


def test_worker_rejects_invalid_runtime_options() -> None:
    simpleq = SimpleQ()
    queue = FakeQueue(simpleq=simpleq)

    with pytest.raises(ValueError, match="concurrency must be at least 1"):
        Worker(simpleq, [queue], concurrency=0)

    with pytest.raises(ValueError, match="poll_interval must be non-negative"):
        Worker(simpleq, [queue], concurrency=1, poll_interval=-0.1)


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


@pytest.mark.asyncio
async def test_worker_cancellation_does_not_mark_job_failed() -> None:
    simpleq = SimpleQ()
    definition = TaskDefinition(name=task_name_for(record_sync), func=record_sync)
    simpleq.registry.register(definition)
    queue = FakeQueue(simpleq=simpleq)
    worker = Worker(simpleq, [queue], concurrency=1)
    job = Job(
        task_name=definition.name,
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
    )

    async def cancelled_invoke(_queue: Any, _job: Job) -> None:
        raise asyncio.CancelledError()

    worker._invoke = cancelled_invoke  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await worker._process_job(queue, job, asyncio.Semaphore(1))

    assert queue.acked == []
    assert queue.visibility_changes == []
    assert queue.dlq_moves == []


@pytest.mark.asyncio
async def test_worker_processes_ready_queue_without_waiting_for_slow_queue() -> None:
    simpleq = SimpleQ()
    processed = asyncio.Event()
    definition = TaskDefinition(name=task_name_for(record_sync), func=record_sync)
    simpleq.registry.register(definition)

    class SlowQueue(FakeQueue):
        async def receive(
            self, *, max_messages: int, visibility_timeout: int
        ) -> list[Job]:
            assert max_messages
            assert visibility_timeout == self.visibility_timeout
            await asyncio.sleep(0.3)
            return []

    class ReadyQueue(FakeQueue):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._returned = False

        async def receive(
            self, *, max_messages: int, visibility_timeout: int
        ) -> list[Job]:
            assert max_messages
            assert visibility_timeout == self.visibility_timeout
            if self._returned:
                return []
            self._returned = True
            return [
                Job(
                    task_name=definition.name,
                    args=("hello",),
                    kwargs={},
                    queue_name=self.name,
                )
            ]

    slow_queue = SlowQueue(simpleq=simpleq, name="slow")
    ready_queue = ReadyQueue(simpleq=simpleq, name="ready")
    worker = Worker(simpleq, [slow_queue, ready_queue], concurrency=1, poll_interval=0)
    original_invoke = worker._invoke

    async def invoke_and_mark(queue: Any, job: Job) -> Any:
        processed.set()
        return await original_invoke(queue, job)

    worker._invoke = invoke_and_mark  # type: ignore[method-assign]

    work_task = asyncio.create_task(worker.work(burst=True))
    await asyncio.wait_for(processed.wait(), timeout=0.15)
    await work_task


@pytest.mark.asyncio
async def test_worker_survives_receive_error_and_processes_other_queues() -> None:
    simpleq = SimpleQ()
    processed = asyncio.Event()
    definition = TaskDefinition(name=task_name_for(record_sync), func=record_sync)
    simpleq.registry.register(definition)

    class FailingQueue(FakeQueue):
        async def receive(
            self, *, max_messages: int, visibility_timeout: int
        ) -> list[Job]:
            assert max_messages
            assert visibility_timeout == self.visibility_timeout
            raise RuntimeError("temporary receive failure")

    class ReadyQueue(FakeQueue):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._returned = False

        async def receive(
            self, *, max_messages: int, visibility_timeout: int
        ) -> list[Job]:
            assert max_messages
            assert visibility_timeout == self.visibility_timeout
            if self._returned:
                return []
            self._returned = True
            return [
                Job(
                    task_name=definition.name,
                    args=("hello",),
                    kwargs={},
                    queue_name=self.name,
                )
            ]

    failing_queue = FailingQueue(simpleq=simpleq, name="failing")
    ready_queue = ReadyQueue(simpleq=simpleq, name="ready")
    worker = Worker(
        simpleq,
        [failing_queue, ready_queue],
        concurrency=1,
        poll_interval=0,
    )
    original_invoke = worker._invoke

    async def invoke_and_mark(queue: Any, job: Job) -> Any:
        processed.set()
        return await original_invoke(queue, job)

    worker._invoke = invoke_and_mark  # type: ignore[method-assign]
    await asyncio.wait_for(worker.work(burst=True), timeout=0.5)
    await asyncio.wait_for(processed.wait(), timeout=0.15)
