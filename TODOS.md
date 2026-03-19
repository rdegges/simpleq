# SimpleQ TODOs

## Core Implementation Gaps

### SQS Message Size Validation
**Priority:** High
**What:** Check serialized payload size before sending to SQS. Raise a clear error if >256KB with guidance to use S3 for large data.
**Why:** SQS silently rejects oversized messages with a generic error. A clear error message is critical DX.
**Depends on:** Job serialization implementation.

### Visibility Timeout Heartbeat (Long-Running Tasks)
**Priority:** High
**What:** Worker should extend SQS visibility timeout while a task is running, preventing duplicate execution for tasks >30s.
**Why:** Without this, any task taking longer than the visibility timeout (default 30s) gets re-delivered to another worker, causing duplicate execution. This is a well-known SQS gotcha.
**Depends on:** Worker implementation.

### DLQ Existence Validation
**Priority:** Medium
**What:** Validate DLQ exists before reading from it or redriving. Show a clear error like "No DLQ configured for queue X. Create one with Queue('X', dlq=True)." instead of a raw AWS error.
**Why:** Users may call `queue.get_dlq_jobs()` on a queue without DLQ enabled.
**Depends on:** Queue DLQ implementation.

## Design

### Branded AWS Credential Error
**Priority:** High
**What:** Catch boto3 `NoCredentialsError` and show a branded, step-by-step setup guide instead of a raw traceback. Include export commands and `aws configure` reference.
**Why:** Missing AWS credentials is the #1 first-run failure. A helpful error is the difference between "this library sucks" and "oh I just need to set my creds."
**Depends on:** Config module implementation.

## Post-Core Features

### Zero-Config Lambda Mode
**Priority:** High (post-core)
**What:** `@sq.task(lambda_=True)` deploys the task handler as an AWS Lambda function with SQS trigger. `simpleq deploy` CLI command handles IAM roles, Lambda zip, and SQS event source mapping.
**Why:** The moonshot feature that differentiates SimpleQ from every other Python queue library. "One decorator, zero infrastructure."
**Depends on:** Core implementation complete and stable. API must be designed to accommodate this from day 1 even if shipped later.
