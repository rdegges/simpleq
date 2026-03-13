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

## [2.0.0] - 2026-03-13

### Added

- Initial 2.0 release of SimpleQ with SQS-native queues, FIFO and DLQ support,
  async and sync task execution, local cost tracking, Prometheus metrics,
  LocalStack-friendly development, and an in-memory transport for tests.
