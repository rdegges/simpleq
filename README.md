# SimpleQ

The Python task queue for AWS. Dead simple. SQS native. Zero infrastructure.

```bash
pip install simpleq
```


## Quickstart

Define a task:

```python
# tasks.py
from simpleq import SimpleQ

sq = SimpleQ()

@sq.task
def send_email(to, subject, body):
    print(f"Sending email to {to}: {subject}")
```

Enqueue it from anywhere:

```python
from tasks import send_email

send_email.delay("user@example.com", "Welcome!", "Thanks for signing up.")
```

Start a worker:

```bash
simpleq worker -a tasks
```

That's it. No Redis. No RabbitMQ. No config files. Just SQS.


## Why SimpleQ?

Every Python task queue makes you manage infrastructure:

- **Celery** needs Redis or RabbitMQ, a config file, and a PhD in distributed systems.
- **RQ** needs Redis.
- **Dramatiq** needs RabbitMQ or Redis.

If you're on AWS, you already have SQS. It's serverless, infinitely scalable, and costs
about $0.40 per million messages. SimpleQ treats SQS as a first-class citizen — not just
"another supported broker."

**SimpleQ is for developers who want background jobs without background infrastructure.**


## Features

### Tasks

Decorate any function to make it a background task:

```python
@sq.task
def process_image(image_url: str, width: int, height: int):
    # Runs in the background on a worker
    ...
```

Enqueue it:

```python
process_image.delay("https://example.com/photo.jpg", width=800, height=600)
```

Run it locally (skip SQS, useful for testing):

```python
result = process_image.apply("https://example.com/photo.jpg", width=800, height=600)
```

### Queues

By default, tasks go to a queue named `default`. Use named queues to organize work:

```python
@sq.task(queue="emails")
def send_email(to, subject, body):
    ...

@sq.task(queue="images")
def process_image(url):
    ...
```

Queues are auto-created on first use. To disable this:

```python
sq = SimpleQ(auto_create=False)  # Raises an error if a queue doesn't exist
```

### Worker

Use the CLI to start a worker:

```bash
simpleq worker -a tasks
```

Or use the Python API directly:

```python
from simpleq import Worker

worker = Worker([sq.queue("emails"), sq.queue("images")])
worker.work()                 # Run forever
worker.work(burst=True)       # Process all pending jobs, then exit
```

Workers handle SIGINT and SIGTERM gracefully — the current job finishes, then the
worker stops polling and shuts down.

### Retries

```python
@sq.task(retries=3, backoff="exponential")
def call_external_api(url):
    response = requests.get(url)
    response.raise_for_status()
```

Failed tasks retry automatically with exponential backoff. After all retries are
exhausted, the task moves to the dead letter queue (if enabled).

### Dead Letter Queue

```python
sq = SimpleQ(dead_letter_queue=True)
```

Failed tasks are automatically moved to a DLQ after exhausting retries. Inspect and
redrive them:

```bash
simpleq queue dlq default         # List failed messages
simpleq queue redrive default     # Retry all failed messages
```

### FIFO Queues

When ordering matters:

```python
@sq.task(queue="orders", fifo=True, message_group_id=lambda order_id: order_id)
def process_order(order_id: str):
    ...
```

Messages within a group are processed in order. Automatic deduplication prevents
double-processing.

### Delayed Jobs

```python
# Process this in 5 minutes
send_email.delay("user@example.com", "Reminder", "...", _delay_seconds=300)
```

Uses SQS delay seconds natively. Max 15 minutes (SQS limit).

### Type-Safe Tasks

Use Pydantic models for validated task arguments:

```python
from pydantic import BaseModel

class EmailTask(BaseModel):
    to: str
    subject: str
    body: str

@sq.task
def send_email(task: EmailTask):
    # Arguments are validated against the model before the task runs
    ...

send_email.delay(EmailTask(to="user@example.com", subject="Hello", body="Welcome!"))
```

Pydantic is optional — plain arguments work fine for simple tasks.

### Serialization

Task arguments are serialized with pickle, so you can pass any picklable Python object:

```python
@sq.task
def train_model(dataset: pd.DataFrame, config: dict):
    # DataFrames, dicts, custom classes — anything picklable works
    ...
```

Note: SQS messages have a 256KB size limit. SimpleQ checks this before sending and
raises a clear error if your payload is too large.

### Async Tasks

```python
@sq.task(async_=True)
async def fetch_data(url: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()
```

Async tasks run in the worker's event loop. The `async_=True` flag is required — this
keeps the common case simple and makes async an explicit opt-in.

### Cost Tracking

```bash
$ simpleq stats

Queue       Messages    Sent    Received    Cost (est.)
default     1,204       3,891   7,782       $0.0047
emails      89          267     534         $0.0003
                                     Total: $0.0050
```

SQS is cheap, but SimpleQ tracks every API call so you always know what you're spending.


## CLI

```bash
# Workers
simpleq worker -a myapp.tasks                  # Start a worker (all queues)
simpleq worker -a myapp.tasks -q emails         # Specific queue only
simpleq worker -a myapp.tasks -c 20             # 20 concurrent jobs

# Queues
simpleq queue list                              # List all queues
simpleq queue create notifications              # Create a queue
simpleq queue stats emails                      # Queue statistics
simpleq queue purge emails                      # Delete all messages
simpleq queue delete emails                     # Delete the queue

# Dead Letter Queues
simpleq queue dlq emails                        # List failed messages
simpleq queue redrive emails                    # Retry all failed messages

# Cost
simpleq stats                                   # Cost report across all queues
```


## Configuration

### AWS Credentials

SimpleQ uses your existing AWS credentials. Any of these work:

```bash
# Environment variables
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx
export AWS_DEFAULT_REGION=us-east-1

# AWS CLI profile
aws configure

# IAM role (EC2, ECS, Lambda) — just works, no config needed
```

### Options

```python
sq = SimpleQ(
    region="us-west-2",              # AWS region (default: us-east-1)
    dead_letter_queue=True,          # Enable DLQ for all queues (default: False)
    visibility_timeout=300,          # Seconds before unfinished jobs retry (default: 30)
    auto_create=False,               # Don't auto-create queues (default: True)
)
```

### Testing

SimpleQ's test suite uses [moto](https://github.com/getmoto/moto) to mock SQS. Use the
same approach in your own tests:

```python
import pytest
from moto import mock_aws
from tasks import sq, send_email

@mock_aws
def test_send_email_enqueues():
    send_email.delay("user@example.com", "Hello", "Welcome!")
    assert sq.queue("emails").num_jobs() == 1
```

No AWS credentials or running services needed — moto handles everything in-process.


## Lambda Mode *(coming soon)*

The zero-config deployment that makes SimpleQ unique:

```python
@sq.task(lambda_=True)
def process_image(image_url: str):
    # This runs as an AWS Lambda function
    ...
```

```bash
simpleq deploy
```

One decorator. One command. Your task is now a Lambda function triggered by SQS —
infinite scale, zero infrastructure, pennies in cost.


## Installation

```bash
pip install simpleq
```

Requires Python 3.10+ and an AWS account.


## License

ISC
