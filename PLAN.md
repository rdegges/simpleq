# SimpleQ v2.0: Master Implementation Plan

**Date:** March 1, 2026
**Version:** 2.0.0
**Status:** Planning Phase
**Target Launch:** May 2026 (10 weeks)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Strategic Vision](#strategic-vision)
3. [Competitive Analysis Summary](#competitive-analysis-summary)
4. [Technical Architecture](#technical-architecture)
5. [Detailed Implementation Plan](#detailed-implementation-plan)
6. [API Design](#api-design)
7. [Performance Targets](#performance-targets)
8. [Testing Strategy](#testing-strategy)
9. [Documentation Plan](#documentation-plan)
10. [Launch Strategy](#launch-strategy)
11. [Success Metrics](#success-metrics)
12. [Risk Management](#risk-management)

---

## Executive Summary

### The Opportunity

After comprehensive research of the Python task queue ecosystem in 2026, we've identified a critical market gap: **no library offers a truly serverless-first, SQS-native, async-ready task queue** that combines RQ's simplicity with enterprise reliability.

### Current State

- **Celery:** 28M downloads/month but complex, slow, poor defaults
- **Taskiq:** Fastest but generic multi-broker (SQS not optimized)
- **Dramatiq:** Great reliability but requires infrastructure
- **RQ:** Simple but slow, no async, Redis-only

### SimpleQ's Position

**"The Python task queue for AWS. Zero infrastructure, infinite scale, pennies in cost."**

We will be:
1. **Simplest** - RQ-level developer experience
2. **Cheapest** - Serverless, cost-optimized, built-in cost tracking
3. **Most AWS-native** - FIFO, deduplication, X-Ray, CloudWatch
4. **Most modern** - Async-first, type-safe, Python 3.10+
5. **Most reliable** - DLQ, retries, monitoring built-in

### Timeline

**10 weeks to v2.0 launch:**
- Weeks 1-2: Foundation (Python 3, boto3, async core)
- Weeks 3-4: SQS-native features (FIFO, DLQ, cost tracking)
- Weeks 5-6: Developer experience (CLI, dashboard, integrations)
- Weeks 7-8: Advanced features (retries, scheduling, multi-region)
- Weeks 9-10: Documentation and launch

---

## Strategic Vision

### Mission

Build the most developer-friendly, cost-effective, AWS-native task queue for Python, making background job processing on AWS as simple as possible while providing enterprise-grade reliability.

### Core Principles

1. **Simplicity First** - Five lines of code from install to first job
2. **AWS-Native** - Leverage SQS features, don't abstract them away
3. **Cost-Conscious** - Track, optimize, and report on costs automatically
4. **Type-Safe** - Modern Python with full type hints and validation
5. **Async-First** - Native asyncio, not middleware
6. **Production-Ready** - DLQ, monitoring, observability out-of-box

### Non-Goals

We explicitly choose NOT to:
- ❌ Support multiple brokers (SQS only)
- ❌ Support multi-cloud (AWS only)
- ❌ Build complex workflow orchestration (use Step Functions)
- ❌ Support Python 2 or Python 3.9
- ❌ Compete on feature breadth (we compete on focus)

---

## Competitive Analysis Summary

### Feature Matrix: SimpleQ vs Competition

| Feature | SimpleQ v2 | Celery | Taskiq | Dramatiq | RQ |
|---------|-----------|--------|--------|----------|-----|
| **Setup Time** | ⚡ <5 min | ❌ Hours | ⚠️ 30 min | ⚠️ 30 min | ⚡ <5 min |
| **Infrastructure** | ✅ None | ❌ Heavy | ⚠️ Varies | ❌ Required | ❌ Redis |
| **Native Async** | ✅ Yes | ❌ No | ✅ Yes | ❌ No | ❌ No |
| **Type Safety** | ✅ Pydantic | ❌ No | ⚠️ Partial | ❌ No | ❌ No |
| **Performance** | 🎯 Top 3 | ⚠️ Moderate | ✅ #1 | ✅ Fast | ❌ Slow |
| **Native DLQ** | ✅ SQS DLQ | ⚠️ Manual | ⚠️ Varies | ✅ Yes | ❌ No |
| **Cost Tracking** | ✅ Built-in | ❌ No | ❌ No | ❌ No | ❌ No |
| **FIFO Queues** | ✅ Yes | ❌ No | ❌ No | ❌ No | ❌ No |
| **Deduplication** | ✅ Native | ❌ No | ❌ No | ❌ No | ❌ No |
| **Dashboard** | ✅ Built-in | ✅ Flower | ⚠️ 3rd | ⚠️ Alpha | ⚠️ 3rd |
| **AWS Integration** | ✅ Deep | ⚠️ Basic | ⚠️ Basic | ❌ No | ❌ No |
| **Learning Curve** | ✅ Low | ❌ High | ⚠️ Med | ⚠️ Med | ✅ Low |

### Our Unique Advantages

**Features NO competitor has:**
1. SQS FIFO queue support with message groups
2. Built-in cost tracking and optimization dashboard
3. Native SQS message deduplication
4. Zero-config localstack integration for local dev
5. Pydantic schemas for type-safe tasks
6. AWS X-Ray distributed tracing built-in

### Target Audience

**Primary:**
- Cloud-native teams on AWS (Lambda, ECS, Fargate, EC2)
- Startups optimizing costs
- FastAPI/async Python applications
- Teams migrating from self-hosted queues to serverless

**Secondary:**
- Teams frustrated with Celery complexity
- Developers wanting RQ simplicity with more power
- Companies already invested in AWS ecosystem

---

## Technical Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Application Code                       │
│  @sq.task(schema=EmailTask)                                  │
│  async def send_email(task: EmailTask): ...                  │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                      SimpleQ Client                          │
│  - Task serialization (JSON/CloudPickle)                     │
│  - Pydantic validation                                       │
│  - Cost tracking                                             │
│  - Async/sync task support                                   │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                       AWS SQS                                │
│  - Standard or FIFO queues                                   │
│  - Message deduplication                                     │
│  - Dead letter queues                                        │
│  - Visibility timeout management                             │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    SimpleQ Worker                            │
│  - Long polling (cost optimization)                          │
│  - Batch processing (10 messages)                            │
│  - Async execution                                           │
│  - Auto-heartbeat for long jobs                              │
│  - Graceful shutdown                                         │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                     Observability                            │
│  - CloudWatch Metrics                                        │
│  - X-Ray Traces                                              │
│  - Prometheus Metrics                                        │
│  - Structured Logs                                           │
│  - Web Dashboard                                             │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

**Core:**
- Python 3.10+ (required)
- `boto3` - AWS SDK
- `aioboto3` - Async AWS SDK
- `pydantic` v2 - Data validation and serialization
- `asyncio` - Async/await support

**Observability:**
- `structlog` - Structured logging
- `prometheus_client` - Metrics export
- `opentelemetry-api` - Distributed tracing
- `aws-xray-sdk` - AWS X-Ray integration

**Developer Tools:**
- `typer` - CLI framework
- `rich` - Terminal UI
- `httpx` - Async HTTP for dashboard

**Testing:**
- `pytest` - Testing framework
- `pytest-asyncio` - Async test support
- `pytest-cov` - Coverage reporting
- `localstack` - Local AWS emulation
- `moto` - AWS service mocking

**Documentation:**
- `mkdocs-material` - Documentation site
- `mkdocstrings` - API doc generation

### Module Structure

```
simpleq/
├── __init__.py              # Public API
├── client.py                # SimpleQ main client
├── queue.py                 # Queue abstraction
├── task.py                  # Task decorator and registry
├── worker.py                # Worker implementation
├── job.py                   # Job representation
├── serializers/
│   ├── __init__.py
│   ├── json.py              # JSON serializer
│   └── cloudpickle.py       # CloudPickle fallback
├── sqs/
│   ├── __init__.py
│   ├── client.py            # SQS client wrapper
│   ├── fifo.py              # FIFO queue support
│   ├── dlq.py               # Dead letter queue
│   └── batching.py          # Batch operations
├── observability/
│   ├── __init__.py
│   ├── metrics.py           # Prometheus metrics
│   ├── tracing.py           # OpenTelemetry/X-Ray
│   ├── logging.py           # Structured logging
│   └── cost_tracker.py      # Cost tracking
├── cli/
│   ├── __init__.py
│   ├── main.py              # CLI entry point
│   ├── worker.py            # Worker commands
│   ├── queue.py             # Queue commands
│   └── dashboard.py         # Dashboard server
├── dashboard/
│   ├── __init__.py
│   ├── app.py               # Web dashboard
│   └── templates/           # HTML templates
├── integrations/
│   ├── __init__.py
│   ├── fastapi.py           # FastAPI integration
│   ├── django.py            # Django integration
│   └── flask.py             # Flask integration
└── testing/
    ├── __init__.py
    ├── localstack.py        # Localstack helpers
    └── fixtures.py          # Test fixtures
```

---

## Detailed Implementation Plan

### Phase 1: Foundation (Weeks 1-2)

**Goal:** Modernize codebase to 2026 standards with async-first architecture

#### Week 1: Core Modernization

**Day 1-2: Project Setup**
- [ ] Create `v2-development` branch
- [ ] Update `pyproject.toml` (replace setup.py)
  ```toml
  [project]
  name = "simpleq"
  version = "2.0.0"
  description = "The Python task queue for AWS"
  requires-python = ">=3.10"
  dependencies = [
      "boto3>=1.34.0",
      "aioboto3>=13.0.0",
      "pydantic>=2.5.0",
      "structlog>=24.0.0",
      "typer>=0.9.0",
      "rich>=13.0.0",
  ]

  [project.optional-dependencies]
  dev = [
      "pytest>=8.0.0",
      "pytest-asyncio>=0.23.0",
      "pytest-cov>=4.1.0",
      "mypy>=1.8.0",
      "ruff>=0.2.0",
      "localstack>=3.0.0",
  ]
  observability = [
      "prometheus-client>=0.19.0",
      "opentelemetry-api>=1.22.0",
      "aws-xray-sdk>=2.12.0",
  ]
  dashboard = [
      "httpx>=0.26.0",
      "jinja2>=3.1.0",
  ]
  ```

- [ ] Configure GitHub Actions
  ```yaml
  # .github/workflows/test.yml
  name: Test
  on: [push, pull_request]
  jobs:
    test:
      runs-on: ubuntu-latest
      strategy:
        matrix:
          python-version: ["3.10", "3.11", "3.12"]
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with:
            python-version: ${{ matrix.python-version }}
        - run: pip install -e ".[dev]"
        - run: ruff check .
        - run: mypy simpleq
        - run: pytest --cov=simpleq --cov-report=xml
        - uses: codecov/codecov-action@v3
  ```

- [ ] Set up pre-commit hooks
  ```yaml
  # .pre-commit-config.yaml
  repos:
    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.2.0
      hooks:
        - id: ruff
          args: [--fix]
        - id: ruff-format
    - repo: https://github.com/pre-commit/mirrors-mypy
      rev: v1.8.0
      hooks:
        - id: mypy
          additional_dependencies: [types-all]
  ```

**Day 3-4: Boto3 Migration**
- [ ] Replace all `boto` imports with `boto3`
- [ ] Update SQS connection handling
  ```python
  # Old (boto)
  from boto.sqs import connect_to_region
  conn = connect_to_region('us-east-1')

  # New (boto3)
  import boto3
  sqs = boto3.resource('sqs', region_name='us-east-1')
  ```

- [ ] Add async support with `aioboto3`
  ```python
  import aioboto3

  async def get_queue(queue_name: str):
      session = aioboto3.Session()
      async with session.resource('sqs') as sqs:
          queue = await sqs.get_queue_by_name(QueueName=queue_name)
          return queue
  ```

- [ ] Update all queue operations to boto3 API

**Day 5-7: Type Hints & Core Async**
- [ ] Add type hints to all existing code
- [ ] Configure mypy strict mode
  ```ini
  # pyproject.toml
  [tool.mypy]
  python_version = "3.10"
  strict = true
  warn_return_any = true
  warn_unused_configs = true
  disallow_untyped_defs = true
  ```

- [ ] Rewrite `Queue` class with async
  ```python
  from typing import AsyncIterator
  import aioboto3
  from pydantic import BaseModel

  class Queue:
      def __init__(
          self,
          name: str,
          *,
          region: str = "us-east-1",
          fifo: bool = False,
          dlq: bool = False,
      ) -> None:
          self.name = name
          self.region = region
          self.fifo = fifo
          self.dlq = dlq
          self._session = aioboto3.Session()

      async def enqueue(self, job: Job) -> None:
          """Add a job to the queue."""
          async with self._session.resource('sqs') as sqs:
              queue = await sqs.get_queue_by_name(QueueName=self.name)
              await queue.send_message(
                  MessageBody=job.serialize(),
                  MessageAttributes=job.attributes,
              )

      async def jobs(self) -> AsyncIterator[Job]:
          """Iterate through jobs in the queue."""
          async with self._session.resource('sqs') as sqs:
              queue = await sqs.get_queue_by_name(QueueName=self.name)

              while True:
                  messages = await queue.receive_messages(
                      MaxNumberOfMessages=10,
                      WaitTimeSeconds=20,
                  )

                  for msg in messages:
                      yield Job.deserialize(msg.body)
                      await msg.delete()
  ```

#### Week 2: Job System & Testing

**Day 8-10: Job & Task Implementation**
- [ ] Rewrite `Job` class with Pydantic
  ```python
  from datetime import datetime
  from typing import Any, Callable
  from pydantic import BaseModel, Field
  import json

  class Job(BaseModel):
      """A single unit of work."""

      task_name: str
      args: tuple[Any, ...] = Field(default_factory=tuple)
      kwargs: dict[str, Any] = Field(default_factory=dict)
      created_at: datetime = Field(default_factory=datetime.utcnow)
      retry_count: int = 0

      def serialize(self) -> str:
          """Serialize to JSON."""
          return self.model_dump_json()

      @classmethod
      def deserialize(cls, data: str) -> "Job":
          """Deserialize from JSON."""
          return cls.model_validate_json(data)
  ```

- [ ] Implement task decorator with type safety
  ```python
  from typing import Callable, ParamSpec, TypeVar, overload
  from pydantic import BaseModel

  P = ParamSpec("P")
  R = TypeVar("R")

  class TaskDecorator:
      def __init__(self, queue: Queue, schema: type[BaseModel] | None = None):
          self.queue = queue
          self.schema = schema

      def __call__(self, func: Callable[P, R]) -> Task[P, R]:
          return Task(func, self.queue, self.schema)

  class Task:
      def __init__(
          self,
          func: Callable[P, R],
          queue: Queue,
          schema: type[BaseModel] | None,
      ):
          self.func = func
          self.queue = queue
          self.schema = schema

      async def delay(self, *args: P.args, **kwargs: P.kwargs) -> None:
          """Enqueue this task for background execution."""
          # Validate with schema if provided
          if self.schema:
              validated = self.schema.model_validate(kwargs)
              kwargs = validated.model_dump()

          job = Job(
              task_name=self.func.__name__,
              args=args,
              kwargs=kwargs,
          )
          await self.queue.enqueue(job)
  ```

**Day 11-12: Worker Implementation**
- [ ] Build async worker
  ```python
  import asyncio
  from typing import Callable

  class Worker:
      def __init__(
          self,
          queues: list[Queue],
          *,
          concurrency: int = 10,
      ) -> None:
          self.queues = queues
          self.concurrency = concurrency
          self._running = False
          self._tasks: set[asyncio.Task] = set()

      async def work(self, burst: bool = False) -> None:
          """Start processing jobs."""
          self._running = True

          while self._running:
              for queue in self.queues:
                  async for job in queue.jobs():
                      # Create task for concurrent execution
                      task = asyncio.create_task(self._process_job(job))
                      self._tasks.add(task)
                      task.add_done_callback(self._tasks.discard)

                      # Limit concurrency
                      if len(self._tasks) >= self.concurrency:
                          await asyncio.wait(
                              self._tasks,
                              return_when=asyncio.FIRST_COMPLETED,
                          )

              if burst:
                  break

          # Wait for remaining tasks
          if self._tasks:
              await asyncio.gather(*self._tasks)

      async def _process_job(self, job: Job) -> None:
          """Process a single job."""
          try:
              # Execute the task
              func = TASK_REGISTRY[job.task_name]
              result = await func(*job.args, **job.kwargs)
          except Exception as e:
              # Log error, will be retried via DLQ
              logger.error("Job failed", job=job, error=str(e))
              raise
  ```

**Day 13-14: Testing Infrastructure**
- [ ] Set up pytest with localstack
  ```python
  # tests/conftest.py
  import pytest
  import asyncio
  from localstack.testing.pytest import fixtures

  @pytest.fixture(scope="session")
  def event_loop():
      loop = asyncio.get_event_loop_policy().new_event_loop()
      yield loop
      loop.close()

  @pytest.fixture
  async def sqs_queue(localstack):
      """Create a test SQS queue."""
      import aioboto3

      session = aioboto3.Session()
      async with session.resource(
          'sqs',
          endpoint_url='http://localhost:4566',
      ) as sqs:
          queue = await sqs.create_queue(QueueName='test-queue')
          yield queue
          await queue.delete()
  ```

- [ ] Write comprehensive tests
  ```python
  # tests/test_queue.py
  import pytest
  from simpleq import Queue, Job

  @pytest.mark.asyncio
  async def test_enqueue_and_dequeue(sqs_queue):
      queue = Queue("test-queue")

      job = Job(task_name="test_task", args=(1, 2))
      await queue.enqueue(job)

      received = [job async for job in queue.jobs()]
      assert len(received) == 1
      assert received[0].task_name == "test_task"
  ```

- [ ] Achieve 90%+ test coverage

**Deliverable Week 1-2:**
- ✅ Modern Python 3.10+ codebase
- ✅ Boto3 + aioboto3 integration
- ✅ Native async/await support
- ✅ Type hints with mypy strict mode
- ✅ CI/CD with GitHub Actions
- ✅ 90%+ test coverage
- ✅ All existing tests passing

---

### Phase 2: SQS-Native Features (Weeks 3-4)

**Goal:** Implement features that make SimpleQ unique and leverage SQS capabilities

#### Week 3: FIFO & Deduplication

**Day 15-16: FIFO Queue Support**
- [ ] Implement FIFO queue creation
  ```python
  class Queue:
      def __init__(
          self,
          name: str,
          *,
          fifo: bool = False,
          content_based_deduplication: bool = False,
      ) -> None:
          self.name = name
          self.fifo = fifo

          # FIFO queues must end with .fifo
          if fifo and not name.endswith('.fifo'):
              self.name = f"{name}.fifo"

          self.content_based_deduplication = content_based_deduplication

      async def _ensure_queue_exists(self) -> None:
          """Create queue if it doesn't exist."""
          async with self._session.resource('sqs') as sqs:
              try:
                  self._queue = await sqs.get_queue_by_name(
                      QueueName=self.name
                  )
              except sqs.meta.client.exceptions.QueueDoesNotExist:
                  attrs = {}

                  if self.fifo:
                      attrs['FifoQueue'] = 'true'
                      if self.content_based_deduplication:
                          attrs['ContentBasedDeduplication'] = 'true'

                  self._queue = await sqs.create_queue(
                      QueueName=self.name,
                      Attributes=attrs,
                  )
  ```

- [ ] Add message group ID support
  ```python
  class Task:
      def __init__(
          self,
          func: Callable,
          queue: Queue,
          *,
          message_group_id: str | Callable | None = None,
      ):
          self.func = func
          self.queue = queue
          self.message_group_id = message_group_id

      async def delay(self, *args, **kwargs) -> None:
          job = Job(task_name=self.func.__name__, args=args, kwargs=kwargs)

          # Determine message group ID
          group_id = None
          if self.queue.fifo:
              if callable(self.message_group_id):
                  group_id = self.message_group_id(*args, **kwargs)
              elif self.message_group_id:
                  group_id = self.message_group_id
              else:
                  # Default: use task name as group
                  group_id = self.func.__name__

          await self.queue.enqueue(job, message_group_id=group_id)
  ```

- [ ] Test FIFO ordering guarantees
  ```python
  @pytest.mark.asyncio
  async def test_fifo_ordering():
      queue = Queue("test.fifo", fifo=True)

      # Enqueue 10 jobs in order
      for i in range(10):
          await queue.enqueue(Job(task_name="test", args=(i,)))

      # Verify order is preserved
      results = [job async for job in queue.jobs()]
      assert [j.args[0] for j in results] == list(range(10))
  ```

**Day 17-18: Message Deduplication**
- [ ] Implement deduplication ID support
  ```python
  class Job(BaseModel):
      task_name: str
      args: tuple
      kwargs: dict
      deduplication_id: str | None = None

      def get_deduplication_id(self) -> str:
          """Generate deduplication ID."""
          if self.deduplication_id:
              return self.deduplication_id

          # Content-based: hash of task + args + kwargs
          import hashlib
          content = f"{self.task_name}:{self.args}:{self.kwargs}"
          return hashlib.sha256(content.encode()).hexdigest()
  ```

- [ ] Add deduplication to enqueue
  ```python
  async def enqueue(
      self,
      job: Job,
      *,
      message_group_id: str | None = None,
  ) -> None:
      async with self._session.resource('sqs') as sqs:
          queue = await self._get_queue(sqs)

          kwargs = {
              'MessageBody': job.serialize(),
          }

          if self.fifo:
              kwargs['MessageGroupId'] = message_group_id or 'default'

              if not self.content_based_deduplication:
                  kwargs['MessageDeduplicationId'] = job.get_deduplication_id()

          await queue.send_message(**kwargs)
  ```

- [ ] Test deduplication behavior
  ```python
  @pytest.mark.asyncio
  async def test_deduplication():
      queue = Queue("test.fifo", fifo=True)

      job = Job(task_name="test", args=(1,))

      # Send same job twice within 5 minutes
      await queue.enqueue(job)
      await queue.enqueue(job)

      # Should only receive one job
      results = [j async for j in queue.jobs()]
      assert len(results) == 1
  ```

#### Week 4: DLQ & Cost Tracking

**Day 19-20: Dead Letter Queue**
- [ ] Implement automatic DLQ setup
  ```python
  class Queue:
      async def _ensure_queue_exists(self) -> None:
          async with self._session.resource('sqs') as sqs:
              # Create DLQ first if enabled
              dlq_arn = None
              if self.dlq:
                  dlq_name = f"{self.name}-dlq"
                  dlq = await sqs.create_queue(
                      QueueName=dlq_name,
                      Attributes={'FifoQueue': 'true'} if self.fifo else {},
                  )
                  dlq_arn = (await dlq.attributes)['QueueArn']

              # Create main queue with DLQ policy
              attrs = {}
              if dlq_arn:
                  attrs['RedrivePolicy'] = json.dumps({
                      'deadLetterTargetArn': dlq_arn,
                      'maxReceiveCount': '3',  # Retry 3 times
                  })

              self._queue = await sqs.create_queue(
                  QueueName=self.name,
                  Attributes=attrs,
              )
  ```

- [ ] Add DLQ inspection methods
  ```python
  class Queue:
      async def get_dlq_jobs(self) -> AsyncIterator[Job]:
          """Iterate through jobs in the dead letter queue."""
          async with self._session.resource('sqs') as sqs:
              dlq = await sqs.get_queue_by_name(
                  QueueName=f"{self.name}-dlq"
              )

              messages = await dlq.receive_messages(
                  MaxNumberOfMessages=10,
              )

              for msg in messages:
                  yield Job.deserialize(msg.body)

      async def redrive_dlq_jobs(self) -> int:
          """Move jobs from DLQ back to main queue."""
          count = 0
          async for job in self.get_dlq_jobs():
              await self.enqueue(job)
              count += 1
          return count
  ```

**Day 21-22: Cost Tracking**
- [ ] Implement cost calculator
  ```python
  # simpleq/observability/cost_tracker.py
  from dataclasses import dataclass
  from datetime import datetime

  @dataclass
  class CostMetrics:
      """SQS cost metrics."""

      # Request counts
      send_requests: int = 0
      receive_requests: int = 0
      delete_requests: int = 0

      # Pricing (as of 2026, adjust for region)
      price_per_million_requests: float = 0.40  # $0.40 per million

      @property
      def total_requests(self) -> int:
          return (
              self.send_requests +
              self.receive_requests +
              self.delete_requests
          )

      @property
      def estimated_cost(self) -> float:
          """Calculate estimated cost in USD."""
          return (self.total_requests / 1_000_000) * self.price_per_million_requests

      def add_send(self, count: int = 1) -> None:
          self.send_requests += count

      def add_receive(self, count: int = 1) -> None:
          self.receive_requests += count

      def add_delete(self, count: int = 1) -> None:
          self.delete_requests += count

  class CostTracker:
      """Track SQS costs across queues."""

      def __init__(self):
          self._metrics: dict[str, CostMetrics] = {}

      def get_metrics(self, queue_name: str) -> CostMetrics:
          if queue_name not in self._metrics:
              self._metrics[queue_name] = CostMetrics()
          return self._metrics[queue_name]

      def total_cost(self) -> float:
          return sum(m.estimated_cost for m in self._metrics.values())
  ```

- [ ] Integrate cost tracking into Queue
  ```python
  class Queue:
      def __init__(self, name: str, *, cost_tracker: CostTracker | None = None):
          self.name = name
          self.cost_tracker = cost_tracker or CostTracker()

      async def enqueue(self, job: Job) -> None:
          await self._send_message(job)
          self.cost_tracker.get_metrics(self.name).add_send()

      async def jobs(self) -> AsyncIterator[Job]:
          async for job in self._receive_messages():
              self.cost_tracker.get_metrics(self.name).add_receive()
              yield job
              self.cost_tracker.get_metrics(self.name).add_delete()
  ```

- [ ] Add cost reporting CLI command
  ```python
  # simpleq/cli/cost.py
  import typer
  from rich.console import Console
  from rich.table import Table

  app = typer.Typer()
  console = Console()

  @app.command()
  def report(
      queue_name: str | None = None,
      last_days: int = 30,
  ):
      """Show cost report for queues."""
      tracker = get_cost_tracker()

      table = Table(title=f"SQS Cost Report (Last {last_days} Days)")
      table.add_column("Queue", style="cyan")
      table.add_column("Requests", justify="right")
      table.add_column("Est. Cost", justify="right", style="green")

      for name, metrics in tracker._metrics.items():
          if queue_name and name != queue_name:
              continue

          table.add_row(
              name,
              f"{metrics.total_requests:,}",
              f"${metrics.estimated_cost:.4f}",
          )

      console.print(table)
      console.print(f"\nTotal: ${tracker.total_cost():.4f}")
  ```

**Deliverable Week 3-4:**
- ✅ FIFO queue support with message groups
- ✅ Message deduplication (content-based and custom IDs)
- ✅ Automatic DLQ setup and management
- ✅ Cost tracking and reporting
- ✅ Comprehensive tests for all features

---

### Phase 3: Developer Experience (Weeks 5-6)

**Goal:** Make SimpleQ the easiest task queue to use

#### Week 5: CLI & Localstack

**Day 23-24: CLI Framework**
- [ ] Build comprehensive CLI
  ```python
  # simpleq/cli/main.py
  import typer
  from rich.console import Console

  app = typer.Typer(
      name="simpleq",
      help="SimpleQ - The Python task queue for AWS"
  )

  # Register subcommands
  from simpleq.cli import worker, queue, cost
  app.add_typer(worker.app, name="worker")
  app.add_typer(queue.app, name="queue")
  app.add_typer(cost.app, name="cost")

  if __name__ == "__main__":
      app()
  ```

- [ ] Worker commands
  ```python
  # simpleq/cli/worker.py
  import typer
  import asyncio
  from simpleq import SimpleQ, Worker

  app = typer.Typer()

  @app.command()
  def start(
      queues: list[str] = typer.Option(..., "--queue", "-q"),
      concurrency: int = typer.Option(10, "--concurrency", "-c"),
      burst: bool = typer.Option(False, "--burst"),
  ):
      """Start processing jobs from queues."""
      sq = SimpleQ()
      queue_objs = [sq.queue(name) for name in queues]

      worker = Worker(queue_objs, concurrency=concurrency)

      try:
          asyncio.run(worker.work(burst=burst))
      except KeyboardInterrupt:
          typer.echo("Shutting down gracefully...")
  ```

- [ ] Queue management commands
  ```python
  # simpleq/cli/queue.py
  import typer
  from rich.console import Console
  from rich.table import Table

  app = typer.Typer()
  console = Console()

  @app.command()
  def create(
      name: str,
      fifo: bool = typer.Option(False, "--fifo"),
      dlq: bool = typer.Option(False, "--dlq"),
  ):
      """Create a new queue."""
      sq = SimpleQ()
      queue = sq.queue(name, fifo=fifo, dlq=dlq)
      asyncio.run(queue._ensure_queue_exists())
      console.print(f"✓ Created queue: {name}")

  @app.command()
  def stats(name: str):
      """Show queue statistics."""
      sq = SimpleQ()
      queue = sq.queue(name)

      # Get queue attributes
      attrs = asyncio.run(queue.get_attributes())

      table = Table(title=f"Queue Stats: {name}")
      table.add_column("Metric", style="cyan")
      table.add_column("Value", style="green")

      table.add_row("Messages Available", attrs['ApproximateNumberOfMessages'])
      table.add_row("Messages In Flight", attrs['ApproximateNumberOfMessagesNotVisible'])
      table.add_row("Messages Delayed", attrs['ApproximateNumberOfMessagesDelayed'])

      console.print(table)

  @app.command()
  def list():
      """List all queues."""
      sq = SimpleQ()
      queues = asyncio.run(sq.list_queues())

      table = Table(title="Queues")
      table.add_column("Name", style="cyan")
      table.add_column("Type", style="yellow")

      for queue in queues:
          qtype = "FIFO" if queue.endswith('.fifo') else "Standard"
          table.add_row(queue, qtype)

      console.print(table)
  ```

**Day 25-26: Localstack Integration**
- [ ] Auto-detect localstack
  ```python
  # simpleq/config.py
  import os

  def get_endpoint_url() -> str | None:
      """Auto-detect localstack or return None for production."""
      # Check environment variable
      if endpoint := os.environ.get('SIMPLEQ_ENDPOINT_URL'):
          return endpoint

      # Check if localstack is running locally
      if os.environ.get('LOCALSTACK_HOSTNAME'):
          return 'http://localhost:4566'

      # Check for common CI environments
      if os.environ.get('CI'):
          return 'http://localhost:4566'

      # Production (real AWS)
      return None

  def create_session() -> aioboto3.Session:
      session = aioboto3.Session()
      endpoint = get_endpoint_url()

      if endpoint:
          # Localstack mode
          logger.info(f"Using localstack at {endpoint}")

      return session
  ```

- [ ] Provide test fixtures
  ```python
  # simpleq/testing/fixtures.py
  import pytest
  from simpleq import SimpleQ

  @pytest.fixture
  def simpleq_localstack():
      """SimpleQ instance configured for localstack."""
      import os
      os.environ['SIMPLEQ_ENDPOINT_URL'] = 'http://localhost:4566'

      sq = SimpleQ()
      yield sq

      # Cleanup
      del os.environ['SIMPLEQ_ENDPOINT_URL']

  @pytest.fixture
  async def test_queue(simpleq_localstack):
      """Create a test queue."""
      sq = simpleq_localstack
      queue = sq.queue('test-queue')
      await queue._ensure_queue_exists()

      yield queue

      # Cleanup
      await queue.delete()
  ```

#### Week 6: Observability & Dashboard

**Day 27-28: Prometheus Metrics**
- [ ] Implement metrics collection
  ```python
  # simpleq/observability/metrics.py
  from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry

  registry = CollectorRegistry()

  # Counters
  jobs_enqueued = Counter(
      'simpleq_jobs_enqueued_total',
      'Total number of jobs enqueued',
      ['queue_name', 'task_name'],
      registry=registry,
  )

  jobs_processed = Counter(
      'simpleq_jobs_processed_total',
      'Total number of jobs processed',
      ['queue_name', 'task_name', 'status'],
      registry=registry,
  )

  # Histograms
  job_duration = Histogram(
      'simpleq_job_duration_seconds',
      'Job execution duration',
      ['queue_name', 'task_name'],
      registry=registry,
  )

  # Gauges
  queue_depth = Gauge(
      'simpleq_queue_depth',
      'Number of messages in queue',
      ['queue_name'],
      registry=registry,
  )

  sqs_api_calls = Counter(
      'simpleq_sqs_api_calls_total',
      'Total SQS API calls',
      ['operation'],
      registry=registry,
  )
  ```

- [ ] Add metrics endpoint
  ```python
  # simpleq/cli/metrics.py
  import typer
  from prometheus_client import start_http_server

  app = typer.Typer()

  @app.command()
  def serve(port: int = 9090):
      """Start Prometheus metrics server."""
      start_http_server(port)
      typer.echo(f"Metrics server running on http://localhost:{port}")

      # Keep running
      import time
      try:
          while True:
              time.sleep(1)
      except KeyboardInterrupt:
          typer.echo("Shutting down...")
  ```

**Day 29-30: Web Dashboard**
- [ ] Build simple web dashboard
  ```python
  # simpleq/dashboard/app.py
  import asyncio
  from typing import Any
  import httpx
  from jinja2 import Environment, FileSystemLoader

  class Dashboard:
      def __init__(self, sq: SimpleQ):
          self.sq = sq
          self.env = Environment(
              loader=FileSystemLoader('simpleq/dashboard/templates')
          )

      async def get_stats(self) -> dict[str, Any]:
          """Get statistics for dashboard."""
          queues = await self.sq.list_queues()
          stats = []

          for queue_name in queues:
              queue = self.sq.queue(queue_name)
              attrs = await queue.get_attributes()

              stats.append({
                  'name': queue_name,
                  'available': int(attrs['ApproximateNumberOfMessages']),
                  'in_flight': int(attrs['ApproximateNumberOfMessagesNotVisible']),
                  'dlq_messages': 0,  # TODO: Get DLQ stats
              })

          cost_tracker = self.sq.cost_tracker

          return {
              'queues': stats,
              'total_cost': cost_tracker.total_cost(),
              'total_requests': sum(
                  m.total_requests
                  for m in cost_tracker._metrics.values()
              ),
          }

      def render(self) -> str:
          """Render dashboard HTML."""
          stats = asyncio.run(self.get_stats())
          template = self.env.get_template('dashboard.html')
          return template.render(**stats)
  ```

- [ ] Create dashboard template
  ```html
  <!-- simpleq/dashboard/templates/dashboard.html -->
  <!DOCTYPE html>
  <html>
  <head>
      <title>SimpleQ Dashboard</title>
      <style>
          body { font-family: system-ui; padding: 20px; }
          .card { border: 1px solid #ddd; padding: 20px; margin: 10px 0; }
          .metric { font-size: 2em; color: #0066cc; }
          table { width: 100%; border-collapse: collapse; }
          th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
      </style>
  </head>
  <body>
      <h1>SimpleQ Dashboard</h1>

      <div class="card">
          <h2>Cost Summary</h2>
          <div class="metric">${{ "%.4f"|format(total_cost) }}</div>
          <p>{{ "{:,}".format(total_requests) }} total requests</p>
      </div>

      <div class="card">
          <h2>Queues</h2>
          <table>
              <thead>
                  <tr>
                      <th>Queue</th>
                      <th>Available</th>
                      <th>In Flight</th>
                      <th>DLQ</th>
                  </tr>
              </thead>
              <tbody>
                  {% for queue in queues %}
                  <tr>
                      <td>{{ queue.name }}</td>
                      <td>{{ queue.available }}</td>
                      <td>{{ queue.in_flight }}</td>
                      <td>{{ queue.dlq_messages }}</td>
                  </tr>
                  {% endfor %}
              </tbody>
          </table>
      </div>
  </body>
  </html>
  ```

- [ ] Add dashboard command to CLI
  ```python
  # simpleq/cli/dashboard.py
  import typer
  from simpleq import SimpleQ
  from simpleq.dashboard import Dashboard

  app = typer.Typer()

  @app.command()
  def serve(port: int = 8080):
      """Start web dashboard."""
      sq = SimpleQ()
      dashboard = Dashboard(sq)

      # Simple HTTP server
      import http.server
      import socketserver

      class Handler(http.server.BaseHTTPRequestHandler):
          def do_GET(self):
              self.send_response(200)
              self.send_header('Content-type', 'text/html')
              self.end_headers()
              self.wfile.write(dashboard.render().encode())

      with socketserver.TCPServer(("", port), Handler) as httpd:
          typer.echo(f"Dashboard running at http://localhost:{port}")
          httpd.serve_forever()
  ```

**Deliverable Week 5-6:**
- ✅ Comprehensive CLI tool
- ✅ Auto-detecting localstack integration
- ✅ Prometheus metrics
- ✅ Web dashboard with cost tracking
- ✅ Test fixtures for easy testing

---

### Phase 4: Advanced Features (Weeks 7-8)

**Goal:** Enterprise-ready production features

#### Week 7: Retries & Scheduling

**Day 31-32: Retry Logic**
- [ ] Implement configurable retries
  ```python
  from typing import Literal

  BackoffStrategy = Literal["linear", "exponential", "constant"]

  class Task:
      def __init__(
          self,
          func: Callable,
          queue: Queue,
          *,
          max_retries: int = 3,
          backoff: BackoffStrategy = "exponential",
          retry_exceptions: list[type[Exception]] | None = None,
      ):
          self.func = func
          self.queue = queue
          self.max_retries = max_retries
          self.backoff = backoff
          self.retry_exceptions = retry_exceptions or [Exception]

      def should_retry(self, exception: Exception, retry_count: int) -> bool:
          """Determine if job should be retried."""
          if retry_count >= self.max_retries:
              return False

          # Check if exception type is retryable
          return any(
              isinstance(exception, exc_type)
              for exc_type in self.retry_exceptions
          )

      def calculate_delay(self, retry_count: int) -> int:
          """Calculate delay before retry in seconds."""
          if self.backoff == "constant":
              return 60  # 1 minute
          elif self.backoff == "linear":
              return retry_count * 60  # 1, 2, 3 minutes
          else:  # exponential
              return min(2 ** retry_count * 60, 3600)  # Cap at 1 hour
  ```

- [ ] Integrate retry logic into worker
  ```python
  class Worker:
      async def _process_job(self, job: Job, message) -> None:
          """Process a single job with retry logic."""
          task = TASK_REGISTRY[job.task_name]

          try:
              # Execute the task
              if asyncio.iscoroutinefunction(task.func):
                  result = await task.func(*job.args, **job.kwargs)
              else:
                  result = task.func(*job.args, **job.kwargs)

              # Success - delete message
              await message.delete()

          except Exception as e:
              # Check if should retry
              if task.should_retry(e, job.retry_count):
                  # Calculate delay and re-enqueue
                  delay = task.calculate_delay(job.retry_count)
                  job.retry_count += 1

                  await task.queue.enqueue(
                      job,
                      delay_seconds=delay,
                  )

                  # Delete original message
                  await message.delete()

                  logger.warning(
                      f"Job failed, retrying in {delay}s",
                      job=job,
                      error=str(e),
                      retry_count=job.retry_count,
                  )
              else:
                  # Max retries reached or non-retryable error
                  # Let it go to DLQ
                  logger.error(
                      "Job failed permanently",
                      job=job,
                      error=str(e),
                      retry_count=job.retry_count,
                  )
                  # Don't delete - will go to DLQ after max receives
  ```

**Day 33-34: Job Scheduling**
- [ ] Add delayed execution
  ```python
  class Queue:
      async def enqueue(
          self,
          job: Job,
          *,
          delay_seconds: int = 0,
      ) -> None:
          """Enqueue a job with optional delay."""
          async with self._session.resource('sqs') as sqs:
              queue = await self._get_queue(sqs)

              kwargs = {
                  'MessageBody': job.serialize(),
              }

              # SQS supports delays up to 15 minutes
              if delay_seconds > 0:
                  kwargs['DelaySeconds'] = min(delay_seconds, 900)

              await queue.send_message(**kwargs)
  ```

- [ ] EventBridge integration for cron
  ```python
  # simpleq/scheduling.py
  import boto3
  from typing import Callable

  class Scheduler:
      def __init__(self, sq: SimpleQ):
          self.sq = sq
          self.eventbridge = boto3.client('events')

      def cron(self, expression: str):
          """Decorator for cron-scheduled tasks."""
          def decorator(func: Callable):
              task = self.sq.task()(func)

              # Create EventBridge rule
              rule_name = f"simpleq-{func.__name__}"
              self.eventbridge.put_rule(
                  Name=rule_name,
                  ScheduleExpression=f"cron({expression})",
                  State='ENABLED',
              )

              # Add SQS queue as target
              self.eventbridge.put_targets(
                  Rule=rule_name,
                  Targets=[{
                      'Id': '1',
                      'Arn': task.queue.arn,
                      'Input': task._create_job_json(),
                  }],
              )

              return task

          return decorator
  ```

#### Week 8: Multi-Region & Polish

**Day 35-36: Multi-Region Support**
- [ ] Implement region failover
  ```python
  class SimpleQ:
      def __init__(
          self,
          *,
          regions: list[str] | None = None,
          failover: bool = False,
      ):
          self.regions = regions or ['us-east-1']
          self.failover = failover
          self._current_region_idx = 0

      async def queue(self, name: str, **kwargs) -> Queue:
          """Get queue, with region failover if enabled."""
          if not self.failover:
              return Queue(name, region=self.regions[0], **kwargs)

          # Try each region until success
          for i, region in enumerate(self.regions):
              try:
                  queue = Queue(name, region=region, **kwargs)
                  await queue._ensure_queue_exists()
                  self._current_region_idx = i
                  return queue
              except Exception as e:
                  logger.warning(f"Region {region} failed: {e}")
                  continue

          raise RuntimeError("All regions failed")
  ```

**Day 37-38: Polish & Documentation**
- [ ] Add docstrings to all public APIs
- [ ] Create comprehensive type stubs
- [ ] Write inline code examples
- [ ] Performance profiling and optimization
- [ ] Security audit
- [ ] Final testing pass

**Deliverable Week 7-8:**
- ✅ Configurable retry logic with backoff
- ✅ Delayed execution support
- ✅ EventBridge cron integration
- ✅ Multi-region failover
- ✅ Production-ready, fully tested

---

### Phase 5: Documentation & Launch (Weeks 9-10)

#### Week 9: Documentation

**Day 39-42: Documentation Site**
- [ ] Set up MkDocs Material
  ```yaml
  # mkdocs.yml
  site_name: SimpleQ
  site_description: The Python task queue for AWS
  theme:
    name: material
    palette:
      primary: indigo
    features:
      - navigation.tabs
      - navigation.sections
      - search.highlight

  nav:
    - Home: index.md
    - Getting Started:
      - Installation: getting-started/installation.md
      - Quick Start: getting-started/quickstart.md
      - Tutorial: getting-started/tutorial.md
    - User Guide:
      - Tasks: guide/tasks.md
      - Queues: guide/queues.md
      - Workers: guide/workers.md
      - FIFO Queues: guide/fifo.md
      - Dead Letter Queues: guide/dlq.md
      - Cost Optimization: guide/cost.md
    - Framework Integration:
      - FastAPI: integrations/fastapi.md
      - Django: integrations/django.md
      - Flask: integrations/flask.md
    - Advanced:
      - Retries: advanced/retries.md
      - Scheduling: advanced/scheduling.md
      - Multi-Region: advanced/multi-region.md
      - Monitoring: advanced/monitoring.md
    - Migration Guides:
      - From Celery: migration/celery.md
      - From RQ: migration/rq.md
      - From Dramatiq: migration/dramatiq.md
    - API Reference: api/

  plugins:
    - search
    - mkdocstrings:
        handlers:
          python:
            options:
              show_source: true
  ```

- [ ] Write key documentation pages
  - Quick start (< 5 min to first job)
  - Complete user guide
  - API reference (auto-generated)
  - Migration guides
  - Best practices
  - Troubleshooting

- [ ] Create example projects
  - FastAPI + SimpleQ starter
  - Django + SimpleQ starter
  - Lambda workers example
  - ECS deployment example

#### Week 10: Launch Preparation

**Day 43-44: Content Creation**
- [ ] Blog post: "Introducing SimpleQ v2.0"
- [ ] Blog post: "Why We Built SimpleQ for AWS"
- [ ] Blog post: "Migrating from Celery to SimpleQ"
- [ ] Blog post: "SQS Task Queue Cost Comparison"
- [ ] Video: "SimpleQ in 5 Minutes"
- [ ] Comparison table vs competitors

**Day 45-46: Community Setup**
- [ ] Clean up README.md
- [ ] Create CONTRIBUTING.md
- [ ] Add CODE_OF_CONDUCT.md
- [ ] Set up GitHub Discussions
- [ ] Create Discord server
- [ ] Label good first issues
- [ ] Prepare launch posts (HN, Reddit)

**Day 47: Launch! 🚀**
- [ ] Publish v2.0.0 to PyPI
- [ ] Deploy documentation site
- [ ] Post on Hacker News
- [ ] Post on r/Python
- [ ] Post on r/aws
- [ ] Tweet announcement
- [ ] Submit to ProductHunt
- [ ] Email AWS developer advocates

**Deliverable Week 9-10:**
- ✅ Comprehensive documentation site
- ✅ Example projects and tutorials
- ✅ Migration guides
- ✅ Launch content ready
- ✅ v2.0.0 released

---

## API Design

### Core API

```python
from simpleq import SimpleQ
from pydantic import BaseModel

# Initialize
sq = SimpleQ()

# Define a task with type-safe schema
class EmailData(BaseModel):
    to: str
    subject: str
    body: str

@sq.task(schema=EmailData)
async def send_email(data: EmailData):
    # Send email logic
    print(f"Sending to {data.to}: {data.subject}")

# Enqueue a job
await send_email.delay(
    EmailData(
        to="user@example.com",
        subject="Hello",
        body="World"
    )
)

# Start worker
worker = sq.worker(queues=["default"], concurrency=10)
await worker.work()
```

### FIFO Queue Example

```python
# Create FIFO queue with content-based deduplication
sq = SimpleQ()
queue = sq.queue("orders.fifo", fifo=True, content_based_deduplication=True)

@sq.task(queue=queue, message_group_id=lambda order_id: f"customer-{order_id}")
async def process_order(order_id: str):
    # Orders for same customer processed in order
    pass

await process_order.delay("order-123")
```

### Dead Letter Queue Example

```python
# Queue with DLQ after 3 retries
queue = sq.queue("emails", dlq=True, max_retries=3)

@sq.task(queue=queue, retry_exceptions=[NetworkError])
async def send_email(to: str):
    # Will retry up to 3 times on NetworkError
    # Then move to DLQ
    pass

# Inspect DLQ
async for job in queue.get_dlq_jobs():
    print(f"Failed job: {job}")

# Redrive DLQ jobs back to main queue
count = await queue.redrive_dlq_jobs()
print(f"Redrove {count} jobs")
```

### Cost Tracking Example

```python
sq = SimpleQ()

# Cost tracking is automatic
await process_data.delay(data)

# View costs
cost_tracker = sq.cost_tracker
print(f"Total cost: ${cost_tracker.total_cost():.4f}")

for queue_name, metrics in cost_tracker._metrics.items():
    print(f"{queue_name}: {metrics.total_requests} requests")
```

### CLI Usage

```bash
# Start worker
simpleq worker start -q emails -q orders --concurrency 20

# Queue management
simpleq queue create notifications --fifo --dlq
simpleq queue stats emails
simpleq queue list

# Cost reporting
simpleq cost report
simpleq cost report --queue emails --last-30-days

# Dashboard
simpleq dashboard serve --port 8080

# Metrics
simpleq metrics serve --port 9090
```

---

## Performance Targets

### Benchmarks

**Target:** Top 3 performance (match Dramatiq/Huey)

**Test scenario:** 20,000 jobs with 10 workers

| Library | Target Time | Status |
|---------|-------------|--------|
| Taskiq | 2.03s | 🎯 Aspirational |
| Huey | 3.62s | 🎯 Target Range |
| Dramatiq | 4.12s | 🎯 Target Range |
| **SimpleQ** | **3-5s** | **✅ Goal** |
| Celery | 11.68s | ⚠️ Must Beat |
| RQ | 51.05s | ⚠️ Must Beat |

### Optimization Strategies

1. **Batch Operations** - Receive/send 10 messages at once
2. **Long Polling** - 20 second waits to reduce API calls
3. **Async/Await** - Native asyncio for I/O efficiency
4. **Message Prefetching** - Keep workers fed
5. **Connection Pooling** - Reuse boto3 sessions

### Performance Testing

```python
# tests/performance/benchmark.py
import asyncio
import time
from simpleq import SimpleQ

async def benchmark():
    sq = SimpleQ()

    @sq.task()
    async def noop():
        pass

    # Enqueue 20,000 jobs
    start = time.time()
    for i in range(20_000):
        await noop.delay()
    enqueue_time = time.time() - start

    # Process with 10 workers
    worker = sq.worker(queues=["default"], concurrency=10)
    start = time.time()
    await worker.work(burst=True)
    process_time = time.time() - start

    print(f"Enqueue: {enqueue_time:.2f}s")
    print(f"Process: {process_time:.2f}s")
    print(f"Total: {enqueue_time + process_time:.2f}s")

asyncio.run(benchmark())
```

---

## Testing Strategy

### Test Coverage Goals

- **Overall:** 90%+ coverage
- **Core modules:** 95%+ coverage
- **Integration tests:** All major flows
- **Performance tests:** Benchmarks vs competitors

### Test Organization

```
tests/
├── unit/
│   ├── test_queue.py
│   ├── test_task.py
│   ├── test_job.py
│   ├── test_worker.py
│   └── test_serializers.py
├── integration/
│   ├── test_fifo.py
│   ├── test_dlq.py
│   ├── test_cost_tracking.py
│   └── test_retry.py
├── performance/
│   ├── benchmark.py
│   └── test_throughput.py
└── conftest.py
```

### Test Infrastructure

**Localstack:** For integration tests
**Moto:** For unit tests (mocking AWS)
**Pytest-asyncio:** For async test support
**Coverage:** For coverage reporting

### Example Tests

```python
# tests/integration/test_fifo.py
import pytest
from simpleq import SimpleQ

@pytest.mark.asyncio
async def test_fifo_ordering(localstack):
    sq = SimpleQ()
    queue = sq.queue("test.fifo", fifo=True)

    @sq.task(queue=queue)
    async def ordered_task(n: int):
        return n

    # Enqueue 100 jobs
    for i in range(100):
        await ordered_task.delay(i)

    # Process and verify order
    results = []
    worker = sq.worker(queues=["test.fifo"], concurrency=1)

    async for job in worker._get_jobs():
        results.append(job.args[0])

    assert results == list(range(100)), "FIFO order violated"
```

---

## Documentation Plan

### Documentation Structure

1. **Homepage** - Value prop, quick start, key features
2. **Installation** - pip install, requirements, optional deps
3. **Quick Start** - 5-minute tutorial
4. **User Guide** - Comprehensive guide for all features
5. **Framework Integration** - FastAPI, Django, Flask
6. **Advanced Topics** - Retries, scheduling, multi-region
7. **Migration Guides** - From Celery, RQ, Dramatiq
8. **API Reference** - Auto-generated from docstrings
9. **Best Practices** - Production tips
10. **Troubleshooting** - Common issues and solutions

### Documentation Examples

**Quick Start:**
```markdown
# Quick Start

Install SimpleQ:

\`\`\`bash
pip install simpleq
\`\`\`

Define a task:

\`\`\`python
from simpleq import SimpleQ

sq = SimpleQ()

@sq.task()
async def send_email(to: str, subject: str):
    print(f"Sending {subject} to {to}")
\`\`\`

Enqueue a job:

\`\`\`python
await send_email.delay("user@example.com", "Hello!")
\`\`\`

Start a worker:

\`\`\`bash
simpleq worker start -q default
\`\`\`

That's it! Your first background job is running.
```

**Migration Guide:**
```markdown
# Migrating from Celery

## Key Differences

| Feature | Celery | SimpleQ |
|---------|--------|---------|
| Broker | Many options | AWS SQS only |
| Setup | Complex config | Zero config |
| Async | Middleware | Native |
| Cost | Redis/RabbitMQ hosting | $0.40 per million requests |

## Step-by-Step Migration

### 1. Install SimpleQ

\`\`\`bash
pip install simpleq
\`\`\`

### 2. Replace Celery imports

\`\`\`python
# Before (Celery)
from celery import Celery
app = Celery('myapp', broker='redis://localhost')

# After (SimpleQ)
from simpleq import SimpleQ
sq = SimpleQ()
\`\`\`

### 3. Update task decorators

\`\`\`python
# Before (Celery)
@app.task
def send_email(to, subject):
    ...

# After (SimpleQ)
@sq.task()
async def send_email(to: str, subject: str):
    ...
\`\`\`

[Continue with detailed migration steps...]
```

---

## Launch Strategy

### Pre-Launch (Week 9)

**Content:**
- [ ] Blog post drafts
- [ ] Video script
- [ ] Launch tweet thread
- [ ] HN/Reddit posts
- [ ] Email to AWS advocates

**Community:**
- [ ] Discord server setup
- [ ] GitHub Discussions enabled
- [ ] Good first issues labeled
- [ ] Contributing guide polished

**Technical:**
- [ ] PyPI package ready
- [ ] Documentation deployed
- [ ] Examples tested
- [ ] Performance benchmarks run

### Launch Day (Day 47)

**Morning (9 AM PT):**
1. Publish v2.0.0 to PyPI
2. Deploy documentation
3. Publish blog post
4. Tweet announcement
5. Post to Hacker News

**Afternoon (12 PM PT):**
6. Post to r/Python
7. Post to r/aws
8. Post to r/django
9. Submit to ProductHunt

**Evening (6 PM PT):**
10. Engage with comments/feedback
11. Fix any reported issues
12. Thank early adopters

### Post-Launch (Week 10-12)

**Week 1:**
- Monitor adoption metrics
- Fix bugs reported
- Engage with community
- Update docs based on feedback

**Week 2-4:**
- Write follow-up blog posts
- Submit conference talks (PyCon, AWS re:Invent)
- Reach out to potential case study companies
- Continue community engagement

**Ongoing:**
- Monthly blog posts
- Regular feature releases
- Community support
- Track growth metrics

---

## Success Metrics

### 3 Month Goals (June 2026)

**GitHub:**
- ⭐ 1,000 stars
- 🍴 50 forks
- 📝 10 contributors

**PyPI:**
- 📦 10,000 monthly downloads
- 🔄 50 dependents

**Production:**
- 🏢 5 companies using in production
- 📊 10 case studies/testimonials

**Content:**
- 📝 1 AWS blog mention
- 🎥 5,000 video views
- 🐦 1,000 Twitter followers

### 6 Month Goals (September 2026)

**GitHub:**
- ⭐ 2,500 stars
- 🍴 150 forks
- 📝 25 contributors

**PyPI:**
- 📦 50,000 monthly downloads
- 🔄 200 dependents

**Production:**
- 🏢 25 companies using in production
- 📊 25 case studies

**Content:**
- 📝 Featured in Python Weekly
- 🎤 Accepted to PyCon 2027
- 🐦 5,000 Twitter followers

### 12 Month Goals (March 2027)

**GitHub:**
- ⭐ 5,000 stars
- 🍴 300 forks
- 📝 50 contributors

**PyPI:**
- 📦 200,000 monthly downloads
- 🔄 500 dependents

**Production:**
- 🏢 100 companies using in production
- 📊 50 case studies
- 💰 $50k ARR (enterprise support)

**Content:**
- 📝 AWS re:Invent mention
- 🎤 PyCon 2027 talk delivered
- 📰 Featured in major tech publications
- 🐦 10,000 Twitter followers

---

## Risk Management

### Technical Risks

**Risk: Performance doesn't meet targets**
- Mitigation: Extensive profiling, SQS batch operations, async optimization
- Contingency: Document trade-offs, continue optimizing post-launch

**Risk: AWS API rate limits**
- Mitigation: Exponential backoff, request throttling, batch operations
- Contingency: Document limits, provide configuration options

**Risk: Serialization issues with complex objects**
- Mitigation: JSON primary, CloudPickle fallback, clear documentation
- Contingency: Add more serializers if needed

### Market Risks

**Risk: Celery improves and closes gap**
- Mitigation: Focus on unique features (FIFO, cost tracking, AWS-native)
- Contingency: Continue differentiating, maintain simplicity advantage

**Risk: Taskiq gains SQS-native features**
- Mitigation: Move fast, community engagement, better docs
- Contingency: Collaborate or find new differentiators

**Risk: Low adoption due to SQS-only**
- Mitigation: Target AWS-heavy audience, emphasize benefits
- Contingency: Consider Redis/RabbitMQ support in future

### Execution Risks

**Risk: Timeline slips**
- Mitigation: Weekly checkpoints, ruthless prioritization
- Contingency: Cut scope, ship MVP, iterate

**Risk: Burnout / resource constraints**
- Mitigation: Realistic schedule, community contributions
- Contingency: Extend timeline, seek help

**Risk: Security vulnerability discovered**
- Mitigation: Security audit, dependency scanning
- Contingency: Rapid patch, transparent communication

---

## Next Steps

### Immediate Actions (This Week)

1. ✅ Create `v2-development` branch
2. ✅ Set up GitHub project board
3. ✅ Configure CI/CD pipeline
4. ✅ Begin Phase 1 (Python 3 + boto3 migration)
5. ✅ Recruit contributors (if desired)

### Decision Points

**Before Starting:**
- Confirm timeline (10 weeks realistic?)
- Determine solo vs team effort
- Set up development environment
- Finalize scope (anything to cut?)

**After Phase 1:**
- Review performance of async implementation
- Validate API design with early testers
- Confirm FIFO support is feasible

**After Phase 2:**
- Get feedback on SQS-native features
- Validate cost tracking accuracy
- Confirm unique value prop is clear

**After Phase 3:**
- User test CLI and dashboard
- Validate localstack integration works smoothly
- Confirm developer experience meets goals

**Before Launch:**
- Final security audit
- Performance benchmarks published
- Launch content ready
- Community channels ready

---

## Conclusion

SimpleQ v2.0 represents a **unique opportunity** to become the standard task queue for AWS-native Python applications. Our competitive research shows:

1. **Clear market gap** - No SQS-native, async-first, simple queue exists
2. **Strong differentiation** - FIFO, cost tracking, type safety are unique
3. **Right timing** - Async adoption soaring, AWS growing, serverless trend
4. **Achievable scope** - 10 weeks is aggressive but realistic

**Success depends on:**
- Excellent execution on core features
- World-class documentation and DX
- Strong launch and community building
- Maintaining focus (no scope creep)

**If we execute well, SimpleQ can:**
- Become the default choice for Python + AWS
- Reach 5,000 stars in 12 months
- Support 100+ companies in production
- Generate enterprise support revenue

**The plan is solid. Let's build it! 🚀**

---

**Last Updated:** March 1, 2026
**Status:** Ready to Execute
**Next Review:** After Phase 1 completion
