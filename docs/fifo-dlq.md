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

Use a DLQ when failures are actionable. Do not hide permanent failures behind endless retries.
