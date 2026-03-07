# IAM Guide

SimpleQ only needs SQS permissions for its queues plus optional observability integrations you enable yourself.

Minimum SQS actions for workers:

- `sqs:CreateQueue`
- `sqs:GetQueueUrl`
- `sqs:GetQueueAttributes`
- `sqs:SetQueueAttributes`
- `sqs:ListQueues`
- `sqs:SendMessage`
- `sqs:SendMessageBatch`
- `sqs:ReceiveMessage`
- `sqs:DeleteMessage`
- `sqs:ChangeMessageVisibility`
- `sqs:PurgeQueue`
- `sqs:DeleteQueue`

For live smoke tests, start from `tests/live/iam-policy.json`.

Prefer queue-specific ARNs over wildcard access in production.
