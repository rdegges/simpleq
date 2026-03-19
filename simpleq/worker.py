"""Worker — polls SQS queues and executes tasks."""

from __future__ import annotations

import asyncio
import signal
import time
from typing import Any

import structlog

from simpleq.job import Job
from simpleq.queue import Queue
from simpleq.task import Task

logger = structlog.get_logger()

# Backoff caps
_MAX_BACKOFF_SECONDS = 43200  # 12 hours (SQS max visibility timeout)
_BASE_BACKOFF_SECONDS = 2


def _calculate_backoff(strategy: str, retry_count: int) -> int:
    """Calculate visibility timeout for retry backoff."""
    if strategy == "exponential":
        delay = _BASE_BACKOFF_SECONDS ** (retry_count + 1)
    elif strategy == "linear":
        delay = _BASE_BACKOFF_SECONDS * (retry_count + 1)
    else:
        delay = _BASE_BACKOFF_SECONDS

    return min(int(delay), _MAX_BACKOFF_SECONDS)


class Worker:
    """Polls one or more SQS queues and executes registered tasks.

    Usage:
        worker = Worker([sq.queue("emails")], tasks=sq.tasks)
        worker.work()                  # Run forever
        worker.work(burst=True)        # Process pending jobs, then exit

    Workers handle SIGINT and SIGTERM gracefully — the current job finishes,
    then the worker stops.
    """

    def __init__(
        self,
        queues: list[Queue],
        tasks: dict[str, Task] | None = None,
    ) -> None:
        self.queues = queues
        self.tasks = tasks or {}
        self._shutdown = False

    def work(self, burst: bool = False) -> None:
        """Start processing jobs.

        Args:
            burst: If True, process all available jobs then exit.
                   If False, poll forever until SIGINT/SIGTERM.
        """
        self._shutdown = False
        self._setup_signal_handlers()

        logger.info(
            "worker_started",
            queues=[q.name for q in self.queues],
            tasks=list(self.tasks.keys()),
            burst=burst,
        )

        while not self._shutdown:
            processed = 0
            for queue in self.queues:
                if self._shutdown:
                    break

                jobs = queue.receive_jobs()
                for job in jobs:
                    if self._shutdown:
                        break
                    self._process_job(job, queue)
                    processed += 1

            if self._shutdown:
                logger.info("shutdown_requested")
                break

            if burst and processed == 0:
                break

        logger.info("worker_stopped")

    def _process_job(self, job: Job, queue: Queue) -> None:
        """Execute a single job.

        TODO: Add visibility timeout heartbeat for long-running tasks.
        Without it, tasks running longer than the visibility timeout
        (default 30s) get re-delivered to another worker.
        """
        task = self.tasks.get(job.task_name)
        if task is None:
            logger.error(
                "task_not_found",
                task_name=job.task_name,
                registered_tasks=list(self.tasks.keys()),
            )
            return

        start = time.monotonic()
        try:
            if task.async_:
                asyncio.run(task.fn(*job.args, **job.kwargs))
            else:
                task.fn(*job.args, **job.kwargs)

            duration = time.monotonic() - start
            queue.delete_job(job)
            logger.info(
                "job_completed",
                task_name=job.task_name,
                duration=round(duration, 3),
            )

        except Exception as e:
            duration = time.monotonic() - start
            logger.error(
                "job_failed",
                task_name=job.task_name,
                error=str(e),
                error_type=type(e).__name__,
                duration=round(duration, 3),
                receive_count=job.receive_count,
                max_retries=task.retries,
            )

            if task.retries > 0 and job.receive_count <= task.retries:
                # Apply backoff by changing visibility timeout
                backoff_seconds = _calculate_backoff(
                    task.backoff, job.receive_count
                )
                try:
                    queue.change_visibility(job, backoff_seconds)
                    logger.info(
                        "job_retry_scheduled",
                        task_name=job.task_name,
                        retry=job.receive_count,
                        max_retries=task.retries,
                        backoff_seconds=backoff_seconds,
                    )
                except Exception:
                    logger.warning(
                        "backoff_failed",
                        task_name=job.task_name,
                    )
            elif task.retries > 0 and job.receive_count > task.retries:
                # Retries exhausted — delete if no DLQ (SQS handles DLQ move)
                if not queue.config.dead_letter_queue:
                    queue.delete_job(job)
                    logger.warning(
                        "retries_exhausted_deleted",
                        task_name=job.task_name,
                        receive_count=job.receive_count,
                    )
            # If no retries configured, leave message in queue for SQS to
            # handle (visibility timeout expiry makes it available again)

    def _setup_signal_handlers(self) -> None:
        """Register SIGINT and SIGTERM for graceful shutdown."""
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """Signal handler — sets the shutdown flag so the current job
        finishes before the worker exits.

        Only sets the boolean flag here — logging is deferred to the main
        loop since structlog is not async-signal-safe.
        """
        self._shutdown = True
