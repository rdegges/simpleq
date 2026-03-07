"""SimpleQ worker implementation."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from simpleq._sync import run_sync
from simpleq.observability import Timer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic import BaseModel

    from simpleq.job import Job


class Worker:
    """Async worker that polls queues and executes registered tasks."""

    def __init__(
        self,
        simpleq: Any,
        queues: Sequence[Any],
        *,
        concurrency: int,
        poll_interval: float = 1.0,
    ) -> None:
        self.simpleq = simpleq
        self.queues = list(queues)
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self._stopping = asyncio.Event()

    async def work(self, *, burst: bool = False) -> None:
        """Poll configured queues until stopped."""
        semaphore = asyncio.Semaphore(self.concurrency)
        while not self._stopping.is_set():
            processed = False
            tasks: list[asyncio.Task[None]] = []
            for queue in self.queues:
                jobs = await queue.receive(
                    max_messages=min(queue.batch_size, self.concurrency),
                    visibility_timeout=queue.visibility_timeout,
                )
                for job in jobs:
                    processed = True
                    tasks.append(
                        asyncio.create_task(self._process_job(queue, job, semaphore))
                    )
            if tasks:
                await asyncio.gather(*tasks)
            if burst and not processed:
                break
            if not processed:
                await asyncio.sleep(self.poll_interval)

    def work_sync(self, *, burst: bool = False) -> None:
        """Synchronous wrapper for :meth:`work`."""
        run_sync(self.work(burst=burst))

    async def stop(self) -> None:
        """Signal the worker loop to stop."""
        self._stopping.set()

    async def _process_job(
        self, queue: Any, job: Job, semaphore: asyncio.Semaphore
    ) -> None:
        async with semaphore:
            timer = Timer()
            timer.start()
            heartbeat_task: asyncio.Task[None] | None = None
            try:
                heartbeat_task = self._heartbeat(queue, job)
                await self._invoke(queue, job)
            except BaseException as exc:  # noqa: BLE001
                await self._handle_failure(queue, job, exc)
            else:
                await queue.ack(job)
                duration_ms = timer.stop()
                self.simpleq.cost_tracker.job_completed(
                    queue.name, duration_ms=duration_ms
                )
                self.simpleq.metrics.record_processed(
                    queue.name,
                    status="success",
                    duration_seconds=duration_ms / 1000,
                )
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat_task

    def _heartbeat(self, queue: Any, job: Job) -> asyncio.Task[None]:
        async def extend() -> None:
            interval = max(1, queue.visibility_timeout // 2)
            while True:
                await asyncio.sleep(interval)
                await queue.change_visibility(job, queue.visibility_timeout)

        return asyncio.create_task(extend())

    async def _invoke(self, _queue: Any, job: Job) -> Any:
        definition = self.simpleq.registry.get(job.task_name)
        args, kwargs = reconstruct_arguments(definition.schema, job.args, job.kwargs)
        if definition.is_async:
            return await definition.func(*args, **kwargs)
        return await asyncio.to_thread(definition.func, *args, **kwargs)

    async def _handle_failure(self, queue: Any, job: Job, exc: BaseException) -> None:
        self.simpleq.cost_tracker.job_failed(queue.name)
        should_retry = self._should_retry(job, exc)
        if should_retry:
            self.simpleq.cost_tracker.job_retried(queue.name)
            if job.receive_count >= effective_max_retries(queue, job):
                await queue.move_to_dlq(job, error=str(exc))
                self.simpleq.metrics.record_processed(
                    queue.name,
                    status="dlq",
                    duration_seconds=0.0,
                )
                return
            delay = self._retry_delay(queue, job.receive_count)
            await queue.change_visibility(job, delay)
            self.simpleq.metrics.record_processed(
                queue.name,
                status="retry",
                duration_seconds=0.0,
            )
            return

        await queue.ack(job)
        self.simpleq.metrics.record_processed(
            queue.name,
            status="failure",
            duration_seconds=0.0,
        )

    def _should_retry(self, job: Job, exc: BaseException) -> bool:
        definition = self.simpleq.registry.get(job.task_name)
        if definition.retry_exceptions is None:
            return True
        return isinstance(exc, definition.retry_exceptions)

    def _retry_delay(self, queue: Any, attempt: int) -> int:
        strategy = self.simpleq.config.backoff_strategy
        if strategy == "constant":
            return min(int(queue.visibility_timeout), 1)
        if strategy == "linear":
            return int(min(int(queue.visibility_timeout), attempt))
        return int(min(int(queue.visibility_timeout), 2 ** max(attempt - 1, 0)))


def reconstruct_arguments(
    schema: type[BaseModel] | None,
    args: Any,
    kwargs: Any,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Rehydrate task arguments before invoking a callable."""
    if schema is None:
        return tuple(args), dict(kwargs)
    if len(args) != 1 or kwargs:
        raise ValueError(
            "Schema task payloads must deserialize to a single positional argument."
        )
    model = schema.model_validate(args[0])
    return (model,), {}


def effective_max_retries(queue: Any, job: Job) -> int:
    """Return the effective max retries for a given job."""
    definition = queue.simpleq.registry.get(job.task_name)
    if definition.max_retries is not None:
        return int(definition.max_retries)
    return int(queue.max_retries)
