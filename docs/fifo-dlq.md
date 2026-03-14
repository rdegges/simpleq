# FIFO and DLQ Cookbook

## FIFO queues

Use FIFO when ordering matters within a logical group.

```python
orders = sq.queue(
    "orders.fifo",
    fifo=True,
    dlq=True,
    content_based_deduplication=False,
)
```

Rules to remember:

- FIFO queue names must end with `.fifo`
- every message needs a `message_group_id`
- if content-based deduplication is disabled, every message also needs a `deduplication_id`
- `message_group_id` and `deduplication_id` must be non-empty strings with at most 128 characters
- FIFO routing IDs may only include letters, numbers, and punctuation (no spaces, tabs, or newlines)
- SimpleQ preserves FIFO routing metadata when a message is received, moved to a
  DLQ, or redriven back to the primary queue
- redriven FIFO messages get a fresh internal deduplication ID so AWS does not
  drop them inside the five-minute deduplication window
- `Job.metadata` is reconciled from the current SQS envelope on receive, so the
  routing IDs you inspect after DLQ moves or redrives match the actual message
  state in SQS
- for idempotent FIFO receive retries, pass `receive_request_attempt_id` to
  `queue.receive(...)` so SQS can deduplicate retry attempts
- `Worker` now auto-generates `receive_request_attempt_id` values for FIFO
  polls, so idempotent receive retries are enabled by default in worker loops

Example:

```python
jobs = await orders.receive(
    max_messages=10,
    wait_seconds=20,
    receive_request_attempt_id="poller-attempt-42",
)
```

## DLQs

Enable DLQs per queue:

```python
queue = sq.queue("emails", dlq=True, max_retries=3)
```

Inspect and redrive:

```bash
simpleq dlq list emails
simpleq dlq redrive emails
```

Both commands accept `--limit`, which must be `>= 1`.

Use a DLQ when failures are actionable. Do not hide permanent failures behind endless retries.
