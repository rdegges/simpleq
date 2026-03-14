# Changelog

All notable changes to SimpleQ are documented in this file.

## [Unreleased]

### Added

- Executable smoke tests for `examples/basic.py`, the `simpleq init` scaffold,
  the README quick start, and the sync quick start doc.
- A published stability and deprecation policy in `docs/stability.md`.
- A maintainer-facing release checklist in `RELEASING.md`.
- Suggested issue labels in `.github/labels.yml` for quality work tracking.

### Changed

- Coverage expectations are now enforced at a sustainable `95%` threshold in CI.
- CLI, in-memory transport, queue, SQS, and worker tests cover more failure and
  helper branches so the quality gate matches the real repo state.
- Quick-start snippets in the README and docs now run as complete scripts.
- Worker retry metrics now report `failure` (instead of `dlq`) when retries are
  exhausted on queues without DLQ support.
- `SQSClient.ensure_queue()` now retries once with a refreshed queue URL when a
  cached URL goes stale during attribute/tag reconciliation, reducing flakiness
  after out-of-band queue deletion or recreation.
- `SimpleQConfig.from_overrides()` now ignores whitespace-only
  `SIMPLEQ_DEFAULT_QUEUE` values and falls back to `default`, preventing boot
  failures from blank environment injection.
- FIFO `message_group_id` / `deduplication_id` validation now rejects
  whitespace and unsupported characters up front, preventing runtime
  `SendMessage` failures from leaking out of AWS.
- `SimpleQ.list_queues()` now normalizes blank prefixes and defensively
  re-filters parsed queue names client-side, preventing unrelated queues from
  leaking through non-compliant broker responses.
- `SimpleQConfig.from_overrides()` now treats blank
  `SIMPLEQ_RECEIVE_TIMEOUT_SECONDS` values as unset, avoiding startup failures
  from empty environment injection.
- Numeric config env vars now treat blank values as unset defaults (instead of
  raising parse errors), hardening startup in CI/container environments that
  inject empty env entries.
- Boolean config env vars now treat blank values as unset defaults, avoiding
  startup failures when CI/container tooling injects empty feature flags.
- Queue deletion now retries once after stale-URL invalidation even when the
  refreshed queue URL string is unchanged, reducing false no-op deletes during
  eventual-consistency windows.
- LocalStack endpoint auto-detection now ignores blank `LOCALSTACK_HOSTNAME`
  and `LOCALSTACK_HOST` env values, preventing malformed `http://:4566`
  endpoints and improving startup resilience in CI/container environments.
- Worker shutdown now exits immediately after receive-task cancellation instead
  of waiting an extra `poll_interval`, improving stop latency for idle workers.
- `SQSClient.purge_queue()` now maps AWS `PurgeQueueInProgress` failures to a
  clear, actionable `QueueError`, making purge cooldown handling easier to
  diagnose in production and CI runs.
- Worker non-retryable failure handling now treats `ack()` errors as explicit
  `ack_error` outcomes (with actionable `queue_ack_failed` logs) instead of
  generic `failure_handler_error`, improving production diagnostics and metric
  accuracy.
- `default_queue_name` / `SIMPLEQ_DEFAULT_QUEUE` now accept queue names, SQS
  queue URLs, and SQS queue ARNs (normalized to queue names at config load),
  which simplifies deploying workers from infrastructure outputs without manual
  string rewriting.
- Float config values now reject non-finite inputs (`NaN`, `Infinity`) for
  `poll_interval`, `receive_timeout_seconds`, and `sqs_price_per_million`,
  preventing unstable runtime behavior from malformed environment overrides.
- Worker construction now rejects non-finite runtime overrides (`NaN`,
  `Infinity`) for `poll_interval`, `receive_timeout_seconds`, and
  `graceful_shutdown_timeout`, preventing undefined timing behavior when
  workers are created directly in application code.
- FIFO worker polling now attaches a per-receive
  `ReceiveRequestAttemptId` automatically, reducing duplicate deliveries on
  transient receive retries without requiring application-managed attempt IDs.

## [2.0.0] - 2026-03-13

### Added

- Initial 2.0 release of SimpleQ with SQS-native queues, FIFO and DLQ support,
  async and sync task execution, local cost tracking, Prometheus metrics,
  LocalStack-friendly development, and an in-memory transport for tests.
