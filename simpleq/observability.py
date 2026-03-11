"""Logging, metrics, and cost tracking primitives."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Literal, cast

import structlog
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

OperationName = Literal[
    "change_visibility",
    "create_queue",
    "delete_message",
    "delete_queue",
    "get_queue_url",
    "get_queue_attributes",
    "list_queue_tags",
    "list_queues",
    "purge_queue",
    "receive_message",
    "send_message",
    "set_queue_attributes",
    "tag_queue",
    "untag_queue",
]


def configure_logging(level: str) -> structlog.stdlib.BoundLogger:
    """Create a structured logger for SimpleQ."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(serializer=json.dumps),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_to_int(level)),
    )
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger("simpleq"))


def level_to_int(level: str) -> int:
    """Map a log level string to the stdlib integer value."""
    mapping = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
    }
    return mapping[level]


@dataclass(slots=True)
class QueueCostMetrics:
    """Aggregate metrics for a single queue."""

    total_requests: int = 0
    send_requests: int = 0
    receive_requests: int = 0
    delete_requests: int = 0
    change_visibility_requests: int = 0
    management_requests: int = 0
    jobs_enqueued: int = 0
    jobs_processed: int = 0
    jobs_failed: int = 0
    jobs_retried: int = 0
    processing_time_ms: float = 0.0

    @property
    def average_processing_time_ms(self) -> float:
        """Return the average processing time per processed job."""
        if self.jobs_processed == 0:
            return 0.0
        return self.processing_time_ms / self.jobs_processed


class CostTracker:
    """Lightweight in-process SQS cost tracker."""

    def __init__(self, *, price_per_million: float = 0.40) -> None:
        self._price_per_million = price_per_million
        self._metrics: dict[str, QueueCostMetrics] = {}

    def metrics_for(self, queue_name: str) -> QueueCostMetrics:
        """Return metrics for a queue, creating them if needed."""
        return self._metrics.setdefault(queue_name, QueueCostMetrics())

    def track_request(
        self, queue_name: str, operation: OperationName, *, count: int = 1
    ) -> None:
        """Track SQS API request usage."""
        metrics = self.metrics_for(queue_name)
        metrics.total_requests += count
        if operation == "send_message":
            metrics.send_requests += count
        elif operation == "receive_message":
            metrics.receive_requests += count
        elif operation == "delete_message":
            metrics.delete_requests += count
        elif operation == "change_visibility":
            metrics.change_visibility_requests += count
        else:
            metrics.management_requests += count

    def job_enqueued(self, queue_name: str, *, count: int = 1) -> None:
        """Track logical jobs enqueued."""
        self.metrics_for(queue_name).jobs_enqueued += count

    def job_completed(self, queue_name: str, *, duration_ms: float) -> None:
        """Track a completed job."""
        metrics = self.metrics_for(queue_name)
        metrics.jobs_processed += 1
        metrics.processing_time_ms += duration_ms

    def job_failed(self, queue_name: str) -> None:
        """Track a failed job."""
        self.metrics_for(queue_name).jobs_failed += 1

    def job_retried(self, queue_name: str) -> None:
        """Track a retried job."""
        self.metrics_for(queue_name).jobs_retried += 1

    def total_cost(self) -> float:
        """Return the total estimated SQS request cost."""
        total_requests = sum(item.total_requests for item in self._metrics.values())
        return total_requests * (self._price_per_million / 1_000_000)

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        """Return a JSON-serializable snapshot of all queue metrics."""
        return {
            queue_name: asdict(metrics)
            for queue_name, metrics in sorted(self._metrics.items())
        }


class PrometheusMetrics:
    """Prometheus collectors for queue and worker state."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.jobs_enqueued = Counter(
            "simpleq_jobs_enqueued_total",
            "Jobs enqueued by SimpleQ.",
            ["queue"],
            registry=self.registry,
        )
        self.jobs_processed = Counter(
            "simpleq_jobs_processed_total",
            "Jobs processed by SimpleQ.",
            ["queue", "status"],
            registry=self.registry,
        )
        self.job_duration = Counter(
            "simpleq_job_duration_seconds_total",
            "Total job processing duration in seconds.",
            ["queue"],
            registry=self.registry,
        )
        self.queue_depth = Gauge(
            "simpleq_queue_depth",
            "Approximate visible messages in the queue.",
            ["queue"],
            registry=self.registry,
        )

    def record_enqueue(self, queue_name: str, *, count: int = 1) -> None:
        """Increment the enqueued jobs counter."""
        self.jobs_enqueued.labels(queue=queue_name).inc(count)

    def record_processed(
        self, queue_name: str, *, status: str, duration_seconds: float
    ) -> None:
        """Record job completion metrics."""
        self.jobs_processed.labels(queue=queue_name, status=status).inc()
        self.job_duration.labels(queue=queue_name).inc(duration_seconds)

    def record_queue_depth(self, queue_name: str, depth: int) -> None:
        """Update the queue depth gauge."""
        self.queue_depth.labels(queue=queue_name).set(depth)

    def render(self) -> bytes:
        """Render all metrics in Prometheus exposition format."""
        return generate_latest(self.registry)


@dataclass(slots=True)
class Timer:
    """Small context manager-like helper for elapsed time measurement."""

    started_at: float = 0.0

    def start(self) -> None:
        """Start timing."""
        self.started_at = perf_counter()

    def stop(self) -> float:
        """Stop timing and return elapsed milliseconds."""
        return (perf_counter() - self.started_at) * 1000
