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
    wait_seconds: int = 0
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

    with pytest.raises(ValueError, match="at least one queue"):
        Worker(simpleq, [], concurrency=1)

    with pytest.raises(ValueError, match="concurrency must be at least 1"):
        Worker(simpleq, [queue], concurrency=0)

    with pytest.raises(ValueError, match="poll_interval must be non-negative"):
        Worker(simpleq, [queue], concurrency=1, poll_interval=-0.1)

    with pytest.raises(
        ValueError, match="receive_timeout_seconds must be greater than 0"
    ):
        Worker(simpleq, [queue], concurrency=1, receive_timeout_seconds=0)


def test_worker_rejects_non_strict_numeric_runtime_types() -> None:
    simpleq = SimpleQ()
    queue = FakeQueue(simpleq=simpleq)

    with pytest.raises(ValueError, match="concurrency must be an integer"):
        Worker(simpleq, [queue], concurrency=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="concurrency must be an integer"):
        Worker(simpleq, [queue], concurrency=1.5)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="poll_interval must be a number"):
        Worker(simpleq, [queue], concurrency=1, poll_interval="0.1")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="poll_interval must be a number"):
        Worker(simpleq, [queue], concurrency=1, poll_interval=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="receive_timeout_seconds must be a number"):
        Worker(
            simpleq,
            [queue],
            concurrency=1,
            receive_timeout_seconds="2",  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="receive_timeout_seconds must be a number"):
        Worker(
            simpleq,
            [queue],
            concurrency=1,
            receive_timeout_seconds=True,  # type: ignore[arg-type]
        )


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
    retry_delay_samples = simpleq.metrics.retry_delay_seconds.collect()[0].samples
    retry_count_samples = [
        sample
        for sample in retry_delay_samples
        if sample.name == "simpleq_retry_delay_seconds_count"
        and sample.labels.get("queue") == queue.name
        and sample.labels.get("strategy") == "exponential"
    ]
    assert len(retry_count_samples) == 1
    assert retry_count_samples[0].value == 1

    exhausted = Job(
        task_name=definition.name,
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
        receive_count=3,
    )
    await worker._handle_failure(queue, exhausted, RuntimeError("boom"))
    assert queue.dlq_moves == ["boom"]
    assert simpleq.cost_tracker.metrics_for(queue.name).jobs_retried == 1


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


@pytest.mark.asyncio
async def test_worker_does_not_crash_when_failure_handler_raises() -> None:
    simpleq = SimpleQ()
    definition = TaskDefinition(
        name=task_name_for(record_sync),
        func=record_sync,
        retry_exceptions=(RuntimeError,),
    )
    simpleq.registry.register(definition)

    class BrokenRetryQueue(FakeQueue):
        async def change_visibility(self, job: Job, timeout_seconds: int) -> None:
            raise RuntimeError("change_visibility failed")

    queue = BrokenRetryQueue(simpleq=simpleq)
    worker = Worker(simpleq, [queue], concurrency=1)
    job = Job(
        task_name=definition.name,
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
    )

    async def fail_invoke(_queue: Any, _job: Job) -> None:
        raise RuntimeError("task execution failed")

    worker._invoke = fail_invoke  # type: ignore[method-assign]

    await worker._process_job(queue, job, asyncio.Semaphore(1))

    assert queue.acked == []
    assert queue.dlq_moves == []
    processed_samples = simpleq.metrics.jobs_processed.collect()[0].samples
    assert any(
        sample.labels.get("status") == "failure_handler_error"
        for sample in processed_samples
    )


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


def test_retry_delay_exponential_jitter_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = FakeQueue(simpleq=SimpleQ(), visibility_timeout=8)
    jittered = Worker(
        SimpleQ(backoff_strategy="exponential_jitter"),
        [queue],
        concurrency=1,
    )
    calls: list[tuple[int, int]] = []

    def fake_randint(start: int, end: int) -> int:
        calls.append((start, end))
        return end

    monkeypatch.setattr("simpleq.worker.random.randint", fake_randint)

    assert jittered._retry_delay(queue, 3) == 4
    assert calls == [(1, 4)]


def test_retry_delay_exponential_jitter_uses_configured_jitter_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = FakeQueue(simpleq=SimpleQ(), visibility_timeout=8)
    jittered = Worker(
        SimpleQ(backoff_strategy="exponential_jitter", retry_jitter_min_seconds=3),
        [queue],
        concurrency=1,
    )
    calls: list[tuple[int, int]] = []

    def fake_randint(start: int, end: int) -> int:
        calls.append((start, end))
        return start

    monkeypatch.setattr("simpleq.worker.random.randint", fake_randint)

    assert jittered._retry_delay(queue, 3) == 3
    assert calls == [(3, 4)]


def test_retry_delay_exponential_jitter_caps_jitter_floor_to_visibility_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = FakeQueue(simpleq=SimpleQ(), visibility_timeout=2)
    jittered = Worker(
        SimpleQ(backoff_strategy="exponential_jitter", retry_jitter_min_seconds=5),
        [queue],
        concurrency=1,
    )
    calls: list[tuple[int, int]] = []

    def fake_randint(start: int, end: int) -> int:
        calls.append((start, end))
        return end

    monkeypatch.setattr("simpleq.worker.random.randint", fake_randint)

    assert jittered._retry_delay(queue, 2) == 2
    assert calls == [(2, 2)]


def test_retry_delay_exponential_jitter_uses_minimum_delay_of_one_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = FakeQueue(simpleq=SimpleQ(), visibility_timeout=1)
    jittered = Worker(
        SimpleQ(backoff_strategy="exponential_jitter"),
        [queue],
        concurrency=1,
    )
    calls: list[tuple[int, int]] = []

    def fake_randint(start: int, end: int) -> int:
        calls.append((start, end))
        return start

    monkeypatch.setattr("simpleq.worker.random.randint", fake_randint)

    assert jittered._retry_delay(queue, 1) == 1
    assert calls == [(1, 1)]


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
async def test_worker_task_cancelled_error_is_treated_as_failure() -> None:
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

    await worker._process_job(queue, job, asyncio.Semaphore(1))

    assert queue.acked == []
    assert queue.visibility_changes == [1]
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


@pytest.mark.asyncio
async def test_worker_ignores_heartbeat_task_failures() -> None:
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

    async def invoke_slowly(_queue: Any, _job: Job) -> None:
        await asyncio.sleep(0.02)

    def failing_heartbeat(_queue: Any, _job: Job) -> asyncio.Task[None]:
        async def crash() -> None:
            await asyncio.sleep(0)
            raise RuntimeError("heartbeat failed")

        return asyncio.create_task(crash())

    worker._invoke = invoke_slowly  # type: ignore[method-assign]
    worker._heartbeat = failing_heartbeat  # type: ignore[method-assign]

    await worker._process_job(queue, job, asyncio.Semaphore(1))
    assert queue.acked == [job.job_id]


@pytest.mark.asyncio
async def test_worker_handles_unresolvable_task_without_crashing() -> None:
    simpleq = SimpleQ()
    queue = FakeQueue(simpleq=simpleq)
    queue.dlq = True
    worker = Worker(simpleq, [queue], concurrency=1)
    job = Job(
        task_name="simpleq.no_such_module:no_such_task",
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
    )

    await worker._process_job(queue, job, asyncio.Semaphore(1))

    assert queue.acked == []
    assert queue.visibility_changes == []
    assert len(queue.dlq_moves) == 1
    assert "task-definition-resolution-failed" in queue.dlq_moves[0]


@pytest.mark.asyncio
async def test_worker_does_not_crash_when_ack_fails_after_success() -> None:
    simpleq = SimpleQ()
    definition = TaskDefinition(name=task_name_for(record_sync), func=record_sync)
    simpleq.registry.register(definition)

    class AckFailQueue(FakeQueue):
        async def ack(self, job: Job) -> None:
            raise RuntimeError("ack failed")

    queue = AckFailQueue(simpleq=simpleq)
    worker = Worker(simpleq, [queue], concurrency=1)
    job = Job(
        task_name=definition.name,
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
    )

    await worker._process_job(queue, job, asyncio.Semaphore(1))

    processed_samples = simpleq.metrics.jobs_processed.collect()[0].samples
    ack_error_samples = [
        sample
        for sample in processed_samples
        if sample.name == "simpleq_jobs_processed_total"
        and sample.labels.get("queue") == queue.name
        and sample.labels.get("status") == "ack_error"
    ]
    success_samples = [
        sample
        for sample in processed_samples
        if sample.name == "simpleq_jobs_processed_total"
        and sample.labels.get("queue") == queue.name
        and sample.labels.get("status") == "success"
    ]

    assert len(ack_error_samples) == 1
    assert ack_error_samples[0].value == 1
    assert not success_samples


@pytest.mark.asyncio
async def test_worker_receive_timeout_returns_empty_batch() -> None:
    simpleq = SimpleQ()

    class HungQueue(FakeQueue):
        async def receive(
            self, *, max_messages: int, visibility_timeout: int
        ) -> list[Job]:
            assert max_messages
            assert visibility_timeout == self.visibility_timeout
            await asyncio.sleep(1)
            return []

    queue = HungQueue(simpleq=simpleq)
    worker = Worker(simpleq, [queue], concurrency=1, receive_timeout_seconds=0.01)

    received_queue, jobs = await worker._receive(queue)

    assert received_queue is queue
    assert jobs == []


@pytest.mark.asyncio
async def test_worker_receive_timeout_does_not_block_ready_queue() -> None:
    simpleq = SimpleQ()
    processed = asyncio.Event()
    definition = TaskDefinition(name=task_name_for(record_sync), func=record_sync)
    simpleq.registry.register(definition)

    class HungQueue(FakeQueue):
        async def receive(
            self, *, max_messages: int, visibility_timeout: int
        ) -> list[Job]:
            assert max_messages
            assert visibility_timeout == self.visibility_timeout
            await asyncio.sleep(1)
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

    hung_queue = HungQueue(simpleq=simpleq, name="hung", wait_seconds=20)
    ready_queue = ReadyQueue(simpleq=simpleq, name="ready")
    worker = Worker(
        simpleq,
        [hung_queue, ready_queue],
        concurrency=1,
        poll_interval=0,
        receive_timeout_seconds=0.01,
    )
    original_invoke = worker._invoke

    async def invoke_and_mark(queue: Any, job: Job) -> Any:
        processed.set()
        return await original_invoke(queue, job)

    worker._invoke = invoke_and_mark  # type: ignore[method-assign]

    work_task = asyncio.create_task(worker.work())
    await asyncio.wait_for(processed.wait(), timeout=0.2)
    await worker.stop()
    await asyncio.wait_for(work_task, timeout=0.5)


@pytest.mark.asyncio
async def test_worker_stop_cancels_in_flight_receive_tasks() -> None:
    simpleq = SimpleQ()

    class BlockingQueue(FakeQueue):
        async def receive(
            self, *, max_messages: int, visibility_timeout: int
        ) -> list[Job]:
            assert max_messages
            assert visibility_timeout == self.visibility_timeout
            await asyncio.Event().wait()
            return []

    queue = BlockingQueue(simpleq=simpleq, wait_seconds=20)
    worker = Worker(simpleq, [queue], concurrency=1, poll_interval=0)

    work_task = asyncio.create_task(worker.work())
    await asyncio.sleep(0.02)
    await worker.stop()
    await asyncio.wait_for(work_task, timeout=0.2)


@pytest.mark.asyncio
async def test_worker_receive_uses_minimum_visibility_timeout_of_one_second() -> None:
    simpleq = SimpleQ()

    class ZeroVisibilityQueue(FakeQueue):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.visibility_timeout = 0
            self.received_visibility_timeouts: list[int] = []

        async def receive(
            self, *, max_messages: int, visibility_timeout: int
        ) -> list[Job]:
            assert max_messages
            self.received_visibility_timeouts.append(visibility_timeout)
            return []

    queue = ZeroVisibilityQueue(simpleq=simpleq)
    worker = Worker(simpleq, [queue], concurrency=1)

    received_queue, jobs = await worker._receive(queue)

    assert received_queue is queue
    assert jobs == []
    assert queue.received_visibility_timeouts == [1]


@pytest.mark.asyncio
async def test_worker_heartbeat_uses_minimum_visibility_timeout_of_one_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simpleq = SimpleQ()
    queue = FakeQueue(simpleq=simpleq, visibility_timeout=0)
    worker = Worker(simpleq, [queue], concurrency=1)
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
        receipt_handle="receipt-1",
    )
    original_sleep = asyncio.sleep

    async def fast_sleep(_seconds: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr("simpleq.worker.asyncio.sleep", fast_sleep)

    heartbeat_task = worker._heartbeat(queue, job)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    heartbeat_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await heartbeat_task

    assert queue.visibility_changes
    assert queue.visibility_changes[0] == 1


@pytest.mark.asyncio
async def test_worker_retry_delay_uses_minimum_visibility_timeout_of_one_second() -> (
    None
):
    simpleq = SimpleQ(backoff_strategy="exponential")
    definition = TaskDefinition(
        name=task_name_for(record_sync),
        func=record_sync,
        retry_exceptions=(RuntimeError,),
    )
    simpleq.registry.register(definition)
    queue = FakeQueue(simpleq=simpleq, visibility_timeout=0)
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
