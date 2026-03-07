# Deployment

## ECS or Fargate workers

Run a long-lived worker container:

```bash
simpleq worker start -q emails -q orders.fifo --import-module myapp.tasks
```

Recommended settings:

- set `SIMPLEQ_CONCURRENCY`
- set `SIMPLEQ_LOG_LEVEL=INFO`
- expose `/metrics` through the dashboard or a sidecar if you scrape Prometheus

## Lambda producers

Lambda is a good fit for enqueue-only workloads. Use Lambda to place jobs on SQS and ECS/Fargate to consume them.

See `examples/lambda_handler.py`.

## Queue provisioning

Provision queues with infrastructure as code. The examples directory includes:

- `examples/cdk_stack.py`
- `examples/terraform.tf`

Provision queues ahead of time in production even though SimpleQ can create them on demand. Explicit infrastructure remains easier to audit.
