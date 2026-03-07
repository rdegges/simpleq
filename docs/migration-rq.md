# Migrating from RQ

RQ users usually adopt SimpleQ because they want similar ergonomics without running Redis.

## Concept mapping

| RQ | SimpleQ |
| --- | --- |
| Redis queue | SQS queue |
| `enqueue()` | `delay()` or `job enqueue` |
| worker process | `simpleq worker start` |
| failed job queue | DLQ |

## Biggest differences

- SimpleQ is async-first but keeps sync wrappers for simple scripts and management commands.
- SQS visibility timeouts replace Redis reservation semantics.
- DLQs are explicit AWS resources instead of an internal failed-job list.

## Migration strategy

1. Keep task import paths stable.
2. Replace RQ enqueue calls with SimpleQ task handles.
3. Start with standard queues, then adopt FIFO only where ordering is required.
