"""SimpleQ worker implementation."""

from __future__ import annotations

import asyncio
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
        receive_timeout_seconds: float | None = None,
    ) -> None:
        resolved_queues = list(queues)
        if not resolved_queues:
            raise ValueError("at least one queue must be configured.")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1.")
        if poll_interval < 0:
            raise ValueError("poll_interval must be non-negative.")
        if receive_timeout_seconds is not None and receive_timeout_seconds <= 0:
            raise ValueError("receive_timeout_seconds must be greater than 0.")
        self.simpleq = simpleq
        self.queues = resolved_queues
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.receive_timeout_seconds = receive_timeout_seconds
        self._stopping = asyncio.Event()
        self._in_flight_receives: set[asyncio.Task[tuple[Any, list[Job]]]] = set()

    async def work(self, *, burst: bool = False) -> None:
        """Poll configured queues until stopped."""
        semaphore = asyncio.Semaphore(self.concurrency)
        while not self._stopping.is_set():
            processed = False
            tasks: list[asyncio.Task[None]] = []
            receive_tasks = [
                asyncio.create_task(self._receive(queue)) for queue in self.queues
            ]
            self._in_flight_receives.update(receive_tasks)
            try:
                for receive_task in asyncio.as_completed(receive_tasks):
                    try:
                        queue, jobs = await receive_task
                    except asyncio.CancelledError:
                        if self._stopping.is_set():
                            continue
                        raise
                    for job in jobs:
                        processed = True
                        tasks.append(
                            asyncio.create_task(
                                self._process_job(queue, job, semaphore)
                            )
                        )
            finally:
                for receive_task in receive_tasks:
                    if not receive_task.done():
                        receive_task.cancel()
                await asyncio.gather(*receive_tasks, return_exceptions=True)
                self._in_flight_receives.difference_update(receive_tasks)
            if tasks:
                await asyncio.gather(*tasks)
            if burst and not processed:
                break
            if not processed:
                await asyncio.sleep(self.poll_interval)

    async def _receive(self, queue: Any) -> tuple[Any, list[Job]]:
        try:
            timeout_seconds = self._receive_timeout(queue)
            jobs = await asyncio.wait_for(
                queue.receive(
                    max_messages=min(queue.batch_size, self.concurrency),
                    visibility_timeout=queue.visibility_timeout,
                ),
                timeout=timeout_seconds,
            )
            return queue, jobs
        except asyncio.TimeoutError:
            queue_name = str(getattr(queue, "name", "unknown"))
            self.simpleq.logger.warning(
                "queue_receive_timeout",
                queue_name=queue_name,
                timeout_seconds=timeout_seconds,
            )
            self.simpleq.metrics.record_processed(
                queue_name,
                status="receive_timeout",
                duration_seconds=0.0,
            )
            return queue, []
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            queue_name = str(getattr(queue, "name", "unknown"))
            self.simpleq.logger.error(
                "queue_receive_failed",
                queue_name=queue_name,
                error=str(exc),
            )
            self.simpleq.metrics.record_processed(
                queue_name,
                status="receive_error",
                duration_seconds=0.0,
            )
            return queue, []

    def _receive_timeout(self, queue: Any) -> float:
        if self.receive_timeout_seconds is not None:
            return self.receive_timeout_seconds
        wait_seconds = max(0, int(getattr(queue, "wait_seconds", 0)))
        return float(wait_seconds + 5)

    def work_sync(self, *, burst: bool = False) -> None:
        """Synchronous wrapper for :meth:`work`."""
        run_sync(self.work(burst=burst))

    async def stop(self) -> None:
        """Signal the worker loop to stop."""
        self._stopping.set()
        for receive_task in list(self._in_flight_receives):
            receive_task.cancel()

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
            except asyncio.CancelledError:
                if not self._stopping.is_set():
                    await self._handle_failure_safely(
                        queue,
                        job,
                        RuntimeError("Task execution cancelled unexpectedly."),
                    )
                    return
                raise
            except Exception as exc:
                await self._handle_failure_safely(queue, job, exc)
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
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        queue_name = str(getattr(queue, "name", "unknown"))
                        self.simpleq.logger.warning(
                            "queue_visibility_heartbeat_shutdown_failed",
                            queue_name=queue_name,
                            job_id=str(getattr(job, "job_id", "unknown")),
                            error=str(exc),
                        )

    async def _handle_failure_safely(
        self,
        queue: Any,
        job: Job,
        exc: BaseException,
    ) -> None:
        """Handle job failures without allowing secondary errors to crash workers."""
        try:
            await self._handle_failure(queue, job, exc)
        except Exception as handler_exc:
            queue_name = str(getattr(queue, "name", "unknown"))
            self.simpleq.logger.error(
                "queue_failure_handler_failed",
                queue_name=queue_name,
                job_id=str(getattr(job, "job_id", "unknown")),
                task_name=str(getattr(job, "task_name", "unknown")),
                original_error=str(exc),
                handler_error=str(handler_exc),
            )
            self.simpleq.metrics.record_processed(
                queue_name,
                status="failure_handler_error",
                duration_seconds=0.0,
            )

    def _heartbeat(self, queue: Any, job: Job) -> asyncio.Task[None]:
        async def extend() -> None:
            interval = max(1, queue.visibility_timeout // 2)
            while True:
                await asyncio.sleep(interval)
                try:
                    await queue.change_visibility(job, queue.visibility_timeout)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    queue_name = str(getattr(queue, "name", "unknown"))
                    self.simpleq.logger.warning(
                        "queue_visibility_heartbeat_failed",
                        queue_name=queue_name,
                        job_id=str(getattr(job, "job_id", "unknown")),
                        error=str(exc),
                    )
                    self.simpleq.metrics.record_processed(
                        queue_name,
                        status="heartbeat_error",
                        duration_seconds=0.0,
                    )

        return asyncio.create_task(extend())

    async def _invoke(self, _queue: Any, job: Job) -> Any:
        definition = self.simpleq.registry.get(job.task_name)
        args, kwargs = reconstruct_arguments(definition.schema, job.args, job.kwargs)
        if definition.is_async:
            return await definition.func(*args, **kwargs)
        return await asyncio.to_thread(definition.func, *args, **kwargs)

    async def _handle_failure(self, queue: Any, job: Job, exc: BaseException) -> None:
        self.simpleq.cost_tracker.job_failed(queue.name)
        definition = self._resolve_task_definition(job.task_name)
        if definition is None:
            await queue.move_to_dlq(job, error=f"task-definition-resolution-failed: {exc}")
            self.simpleq.metrics.record_processed(
                queue.name,
                status="dlq" if queue_has_dlq(queue) else "failure",
                duration_seconds=0.0,
            )
            return

        should_retry = self._should_retry(definition, exc)
        if should_retry:
            self.simpleq.cost_tracker.job_retried(queue.name)
            if job.receive_count >= effective_max_retries(queue, definition):
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

    def _resolve_task_definition(self, task_name: str) -> Any | None:
        try:
            return self.simpleq.registry.get(task_name)
        except Exception as resolve_exc:
            self.simpleq.logger.error(
                "task_definition_resolution_failed",
                task_name=task_name,
                error=str(resolve_exc),
            )
            return None

    def _should_retry(self, definition: Any, exc: BaseException) -> bool:
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


def effective_max_retries(queue: Any, definition: Any) -> int:
    """Return the effective max retries for a given job."""
    if definition.max_retries is not None:
        return int(definition.max_retries)
    return int(queue.max_retries)


def queue_has_dlq(queue: Any) -> bool:
    """Return whether a queue has DLQ support enabled."""
    if getattr(queue, "dlq", False):
        return True
    return getattr(queue, "dlq_name", None) is not None
