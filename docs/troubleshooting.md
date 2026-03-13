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

## `QueueError` mentions an invalid `receive_message` response

SimpleQ validates SQS `receive_message` payloads and expects `Messages` to be a
list of message objects. This usually points to a proxy, mock, or LocalStack
version returning malformed payloads.

Fix it with one of:

- upgrade LocalStack to the latest stable release
- disable or correct any custom SQS proxy/middleware that rewrites responses
- verify your test double returns `{"Messages": [ ... ]}` with mapping entries

## `QueueError` mentions an invalid `send_message_batch` response

SimpleQ validates SQS `send_message_batch` payloads and expects both
`Successful` and `Failed` to be lists of mapping entries. This usually means a
custom test double, proxy, or outdated emulation layer returned a malformed
batch response.

Fix it with one of:

- upgrade LocalStack to the latest stable release
- verify your mock returns `{"Successful": [...], "Failed": [...]}` lists
- remove middleware that rewrites SQS batch response structures

## `QueueError` mentions an invalid `list_queues` response

SimpleQ validates SQS `list_queues` payloads and expects `QueueUrls` to be a
list of non-empty strings and `NextToken` to be a non-empty string when
present. This usually indicates a malformed emulator/proxy response.

Fix it with one of:

- upgrade LocalStack to the latest stable release
- ensure your test double returns `{"QueueUrls": ["..."], "NextToken": "..."}` shapes
- remove middleware that rewrites queue listing payloads
