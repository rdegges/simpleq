"""SimpleQ worker implementation."""

from __future__ import annotations

import asyncio
import random
import typing
from numbers import Real
from typing import TYPE_CHECKING, cast

from simpleq._sync import run_sync
from simpleq.observability import Timer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic import BaseModel

    from simpleq.job import Job
    from simpleq.protocols import QueueRuntimeProtocol, WorkerAppProtocol
    from simpleq.task import TaskDefinition


class Worker:
    """Async worker that polls queues and executes registered tasks."""

    def __init__(
        self,
        simpleq: WorkerAppProtocol,
        queues: Sequence[QueueRuntimeProtocol],
        *,
        concurrency: int,
        poll_interval: float = 1.0,
        receive_timeout_seconds: float | None = None,
        graceful_shutdown_timeout: float | None = None,
    ) -> None:
        resolved_queues = list(queues)
        if not resolved_queues:
            raise ValueError("at least one queue must be configured.")
        if not _is_strict_int(concurrency):
            raise ValueError("concurrency must be an integer.")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1.")
        if not _is_strict_real(poll_interval):
            raise ValueError("poll_interval must be a number.")
        if poll_interval < 0:
            raise ValueError("poll_interval must be non-negative.")
        if receive_timeout_seconds is not None and not _is_strict_real(
            receive_timeout_seconds
        ):
            raise ValueError("receive_timeout_seconds must be a number.")
        if receive_timeout_seconds is not None and receive_timeout_seconds <= 0:
            raise ValueError("receive_timeout_seconds must be greater than 0.")
        if graceful_shutdown_timeout is not None and not _is_strict_real(
            graceful_shutdown_timeout
        ):
            raise ValueError("graceful_shutdown_timeout must be a number.")
        if graceful_shutdown_timeout is not None and graceful_shutdown_timeout < 0:
            raise ValueError("graceful_shutdown_timeout must be non-negative.")
        self.simpleq = simpleq
        self.queues = resolved_queues
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.receive_timeout_seconds = receive_timeout_seconds
        resolved_graceful_shutdown_timeout = (
            simpleq.config.graceful_shutdown_timeout
            if graceful_shutdown_timeout is None
            else graceful_shutdown_timeout
        )
        self.graceful_shutdown_timeout = float(resolved_graceful_shutdown_timeout)
        self._stopping = asyncio.Event()
        self._in_flight_receives: set[
            asyncio.Task[tuple[QueueRuntimeProtocol, list[Job]]]
        ] = set()
        self._in_flight_jobs: set[asyncio.Task[None]] = set()

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
                        if self._stopping.is_set():
                            break
                        processed = True
                        task = asyncio.create_task(
                            self._process_job(queue, job, semaphore)
                        )
                        self._in_flight_jobs.add(task)
                        task.add_done_callback(self._in_flight_jobs.discard)
                        tasks.append(task)
            finally:
                for receive_task in receive_tasks:
                    if not receive_task.done():
                        receive_task.cancel()
                await asyncio.gather(*receive_tasks, return_exceptions=True)
                self._in_flight_receives.difference_update(receive_tasks)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if self._stopping.is_set():
                break
            if burst and not processed:
                break
            if not processed:
                await asyncio.sleep(self.poll_interval)

    async def _receive(
        self, queue: QueueRuntimeProtocol
    ) -> tuple[QueueRuntimeProtocol, list[Job]]:
        try:
            timeout_seconds = self._receive_timeout(queue)
            visibility_timeout = self._visibility_timeout(queue)
            jobs = await asyncio.wait_for(
                queue.receive(
                    max_messages=min(queue.batch_size, self.concurrency),
                    visibility_timeout=visibility_timeout,
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

    def _receive_timeout(self, queue: QueueRuntimeProtocol) -> float:
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
        if not self._in_flight_jobs:
            return

        done, pending = await asyncio.wait(
            list(self._in_flight_jobs),
            timeout=self.graceful_shutdown_timeout,
        )
        if not pending:
            await asyncio.gather(*done, return_exceptions=True)
            return

        self.simpleq.logger.warning(
            "worker_graceful_shutdown_timeout",
            timeout_seconds=self.graceful_shutdown_timeout,
            cancelled_jobs=len(pending),
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _process_job(
        self,
        queue: QueueRuntimeProtocol,
        job: Job,
        semaphore: asyncio.Semaphore,
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
                duration_ms = timer.stop()
                try:
                    await queue.ack(job)
                except Exception as exc:
                    queue_name = str(getattr(queue, "name", "unknown"))
                    self.simpleq.logger.error(
                        "queue_ack_failed",
                        queue_name=queue_name,
                        job_id=str(getattr(job, "job_id", "unknown")),
                        task_name=str(getattr(job, "task_name", "unknown")),
                        error=str(exc),
                    )
                    self.simpleq.metrics.record_processed(
                        queue_name,
                        status="ack_error",
                        duration_seconds=duration_ms / 1000,
                    )
                    return
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
        queue: QueueRuntimeProtocol,
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

    def _heartbeat(self, queue: QueueRuntimeProtocol, job: Job) -> asyncio.Task[None]:
        async def extend() -> None:
            visibility_timeout = self._visibility_timeout(queue)
            interval = max(1, visibility_timeout // 2)
            while True:
                await asyncio.sleep(interval)
                try:
                    await queue.change_visibility(job, visibility_timeout)
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

    def _visibility_timeout(self, queue: QueueRuntimeProtocol) -> int:
        return max(1, int(getattr(queue, "visibility_timeout", 0)))

    async def _invoke(self, _queue: QueueRuntimeProtocol, job: Job) -> object:
        definition = self.simpleq.registry.get(job.task_name)
        args, kwargs = reconstruct_arguments(definition.schema, job.args, job.kwargs)
        if definition.is_async:
            async_func = cast(
                "typing.Callable[..., typing.Awaitable[object]]",
                definition.func,
            )
            return await async_func(*args, **kwargs)
        return await asyncio.to_thread(definition.func, *args, **kwargs)

    async def _handle_failure(
        self,
        queue: QueueRuntimeProtocol,
        job: Job,
        exc: BaseException,
    ) -> None:
        self.simpleq.cost_tracker.job_failed(queue.name)
        definition = self._resolve_task_definition(job.task_name)
        if definition is None:
            await queue.move_to_dlq(
                job, error=f"task-definition-resolution-failed: {exc}"
            )
            self.simpleq.metrics.record_processed(
                queue.name,
                status="dlq" if queue_has_dlq(queue) else "failure",
                duration_seconds=0.0,
            )
            return

        should_retry = self._should_retry(definition, exc)
        if should_retry:
            if job.receive_count >= effective_max_retries(queue, definition):
                await queue.move_to_dlq(job, error=str(exc))
                self.simpleq.metrics.record_processed(
                    queue.name,
                    status="dlq" if queue_has_dlq(queue) else "failure",
                    duration_seconds=0.0,
                )
                return
            delay = self._retry_delay(queue, job.receive_count)
            self.simpleq.cost_tracker.job_retried(queue.name)
            await queue.change_visibility(job, delay)
            self.simpleq.metrics.record_retry_delay(
                queue.name,
                strategy=self.simpleq.config.backoff_strategy,
                delay_seconds=delay,
            )
            self.simpleq.metrics.record_processed(
                queue.name,
                status="retry",
                duration_seconds=0.0,
            )
            return

        try:
            await queue.ack(job)
        except Exception as ack_exc:
            queue_name = str(getattr(queue, "name", "unknown"))
            self.simpleq.logger.error(
                "queue_ack_failed",
                queue_name=queue_name,
                job_id=str(getattr(job, "job_id", "unknown")),
                task_name=str(getattr(job, "task_name", "unknown")),
                error=str(ack_exc),
            )
            self.simpleq.metrics.record_processed(
                queue_name,
                status="ack_error",
                duration_seconds=0.0,
            )
            return
        self.simpleq.metrics.record_processed(
            queue.name,
            status="failure",
            duration_seconds=0.0,
        )

    def _resolve_task_definition(self, task_name: str) -> TaskDefinition | None:
        try:
            return self.simpleq.registry.get(task_name)
        except Exception as resolve_exc:
            self.simpleq.logger.error(
                "task_definition_resolution_failed",
                task_name=task_name,
                error=str(resolve_exc),
            )
            return None

    def _should_retry(self, definition: TaskDefinition, exc: BaseException) -> bool:
        if definition.retry_exceptions is None:
            return True
        return isinstance(exc, definition.retry_exceptions)

    def _retry_delay(self, queue: QueueRuntimeProtocol, attempt: int) -> int:
        strategy = self.simpleq.config.backoff_strategy
        visibility_timeout = self._visibility_timeout(queue)
        if strategy == "constant":
            return min(visibility_timeout, 1)
        if strategy == "linear":
            return int(min(visibility_timeout, attempt))
        if strategy == "exponential_jitter":
            upper_bound = max(1, int(min(visibility_timeout, 2 ** max(attempt - 1, 0))))
            jitter_floor = int(
                max(1, getattr(self.simpleq.config, "retry_jitter_min_seconds", 1))
            )
            lower_bound = min(jitter_floor, upper_bound)
            return random.randint(lower_bound, upper_bound)
        return int(min(visibility_timeout, 2 ** max(attempt - 1, 0)))


def reconstruct_arguments(
    schema: type[BaseModel] | None,
    args: object,
    kwargs: object,
) -> tuple[tuple[object, ...], dict[str, object]]:
    """Rehydrate task arguments before invoking a callable."""
    resolved_args = _coerce_args(args)
    resolved_kwargs = _coerce_kwargs(kwargs)
    if schema is None:
        return resolved_args, resolved_kwargs
    if len(resolved_args) != 1 or resolved_kwargs:
        raise ValueError(
            "Schema task payloads must deserialize to a single positional argument."
        )
    model = schema.model_validate(resolved_args[0])
    return (model,), {}


def _coerce_args(args: object) -> tuple[object, ...]:
    """Return deserialized task args as a tuple."""
    if isinstance(args, tuple):
        return args
    if isinstance(args, list):
        return tuple(args)
    raise ValueError("Task args must deserialize to a sequence.")


def _coerce_kwargs(kwargs: object) -> dict[str, object]:
    """Return deserialized task kwargs as a plain string-keyed mapping."""
    if not isinstance(kwargs, dict):
        raise ValueError("Task kwargs must deserialize to an object.")
    return {str(key): value for key, value in kwargs.items()}


def effective_max_retries(
    queue: QueueRuntimeProtocol, definition: TaskDefinition
) -> int:
    """Return the effective max retries for a given job."""
    if definition.max_retries is not None:
        return int(definition.max_retries)
    return int(queue.max_retries)


def queue_has_dlq(queue: QueueRuntimeProtocol) -> bool:
    """Return whether a queue has DLQ support enabled."""
    if getattr(queue, "dlq", False):
        return True
    return getattr(queue, "dlq_name", None) is not None


def _is_strict_int(value: object) -> bool:
    """Return whether ``value`` is an integer but not a boolean."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_strict_real(value: object) -> bool:
    """Return whether ``value`` is a real number but not a boolean."""
    return isinstance(value, Real) and not isinstance(value, bool)
