# Benchmarks

SimpleQ ships with a LocalStack-backed benchmark smoke suite in `tests/performance/`.

Run it with:

```bash
docker compose up -d localstack
uv run pytest tests/performance -m performance
```

The benchmark harness tracks:

- enqueue throughput
- processing throughput
- requests per logical job

Positioning guidance:

- compare SimpleQ against raw boto3 SQS calls when you want to measure framework overhead
- compare against Celery-on-SQS only in a dedicated benchmark environment, because the broker adapter and worker model introduce different operational tradeoffs

The right goal is not to beat raw SQS on every micro-benchmark. The goal is to stay close enough to raw SQS while giving you retries, schema validation, FIFO helpers, DLQ tooling, and observability.
