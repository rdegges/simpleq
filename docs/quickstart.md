# Quick Start

## Install

```bash
python -m pip install simpleq
```

For local development, run LocalStack and point SimpleQ at it:

```bash
docker run -d --name simpleq-localstack -p 4566:4566 localstack/localstack
export SIMPLEQ_ENDPOINT_URL=http://localhost:4566
```

`AWS_ENDPOINT_URL_SQS` and `AWS_ENDPOINT_URL` are also supported if you prefer
to share the same endpoint configuration with other AWS tooling.

## Sync-first example

```python
from pydantic import BaseModel

from simpleq import SimpleQ

sq = SimpleQ()
queue = sq.queue("emails", dlq=True, wait_seconds=0)


class EmailPayload(BaseModel):
    to: str
    subject: str
    body: str


@sq.task(queue=queue, schema=EmailPayload)
def send_email(payload: EmailPayload) -> None:
    print(payload.to)


def main() -> None:
    send_email.delay_sync(
        to="user@example.com",
        subject="Welcome",
        body="Thanks for signing up.",
    )
    sq.worker(queues=[queue], concurrency=1).work_sync(burst=True)


if __name__ == "__main__":
    main()
```

If you run workers against a network path that can hang, pass
`receive_timeout_seconds` to `sq.worker(...)` so one stalled receive does not
block processing from other queues.
For predictable deploys, `graceful_shutdown_timeout` controls how long worker
shutdown waits for in-flight jobs before cancellation.
Worker runtime options are strict: `concurrency` must be an integer, while
`poll_interval`, `receive_timeout_seconds`, and `graceful_shutdown_timeout`
must be numeric values (booleans are rejected).
Use `SIMPLEQ_POLL_INTERVAL` to set a global default polling interval across
workers.
Use `SIMPLEQ_RECEIVE_TIMEOUT_SECONDS` to set a global default receive timeout
for workers that do not pass `receive_timeout_seconds` explicitly.
Use `SIMPLEQ_SQS_MAX_POOL_CONNECTIONS` to tune boto3 SQS HTTP connection
pooling for higher worker concurrency.

Treat each queue name as a single definition per `SimpleQ` instance. Reuse the
same `queue` object, or pass the same FIFO/DLQ/retry/timing settings each time
you call `sq.queue(...)`; SimpleQ now raises `QueueValidationError` when a later
definition would silently change the existing queue configuration.

## Queue naming rules

SimpleQ validates queue names before sending requests to SQS:

- Standard queues must be `1-80` characters using only letters, numbers, `-`, and `_`
- FIFO queues follow the same character rules and must end with `.fifo`

If the name is invalid, `sq.queue(...)` raises `QueueValidationError` immediately.

## Async example

```python
from pydantic import BaseModel

from simpleq import SimpleQ

sq = SimpleQ()
queue = sq.queue("emails", dlq=True, wait_seconds=0)


class EmailPayload(BaseModel):
    to: str
    subject: str
    body: str


@sq.task(queue=queue, schema=EmailPayload)
async def send_email(payload: EmailPayload) -> None:
    print(payload.to)


async def main() -> None:
    await send_email.delay(
        EmailPayload(
            to="user@example.com",
            subject="Welcome",
            body="Thanks for signing up.",
        )
    )
    await sq.worker(queues=[queue], concurrency=1).work(burst=True)
```

## FIFO queues

```python
orders = sq.queue(
    "orders.fifo",
    fifo=True,
    dlq=True,
    content_based_deduplication=False,
)


@sq.task(
    queue=orders,
    message_group_id=lambda order_id: "customer-123",
    deduplication_id=lambda order_id: f"dedup-{order_id}",
)
def process_order(order_id: str) -> None:
    print(order_id)
```

When a FIFO job is moved to the DLQ or redriven back to the primary queue,
SimpleQ preserves the original `message_group_id` automatically and issues a
fresh deduplication ID for the internal requeue so SQS does not suppress the
message inside the five-minute FIFO deduplication window.

## CLI workflow

```bash
simpleq doctor --check-sqs
simpleq queue create emails --dlq
simpleq worker start -q emails --import-module myapp.tasks --reload
simpleq task list --import-module myapp.tasks
simpleq job enqueue myapp.tasks:send_email --import-module myapp.tasks --payload-json '{"to":"user@example.com","subject":"Hello","body":"World"}'
```

When you import task modules, SimpleQ treats the queue definition in that module as the source of truth. `simpleq worker start -q emails --import-module myapp.tasks` reuses the imported queue's FIFO, DLQ, visibility timeout, and wait settings when there is one configured `emails` queue.
