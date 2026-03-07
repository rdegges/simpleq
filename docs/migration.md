# Migration Guide

SimpleQ v2 is a clean break from the original Python 2 / `boto` prototype.

## Breaking changes

- Python 3.10+ is required.
- `boto` is gone. The library now targets `boto3`.
- `simpleq.jobs`, `simpleq.queues`, and `simpleq.workers` are removed.
- Tasks are registered by import path, not by serializing raw callables.
- Queue and worker APIs are async-first, with `*_sync` wrappers for synchronous call sites.

## Before

```python
from simpleq.jobs import Job
from simpleq.queues import Queue
from simpleq.workers import Worker
```

## After

```python
from simpleq import SimpleQ

sq = SimpleQ()
queue = sq.queue("emails", dlq=True)


@sq.task(queue=queue)
async def send_email(address: str) -> None:
    print(address)


await send_email.delay("user@example.com")
await sq.worker(queues=[queue]).work()
```
