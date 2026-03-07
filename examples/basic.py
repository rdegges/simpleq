"""Basic SimpleQ example."""

from __future__ import annotations

from simpleq import SimpleQ

sq = SimpleQ()
queue = sq.queue("basic-example", dlq=True, wait_seconds=0)


@sq.task(queue=queue)
def send_email(address: str) -> None:
    print(f"sent {address}")


def main() -> None:
    send_email.delay_sync("user@example.com")
    sq.worker(queues=[queue], concurrency=1).work_sync(burst=True)


if __name__ == "__main__":
    main()
