"""ECS/Fargate worker entrypoint example for SimpleQ."""

from __future__ import annotations

from simpleq import SimpleQ

sq = SimpleQ()
emails = sq.queue("emails", dlq=True)
orders = sq.queue("orders.fifo", fifo=True, dlq=True, content_based_deduplication=True)


def main() -> None:
    sq.worker(queues=[emails, orders], concurrency=10).work_sync()


if __name__ == "__main__":
    main()
