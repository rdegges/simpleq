"""Cost tracker for SQS API call accounting."""

from __future__ import annotations

from dataclasses import dataclass, field

# SQS pricing: $0.40 per million requests (standard queues)
# https://aws.amazon.com/sqs/pricing/
SQS_PRICE_PER_REQUEST = 0.40 / 1_000_000


@dataclass
class QueueCost:
    """Cost metrics for a single queue."""

    send_requests: int = 0
    receive_requests: int = 0
    delete_requests: int = 0
    other_requests: int = 0

    @property
    def total_requests(self) -> int:
        return (
            self.send_requests
            + self.receive_requests
            + self.delete_requests
            + self.other_requests
        )

    @property
    def estimated_cost(self) -> float:
        return self.total_requests * SQS_PRICE_PER_REQUEST


class CostTracker:
    """Tracks SQS API calls and estimates cost per queue."""

    def __init__(self) -> None:
        self._queues: dict[str, QueueCost] = {}

    def _ensure_queue(self, queue_name: str) -> QueueCost:
        if queue_name not in self._queues:
            self._queues[queue_name] = QueueCost()
        return self._queues[queue_name]

    def track_send(self, queue_name: str, count: int = 1) -> None:
        self._ensure_queue(queue_name).send_requests += count

    def track_receive(self, queue_name: str, count: int = 1) -> None:
        self._ensure_queue(queue_name).receive_requests += count

    def track_delete(self, queue_name: str, count: int = 1) -> None:
        self._ensure_queue(queue_name).delete_requests += count

    def track_other(self, queue_name: str, count: int = 1) -> None:
        self._ensure_queue(queue_name).other_requests += count

    def get_queue_cost(self, queue_name: str) -> QueueCost:
        return self._ensure_queue(queue_name)

    def get_all(self) -> dict[str, QueueCost]:
        return dict(self._queues)

    @property
    def total_cost(self) -> float:
        return sum(qc.estimated_cost for qc in self._queues.values())

    def reset(self) -> None:
        self._queues.clear()
