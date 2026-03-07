# Migrating from Celery

SimpleQ is the right move when your Celery deployment already depends on AWS SQS and you want less abstraction, fewer moving parts, and clearer queue semantics.

## Concept mapping

| Celery | SimpleQ |
| --- | --- |
| `Celery()` app | `SimpleQ()` |
| task decorator | `@sq.task(...)` |
| `delay()` | `delay()` or `delay_sync()` |
| worker | `sq.worker(...).work()` |
| retries | queue or task `max_retries` plus backoff |
| dead letter handling | built-in DLQ queue support |

## Biggest differences

- SimpleQ keeps queue names and SQS features explicit.
- There is no result backend by default.
- FIFO queues and deduplication are first-class because SQS makes them first-class.

## Migration strategy

1. Pick one Celery queue that already uses SQS.
2. Re-register those tasks with `@sq.task(...)`.
3. Move producers first with `job enqueue` or direct `delay()` calls.
4. Move workers next and verify retry/DLQ behavior in LocalStack.
