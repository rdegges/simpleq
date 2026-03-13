# Testing

SimpleQ is designed for three testing layers.

## Unit tests

Use the built-in in-memory transport when you want deterministic tests with no AWS credentials and no Docker dependency.

```python
from simpleq import SimpleQ
from simpleq.testing import InMemoryTransport

sq = SimpleQ(transport=InMemoryTransport())
queue = sq.queue("emails")
```

`InMemoryTransport` now simulates FIFO deduplication behavior too:

- explicit `deduplication_id` values are deduplicated for 5 minutes
- when `content_based_deduplication=True`, duplicate message bodies are deduplicated
- once a FIFO message group has an in-flight message, later messages in that
  group stay hidden until the earlier message is acked or its visibility expires
- FIFO `receive_request_attempt_id` retries replay the same receive result for
  5 minutes unless message state changes (ack/visibility updates/purge)
- `receive(..., wait_seconds=...)` now long-polls for delayed messages instead of
  returning early when a message becomes visible during the poll window

The supported contract is encoded directly in the test suite:

- [tests/unit/test_transport_contract.py](/Users/rdegges/Code/rdegges/simpleq/tests/unit/test_transport_contract.py)
- [tests/integration/test_transport_contract_integration.py](/Users/rdegges/Code/rdegges/simpleq/tests/integration/test_transport_contract_integration.py)

The cross-transport parity test covers the subset LocalStack reliably mirrors:
FIFO ordering/blocking, deduplication, and delayed long-poll behavior. The
`ReceiveRequestAttemptId` replay contract remains covered at the in-memory layer,
because LocalStack does not currently emulate that FIFO retry behavior
consistently.

`InMemoryTransport` is intentionally not a full AWS emulator. It does not try to
model:

- IAM, credentials, or network failures
- AWS-managed queue attributes outside the subset SimpleQ reads and writes
- approximate CloudWatch/SQS counters beyond the local bookkeeping SimpleQ uses
- distributed multi-process consumer races across multiple runtimes
- service-generated AWS metadata that SimpleQ does not depend on directly

Recommended targets:

- task serialization and schema validation
- retry logic
- queue bookkeeping
- CLI commands

Run them with:

```bash
uv sync --extra dev
uv run pytest tests/unit
```

## Integration tests

Use LocalStack when you want real SQS semantics.

```bash
docker compose up -d localstack
uv run pytest tests/integration
```

The test suite now auto-selects `http://localhost:4566` on the host and `http://localstack:4566` inside the dev container.
If LocalStack is not reachable, integration tests are skipped with a clear
message instead of failing with connection errors.

## Live AWS smoke tests

Live tests remain opt-in and require explicit credentials:

```bash
uv run pytest tests/live --run-live-aws -m live
```

Use these sparingly for final confidence, not for daily feedback loops.
