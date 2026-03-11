"""Primary SimpleQ client and public entrypoint."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    ParamSpec,
    TypeVar,
    cast,
)

from simpleq._sync import run_sync
from simpleq.config import BackoffStrategy, SimpleQConfig
from simpleq.exceptions import InvalidTaskError, QueueValidationError
from simpleq.observability import CostTracker, PrometheusMetrics, configure_logging
from simpleq.queue import Queue
from simpleq.sqs import SQSClient
from simpleq.task import TaskDefinition, TaskHandle, TaskRegistry, task_name_for
from simpleq.worker import Worker

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pydantic import BaseModel

P = ParamSpec("P")
R = TypeVar("R")


def _validate_retry_options(
    *,
    retry_exceptions: Sequence[type[BaseException]] | None,
    max_retries: int | None,
) -> None:
    """Validate task-level retry options provided to ``SimpleQ.task``."""
    if max_retries is not None and max_retries < 0:
        raise InvalidTaskError("max_retries must be greater than or equal to 0.")
    if retry_exceptions is None:
        return
    for retry_exception in retry_exceptions:
        if not isinstance(retry_exception, type) or not issubclass(
            retry_exception, BaseException
        ):
            raise InvalidTaskError(
                "retry_exceptions entries must be exception classes."
            )


class SimpleQ:
    """The main application entrypoint for SimpleQ."""

    def __init__(
        self,
        *,
        region: str | None = None,
        endpoint_url: str | None = None,
        batch_size: int | None = None,
        wait_seconds: int | None = None,
        visibility_timeout: int | None = None,
        concurrency: int | None = None,
        graceful_shutdown_timeout: int | None = None,
        max_retries: int | None = None,
        backoff_strategy: BackoffStrategy | None = None,
        enable_cost_tracking: bool | None = None,
        enable_metrics: bool | None = None,
        enable_tracing: bool | None = None,
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None,
        sqs_price_per_million: float | None = None,
        default_queue_name: str | None = None,
        transport: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.config = SimpleQConfig.from_overrides(
            region=region,
            endpoint_url=endpoint_url,
            batch_size=batch_size,
            wait_seconds=wait_seconds,
            visibility_timeout=visibility_timeout,
            concurrency=concurrency,
            graceful_shutdown_timeout=graceful_shutdown_timeout,
            max_retries=max_retries,
            backoff_strategy=backoff_strategy,
            enable_cost_tracking=enable_cost_tracking,
            enable_metrics=enable_metrics,
            enable_tracing=enable_tracing,
            log_level=log_level,
            sqs_price_per_million=sqs_price_per_million,
            default_queue_name=default_queue_name,
        )
        self.cost_tracker = CostTracker(
            price_per_million=self.config.sqs_price_per_million
        )
        self.metrics = PrometheusMetrics()
        self.logger = configure_logging(self.config.log_level)
        self.registry = TaskRegistry()
        self._transport = transport
        self._session_factory = session_factory
        self._queues: dict[str, Queue] = {}

    @property
    def transport(self) -> Any:
        """Return the configured transport, creating the default lazily."""
        if self._transport is None:
            self._transport = SQSClient(
                self.config,
                self.cost_tracker,
                session_factory=self._session_factory,
            )
        return self._transport

    @transport.setter
    def transport(self, value: Any) -> None:
        """Override the transport used for queue operations."""
        self._transport = value

    def queue(
        self,
        name: str,
        *,
        fifo: bool = False,
        dlq: bool = False,
        max_retries: int | None = None,
        content_based_deduplication: bool = False,
        visibility_timeout: int | None = None,
        wait_seconds: int | None = None,
        tags: dict[str, str] | None = None,
    ) -> Queue:
        """Create or return a cached queue object."""
        requested = Queue(
            self,
            name,
            fifo=fifo,
            dlq=dlq,
            max_retries=max_retries,
            content_based_deduplication=content_based_deduplication,
            visibility_timeout=visibility_timeout,
            wait_seconds=wait_seconds,
            tags=tags,
        )
        if existing := self._queues.get(requested.name):
            self._assert_queue_matches(existing, requested)
            return existing
        self._queues[requested.name] = requested
        return requested

    def _configured_queues(self, name: str) -> list[Queue]:
        """Return cached queue objects for the given queue name."""
        return [queue for queue in self._queues.values() if queue.name == name]

    def _assert_queue_matches(self, existing: Queue, requested: Queue) -> None:
        """Ensure a queue name is not rebound to a different configuration."""
        existing_config = self._queue_signature(existing)
        requested_config = self._queue_signature(requested)
        differences = [
            f"{field}={existing_value!r} -> {requested_value!r}"
            for field, existing_value in existing_config.items()
            if requested_config[field] != existing_value
            for requested_value in [requested_config[field]]
        ]
        if not differences:
            return
        difference_list = ", ".join(differences)
        raise QueueValidationError(
            f"Queue '{existing.name}' is already configured differently on this "
            f"SimpleQ instance ({difference_list}). Reuse the original Queue "
            "instance or keep the queue definition consistent."
        )

    def _queue_signature(self, queue: Queue) -> dict[str, object]:
        """Return the stable queue options used to detect configuration drift."""
        return {
            "fifo": queue.fifo,
            "dlq": queue.dlq,
            "max_retries": queue.max_retries,
            "content_based_deduplication": queue.content_based_deduplication,
            "visibility_timeout": queue.visibility_timeout,
            "wait_seconds": queue.wait_seconds,
            "tags": dict(queue.tags),
        }

    def _clone_queue(self, queue: Queue) -> Queue:
        """Rebuild a queue onto this client while preserving its configuration."""
        return self.queue(
            queue.name,
            fifo=queue.fifo,
            dlq=queue.dlq,
            max_retries=queue.max_retries,
            content_based_deduplication=queue.content_based_deduplication,
            visibility_timeout=queue.visibility_timeout,
            wait_seconds=queue.wait_seconds,
            tags=dict(queue.tags) if queue._tags_configured else None,
        )

    def resolve_queue(self, queue_ref: Any | None) -> Queue:
        """Resolve a queue reference into a Queue instance."""
        if queue_ref is None:
            default_name = self.config.default_queue_name
            return self.queue(default_name, fifo=default_name.endswith(".fifo"))
        if isinstance(queue_ref, Queue):
            if queue_ref.simpleq is self:
                return queue_ref
            return self._clone_queue(queue_ref)
        if isinstance(queue_ref, str):
            matches = self._configured_queues(queue_ref)
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise QueueValidationError(
                    f"Queue name '{queue_ref}' is ambiguous. Reuse the Queue instance instead."
                )
            return self.queue(queue_ref, fifo=queue_ref.endswith(".fifo"))
        return cast("Queue", queue_ref)

    def task(
        self,
        *,
        queue: Queue | str | None = None,
        serializer: str = "json",
        schema: type[BaseModel] | None = None,
        message_group_id: str | Callable[..., str] | None = None,
        deduplication_id: str | Callable[..., str] | None = None,
        retry_exceptions: Sequence[type[BaseException]] | None = None,
        max_retries: int | None = None,
    ) -> Callable[[Callable[P, R]], TaskHandle[P, R]]:
        """Register a function as a SimpleQ task."""
        _validate_retry_options(
            retry_exceptions=retry_exceptions,
            max_retries=max_retries,
        )

        def decorator(func: Callable[P, R]) -> TaskHandle[P, R]:
            definition = TaskDefinition(
                name=task_name_for(func),
                func=func,
                queue_ref=queue,
                serializer=serializer,
                schema=schema,
                message_group_id=message_group_id,
                deduplication_id=deduplication_id,
                retry_exceptions=tuple(retry_exceptions) if retry_exceptions else None,
                max_retries=max_retries,
            )
            self.registry.register(definition)
            return TaskHandle(self, definition)

        return decorator

    def worker(
        self,
        *,
        queues: Sequence[Queue | str],
        concurrency: int | None = None,
        poll_interval: float = 1.0,
        receive_timeout_seconds: float | None = None,
    ) -> Worker:
        """Create a worker for the specified queues."""
        resolved_queues = [self.resolve_queue(queue) for queue in queues]
        return Worker(
            self,
            resolved_queues,
            concurrency=(
                self.config.concurrency if concurrency is None else concurrency
            ),
            poll_interval=poll_interval,
            receive_timeout_seconds=receive_timeout_seconds,
        )

    async def list_queues(self, prefix: str | None = None) -> list[str]:
        """List SQS queue names, optionally filtered by prefix."""
        urls = await self.transport.list_queues(prefix)
        return [url.rsplit("/", 1)[-1] for url in urls]

    def list_queues_sync(self, prefix: str | None = None) -> list[str]:
        """Synchronous wrapper for :meth:`list_queues`."""
        return run_sync(self.list_queues(prefix))

    def run_sync(self, awaitable: Any) -> Any:
        """Expose the sync helper for CLI callers."""
        return run_sync(awaitable)
