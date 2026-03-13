# Stability and Deprecation Policy

## Supported surface

The following interfaces are treated as public API in the 2.x series:

- `simpleq.SimpleQ`
- `simpleq.Queue`
- `simpleq.Worker`
- `simpleq.Job`
- `simpleq.TaskHandle`
- `simpleq.InMemoryTransport`
- documented CLI commands under `simpleq ...`
- documented configuration keys and environment variables

These interfaces are expected to remain source-compatible across 2.x releases
except for bug fixes, security patches, or clearly documented deprecations.

## Internal surface

Everything else should be treated as internal implementation detail, including:

- private names such as `_sync`, `_StoredQueue`, and `_StoredMessage`
- transport internals in `simpleq.sqs`
- helper functions used only by the CLI implementation
- undocumented module-level utilities

Internal APIs may change in any minor release when needed for maintenance,
typing improvements, or reliability work.

## Deprecation policy

- New deprecations are announced in `CHANGELOG.md` before removal.
- Deprecated public APIs stay available for at least one minor release.
- Removals happen only in a major release unless a security issue or data-loss
  bug requires an emergency break.
- When there is a replacement path, the changelog and docs call it out directly.

## Compatibility promises

- Python `3.10` through `3.13` are supported in CI.
- The primary production target is AWS SQS.
- LocalStack and `InMemoryTransport` are supported for development and tests,
  with behavior differences documented when the test transport intentionally
  does not mirror SQS.
