"""FIFO SimpleQ example."""

from __future__ import annotations

from simpleq import SimpleQ

sq = SimpleQ()
queue = sq.queue(
    "orders.fifo",
    fifo=True,
    dlq=True,
    content_based_deduplication=False,
    wait_seconds=0,
)


@sq.task(
    queue=queue,
    message_group_id=lambda _order_id: "customer-1",
    deduplication_id=lambda order_id: f"order-{order_id}",
)
def process_order(order_id: str) -> None:
    print(f"processed {order_id}")


def main() -> None:
    for order_id in ["order-1", "order-2", "order-3"]:
        process_order.delay_sync(order_id)
    sq.worker(queues=[queue], concurrency=1).work_sync(burst=True)


if __name__ == "__main__":
    main()
