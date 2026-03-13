"""Runtime protocols for SimpleQ infrastructure boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Coroutine, Sequence

    from simpleq.config import SimpleQConfig
    from simpleq.job import Job
    from simpleq.queue import Queue
    from simpleq.task import TaskDefinition

R = TypeVar("R")


class LoggerProtocol(Protocol):
    """Minimal structured logger interface used across runtime modules."""

    def debug(self, event: str, /, *args: object, **kwargs: object) -> object: ...

    def info(self, event: str, /, *args: object, **kwargs: object) -> object: ...

    def warning(self, event: str, /, *args: object, **kwargs: object) -> object: ...

    def error(self, event: str, /, *args: object, **kwargs: object) -> object: ...

    def critical(self, event: str, /, *args: object, **kwargs: object) -> object: ...


class CostTrackerProtocol(Protocol):
    """Cost tracker methods exercised by the runtime and CLI."""

    def track_request(
        self, queue_name: str, operation: str, *, count: int = 1
    ) -> None: ...

    def job_enqueued(self, queue_name: str, *, count: int = 1) -> None: ...

    def job_completed(self, queue_name: str, *, duration_ms: float) -> None: ...

    def job_failed(self, queue_name: str) -> None: ...

    def job_retried(self, queue_name: str) -> None: ...

    def job_decode_failed(self, queue_name: str) -> None: ...

    def total_cost(self) -> float: ...

    def snapshot(self) -> dict[str, dict[str, int | float]]: ...


class MetricsProtocol(Protocol):
    """Metrics methods exercised by the runtime and CLI."""

    registry: object

    def record_enqueue(self, queue_name: str, *, count: int = 1) -> None: ...

    def record_processed(
        self,
        queue_name: str,
        *,
        status: str,
        duration_seconds: float,
    ) -> None: ...

    def record_queue_depth(self, queue_name: str, depth: int) -> None: ...

    def record_retry_delay(
        self,
        queue_name: str,
        *,
        strategy: str,
        delay_seconds: int,
    ) -> None: ...


class TaskRegistryProtocol(Protocol):
    """Task registry methods used across runtime and CLI modules."""

    def register(self, definition: TaskDefinition) -> None: ...

    def get(self, task_name: str) -> TaskDefinition: ...

    def names(self) -> list[str]: ...


class QueueTransportProtocol(Protocol):
    """Transport operations required by ``Queue`` and ``SimpleQ``."""

    async def ensure_queue(
        self,
        queue_name: str,
        *,
        attributes: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str: ...

    async def list_queues(self, prefix: str | None = None) -> list[str]: ...

    async def queue_arn(self, queue_name: str, queue_url: str) -> str: ...

    async def delete_queue(self, queue_name: str, queue_url: str) -> None: ...

    async def purge_queue(self, queue_name: str, queue_url: str) -> None: ...

    async def send_message(
        self,
        queue_name: str,
        queue_url: str,
        *,
        message_body: str,
        delay_seconds: int | None = None,
        message_group_id: str | None = None,
        deduplication_id: str | None = None,
        message_attributes: dict[str, dict[str, str]] | None = None,
    ) -> str: ...

    async def send_message_batch(
        self,
        queue_name: str,
        queue_url: str,
        entries: list[dict[str, object]],
    ) -> list[str]: ...

    async def receive_messages(
        self,
        queue_name: str,
        queue_url: str,
        *,
        max_messages: int,
        wait_seconds: int,
        visibility_timeout: int | None,
        receive_request_attempt_id: str | None = None,
    ) -> list[dict[str, object]]: ...

    async def delete_message(
        self, queue_name: str, queue_url: str, receipt_handle: str
    ) -> None: ...

    async def change_message_visibility(
        self,
        queue_name: str,
        queue_url: str,
        receipt_handle: str,
        timeout_seconds: int,
    ) -> None: ...

    async def get_queue_attributes(
        self,
        queue_name: str,
        queue_url: str,
        attribute_names: list[str],
    ) -> dict[str, str]: ...


class TaskQueueProtocol(Protocol):
    """Queue surface required by ``TaskHandle``."""

    name: str

    async def enqueue(
        self,
        job: Job,
        *,
        delay_seconds: int = 0,
        message_group_id: str | None = None,
        deduplication_id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> str: ...


class QueueRuntimeProtocol(Protocol):
    """Queue surface required by ``Worker``."""

    name: str
    batch_size: int
    max_retries: int
    visibility_timeout: int
    wait_seconds: int
    dlq: bool
    dlq_name: str | None

    async def receive(
        self,
        *,
        max_messages: int,
        visibility_timeout: int,
    ) -> list[Job]: ...

    async def ack(self, job: Job) -> None: ...

    async def change_visibility(self, job: Job, timeout_seconds: int) -> None: ...

    async def move_to_dlq(self, job: Job, *, error: str) -> None: ...


class TaskAppProtocol(Protocol):
    """SimpleQ surface required by ``TaskHandle``."""

    registry: TaskRegistryProtocol

    def resolve_queue(self, queue_ref: Queue | str | None) -> TaskQueueProtocol: ...


class WorkerAppProtocol(Protocol):
    """SimpleQ surface required by ``Worker``."""

    config: SimpleQConfig
    logger: LoggerProtocol
    cost_tracker: CostTrackerProtocol
    metrics: MetricsProtocol
    registry: TaskRegistryProtocol


class QueueAppProtocol(Protocol):
    """SimpleQ surface required by ``Queue``."""

    config: SimpleQConfig
    logger: LoggerProtocol
    cost_tracker: CostTrackerProtocol
    metrics: MetricsProtocol
    registry: TaskRegistryProtocol
    transport: QueueTransportProtocol

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
    ) -> Queue: ...

    def run_sync(self, awaitable: Coroutine[object, object, R]) -> R: ...


class WorkerFactoryProtocol(Protocol):
    """Simple worker surface used by CLI reload helpers."""

    def work_sync(self, *, burst: bool = False) -> None: ...

    def stop(self) -> Coroutine[object, object, None]: ...


class ClientFactoryProtocol(Protocol):
    """SimpleQ client surface exercised by CLI command handlers."""

    config: SimpleQConfig
    cost_tracker: CostTrackerProtocol
    metrics: MetricsProtocol
    registry: TaskRegistryProtocol

    def worker(
        self,
        *,
        queues: Sequence[str | Queue],
        concurrency: int | None = None,
        poll_interval: float | None = None,
        receive_timeout_seconds: float | None = None,
        graceful_shutdown_timeout: float | None = None,
    ) -> WorkerFactoryProtocol: ...

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
    ) -> Queue: ...

    def list_queues_sync(self, prefix: str | None = None) -> list[str]: ...

    def resolve_queue(self, queue_ref: Queue | str | None) -> Queue: ...

    def run_sync(self, awaitable: Coroutine[object, object, R]) -> R: ...
