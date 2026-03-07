# SimpleQ

SimpleQ is an SQS-native task queue for Python 3.10+.

It is built for teams that already run on AWS and want queue behavior to stay explicit:

- SQS queue names remain visible
- FIFO groups and deduplication IDs stay first-class
- DLQs and redrive are part of the core model
- long polling, batching, and visibility timeouts are defaults, not afterthoughts

## Core concepts

- `SimpleQ` owns configuration, task registration, and observability.
- `Queue` manages queue creation, receive/send flows, and DLQ behavior.
- `TaskHandle` wraps a callable and adds `delay()` and `delay_sync()`.
- `Worker` polls queues, executes tasks, retries failures, and redrives to DLQs.
- `InMemoryTransport` gives you a zero-AWS test transport for unit tests and local examples.

## Recommended path

1. Read [Quick Start](quickstart.md).
2. Use [Testing](testing.md) to set up unit tests and LocalStack integration tests.
3. Use [Deployment](deployment.md) for ECS, Lambda producers, and queue provisioning.
4. Use [FIFO and DLQ Cookbook](fifo-dlq.md) when you need ordering or redrive behavior.

## Positioning

SimpleQ is not trying to be a universal broker abstraction. If you need Redis, RabbitMQ, Kafka, and SQS all hidden behind one API, use a different tool. If you want SQS to stay native and pleasant in Python, SimpleQ is the right target.
