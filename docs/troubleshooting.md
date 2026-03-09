# Troubleshooting

## `SimpleQ()` works, but enqueueing fails with AWS credential errors

You created the client successfully, but the first real SQS call still needs credentials or a LocalStack endpoint.

Fix it with one of:

- set `SIMPLEQ_ENDPOINT_URL=http://localhost:4566`
- or set `AWS_ENDPOINT_URL_SQS=http://localhost:4566`
- provide AWS credentials and region
- use `InMemoryTransport` in tests

## `task list` shows no tasks

`simpleq task list` only shows tasks that were registered by imported modules. Make sure your module actually defines tasks with `@sq.task(...)` and pass it with `--import-module`.

## `job enqueue` fails validation

Prefer `--payload-json` for schema tasks. If the JSON is an object, SimpleQ passes it as keyword arguments; if it is an array, it passes positional arguments.

## `Queue '...' is already configured differently on this SimpleQ instance`

SimpleQ now treats each queue name as a single source of truth inside one
client. This error means the same queue name was requested again with different
settings such as FIFO vs. standard, DLQ enablement, retry count, visibility
timeout, wait time, or tags.

Fix it with one of:

- create the queue once and reuse that `Queue` object everywhere
- keep repeated `sq.queue(...)` calls identical
- use a different queue name if you truly need a separate definition

## Integration tests fail on the host but pass in Docker

Confirm that LocalStack is reachable on `http://localhost:4566`. The test suite uses that endpoint automatically on the host.
