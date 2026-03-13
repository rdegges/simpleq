# Compatibility

## Runtime matrix

| Component | Supported |
| --- | --- |
| Python | 3.10, 3.11, 3.12, 3.13 |
| boto3 | `>=1.40.0,<2.0.0` |
| botocore | `>=1.40.0,<2.0.0` |
| LocalStack | 4.4.x in CI and dev compose |

## Notes

- Sync wrappers are available everywhere, even though the core queue and worker APIs are async-first.
- The default transport is lazy. Constructing `SimpleQ()` no longer forces an immediate boto3 client creation.
- Use `InMemoryTransport` for unit tests and LocalStack for integration tests.

## AWS usage expectations

- Standard and FIFO SQS queues are both part of the supported runtime surface.
- CI exercises LocalStack 4.4.x plus the in-memory transport; real AWS smoke tests remain opt-in.
- SimpleQ expects an SQS-compatible endpoint. Other brokers and generic queue emulators are out of scope.
