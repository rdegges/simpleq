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


send_email.delay_sync(
    to="user@example.com",
    subject="Welcome",
    body="Thanks for signing up.",
)
sq.worker(queues=[queue], concurrency=1).work_sync(burst=True)
```

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
