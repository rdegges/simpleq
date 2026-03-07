# Deployment

## ECS or Fargate workers

Run a long-lived worker container:

```bash
simpleq worker start -q emails -q orders.fifo --import-module myapp.tasks
```

Recommended settings:

- set `SIMPLEQ_CONCURRENCY`
- set `SIMPLEQ_LOG_LEVEL=INFO`
- set boolean flags (`SIMPLEQ_ENABLE_METRICS`, `SIMPLEQ_ENABLE_TRACING`,
  `SIMPLEQ_COST_TRACKING`) with `1/0`, `true/false`, `yes/no`, or `on/off`
- expose `/metrics` through the dashboard or a sidecar if you scrape Prometheus

## Lambda producers

Lambda is a good fit for enqueue-only workloads. Use Lambda to place jobs on SQS and ECS/Fargate to consume them.

See `examples/lambda_handler.py`.

## Queue provisioning

Provision queues with infrastructure as code. The examples directory includes:

- `examples/cdk_stack.py`
- `examples/terraform.tf`

Provision queues ahead of time in production even though SimpleQ can create them on demand. Explicit infrastructure remains easier to audit.

When a queue already exists, `Queue.ensure_exists()` reconciles mutable SQS
attributes such as `VisibilityTimeout`, `ReceiveMessageWaitTimeSeconds`,
`RedrivePolicy`, and FIFO content-based deduplication. Immutable properties
like the queue name and standard-vs-FIFO type still need to be provisioned
correctly up front.
