# SimpleQ Development Guide for AI Agents

**Last Updated:** March 1, 2026
**Version:** 2.0.0

---

## Project Vision

**SimpleQ is the best Python task queue library ever built.**

Our mission is to create the most developer-friendly, reliable, and cost-effective task queue for AWS, combining RQ's simplicity with enterprise-grade reliability and AWS-native features that no competitor offers.

### Core Principles

1. **Simplicity First** - Five lines of code from install to first job
2. **AWS-Native** - Leverage SQS features, don't abstract them away
3. **Type-Safe** - Full type hints, Pydantic validation, modern Python
4. **Production-Ready** - DLQ, monitoring, observability out-of-box
5. **Zero Configuration** - Reasonable defaults that work for 90% of use cases
6. **Cost-Conscious** - Track, optimize, and report costs automatically

### What Makes SimpleQ Special

**Unique features NO competitor has:**
- SQS FIFO queue support with message groups
- Built-in cost tracking and optimization
- Native async/await (not middleware)
- Type-safe tasks with Pydantic schemas
- Zero-config localstack integration
- Deep AWS integration (X-Ray, CloudWatch, EventBridge)

---

## Development Philosophy

### Test-Driven Development (TDD)

**All code must be written using TDD principles:**

1. **Write the test first** - Before implementing any feature
2. **Watch it fail** - Ensure the test actually tests something
3. **Write minimal code** - Just enough to make the test pass
4. **Refactor** - Clean up while keeping tests green
5. **Repeat** - For every feature, bug fix, and change

**Test Coverage Requirements:**
- **Overall coverage:** 90% minimum
- **Core modules:** 95% minimum (queue.py, task.py, worker.py, job.py)
- **New features:** 100% coverage required
- **Bug fixes:** Must include regression test

### Code Quality Standards

#### Clean Code Principles

**Follow these guidelines for all code:**

1. **Readability** - Code is read 10x more than written
   ```python
   # Good
   async def enqueue_job(self, job: Job, delay_seconds: int = 0) -> None:
       """Enqueue a job with optional delay."""
       ...

   # Bad
   async def eq(self, j, d=0):
       ...
   ```

2. **Single Responsibility** - One class/function, one purpose
   ```python
   # Good
   class CostTracker:
       def track_request(self, operation: str) -> None: ...
       def get_total_cost(self) -> float: ...

   # Bad
   class Queue:
       def enqueue(self): ...
       def track_cost(self): ...  # Mixing concerns
   ```

3. **DRY (Don't Repeat Yourself)** - Extract common patterns
   ```python
   # Good
   async def _get_queue(self, sqs) -> Queue:
       """Shared queue retrieval logic."""
       ...

   # Bad - Same logic copy-pasted in multiple methods
   ```

4. **Explicit is better than implicit**
   ```python
   # Good
   def retry_with_backoff(
       self,
       max_retries: int = 3,
       backoff_strategy: Literal["exponential", "linear"] = "exponential"
   ) -> None:
       ...

   # Bad
   def retry(self, r=3, s="exp"):  # Unclear what these mean
       ...
   ```

5. **Small functions** - Aim for < 20 lines per function
   ```python
   # Good - Each function does one thing
   async def enqueue(self, job: Job) -> None:
       message = self._serialize_job(job)
       await self._send_to_sqs(message)
       self._track_cost()

   # Bad - 100-line function doing everything
   ```

#### Type Hints

**All code must have complete type hints:**

```python
# Required
from typing import AsyncIterator, Literal
from pydantic import BaseModel

async def enqueue(
    self,
    job: Job,
    *,
    delay_seconds: int = 0,
    message_group_id: str | None = None,
) -> None:
    """Enqueue a job to the queue."""
    ...

async def jobs(self) -> AsyncIterator[Job]:
    """Iterate through jobs in the queue."""
    ...

BackoffStrategy = Literal["linear", "exponential", "constant"]

def calculate_backoff(
    strategy: BackoffStrategy,
    retry_count: int
) -> int:
    ...
```

**Configure mypy strict mode:**
```ini
[tool.mypy]
python_version = "3.10"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_any_generics = true
disallow_subclassing_any = true
disallow_untyped_calls = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
```

#### Code Style

**Use `ruff` for linting and formatting:**

```toml
[tool.ruff]
target-version = "py310"
line-length = 88

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # pyflakes
    "I",      # isort
    "B",      # flake8-bugbear
    "C4",     # flake8-comprehensions
    "UP",     # pyupgrade
    "ARG",    # flake8-unused-arguments
    "SIM",    # flake8-simplify
    "TCH",    # flake8-type-checking
    "PERF",   # perflint
]

ignore = [
    "E501",   # Line too long (handled by formatter)
    "B008",   # Do not perform function calls in argument defaults
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["ARG", "S101"]  # Allow unused args and asserts in tests
```

**Pre-commit hooks are mandatory:**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.3.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.9.0
    hooks:
      - id: mypy
        additional_dependencies:
          - types-all
          - boto3-stubs[sqs]
```

---

## Package Management

### UV Package Manager

**Use UV for all dependency management:**

UV is faster, more reliable, and resolves dependencies better than pip.

**Installation:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Project setup:**
```bash
# Install dependencies
uv pip install -e ".[dev,observability,dashboard]"

# Add a new dependency
uv pip install --upgrade boto3

# Lock dependencies
uv pip freeze > requirements.lock
```

**Why UV:**
- ⚡ 10-100x faster than pip
- 🔒 Better dependency resolution
- 🎯 Consistent lock files
- 🛡️ Built-in security checks
- 📦 Works with existing pyproject.toml

### Dependency Management

**Always use latest stable versions:**

```toml
[project]
dependencies = [
    # Core - Always latest stable
    "boto3>=1.34.0",
    "aioboto3>=13.0.0",
    "pydantic>=2.6.0",
    "structlog>=24.1.0",

    # CLI
    "typer>=0.9.0",
    "rich>=13.7.0",
]

[project.optional-dependencies]
dev = [
    # Testing
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "pytest-timeout>=2.2.0",

    # Type checking
    "mypy>=1.8.0",
    "boto3-stubs[sqs]>=1.34.0",

    # Linting
    "ruff>=0.3.0",

    # Local AWS
    "localstack>=3.2.0",
    "moto>=5.0.0",
]

observability = [
    "prometheus-client>=0.20.0",
    "opentelemetry-api>=1.23.0",
    "aws-xray-sdk>=2.13.0",
]

dashboard = [
    "httpx>=0.27.0",
    "jinja2>=3.1.0",
]
```

**Security best practices:**

1. **Use Dependabot** - Auto-update dependencies
   ```yaml
   # .github/dependabot.yml
   version: 2
   updates:
     - package-ecosystem: "pip"
       directory: "/"
       schedule:
         interval: "weekly"
       open-pull-requests-limit: 10
   ```

2. **Security scanning** - Use Safety or pip-audit
   ```bash
   uv pip install safety
   safety check
   ```

3. **Pin exact versions in lock file** - But allow ranges in pyproject.toml
   ```toml
   # pyproject.toml - Allow minor updates
   "boto3>=1.34.0,<2.0.0"

   # requirements.lock - Exact versions
   boto3==1.34.58
   ```

4. **Regular audits** - Weekly security review
   ```bash
   # GitHub Actions runs this automatically
   uv pip audit
   ```

---

## Testing Strategy

### Test Organization

```
tests/
├── unit/                      # Fast, isolated unit tests
│   ├── test_queue.py         # Queue class tests
│   ├── test_task.py          # Task decorator tests
│   ├── test_job.py           # Job model tests
│   ├── test_worker.py        # Worker logic tests
│   ├── test_serializers.py  # Serialization tests
│   └── test_cost_tracker.py # Cost tracking tests
│
├── integration/               # Tests with real AWS (localstack)
│   ├── test_fifo_queues.py  # FIFO queue behavior
│   ├── test_dlq.py           # Dead letter queue
│   ├── test_retry.py         # Retry logic
│   ├── test_batching.py      # Batch operations
│   └── test_end_to_end.py    # Full workflows
│
├── performance/               # Performance benchmarks
│   ├── benchmark.py          # Main benchmark suite
│   └── test_throughput.py    # Throughput tests
│
└── conftest.py               # Shared fixtures
```

### Writing Tests

#### Unit Tests

**Fast, isolated, no external dependencies:**

```python
# tests/unit/test_job.py
import pytest
from simpleq import Job

def test_job_serialization():
    """Job should serialize to JSON and back."""
    job = Job(
        task_name="send_email",
        args=("user@example.com",),
        kwargs={"subject": "Hello"},
    )

    serialized = job.serialize()
    deserialized = Job.deserialize(serialized)

    assert deserialized.task_name == job.task_name
    assert deserialized.args == job.args
    assert deserialized.kwargs == job.kwargs


def test_job_deduplication_id():
    """Job should generate consistent deduplication IDs."""
    job1 = Job(task_name="test", args=(1, 2), kwargs={"key": "value"})
    job2 = Job(task_name="test", args=(1, 2), kwargs={"key": "value"})

    assert job1.get_deduplication_id() == job2.get_deduplication_id()


def test_job_deduplication_id_differs_for_different_args():
    """Different args should produce different dedup IDs."""
    job1 = Job(task_name="test", args=(1,))
    job2 = Job(task_name="test", args=(2,))

    assert job1.get_deduplication_id() != job2.get_deduplication_id()
```

#### Integration Tests

**Test real behavior with localstack:**

```python
# tests/integration/test_fifo_queues.py
import pytest
from simpleq import SimpleQ, Job

@pytest.mark.asyncio
async def test_fifo_queue_ordering(localstack_session):
    """FIFO queues should maintain order within message groups."""
    sq = SimpleQ()
    queue = sq.queue("test.fifo", fifo=True)

    # Enqueue 10 jobs in order
    for i in range(10):
        job = Job(task_name="test", args=(i,))
        await queue.enqueue(job, message_group_id="group1")

    # Receive and verify order
    received = []
    async for job in queue.jobs():
        received.append(job.args[0])
        if len(received) == 10:
            break

    assert received == list(range(10)), "FIFO order not maintained"


@pytest.mark.asyncio
async def test_message_deduplication(localstack_session):
    """Duplicate messages should be rejected within 5 minutes."""
    sq = SimpleQ()
    queue = sq.queue(
        "test.fifo",
        fifo=True,
        content_based_deduplication=False,
    )

    job = Job(task_name="test", args=(1,), deduplication_id="unique-123")

    # Send same job twice
    await queue.enqueue(job, message_group_id="group1")
    await queue.enqueue(job, message_group_id="group1")

    # Should only receive one message
    received = []
    async for job in queue.jobs():
        received.append(job)
        if len(received) == 2:
            break

    assert len(received) == 1, "Deduplication failed"
```

#### Test Fixtures

**Shared test setup:**

```python
# tests/conftest.py
import pytest
import asyncio
import os
from simpleq import SimpleQ

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def localstack_session():
    """Configure for localstack."""
    os.environ['SIMPLEQ_ENDPOINT_URL'] = 'http://localhost:4566'
    os.environ['AWS_ACCESS_KEY_ID'] = 'test'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'test'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

    yield

    # Cleanup
    for key in ['SIMPLEQ_ENDPOINT_URL', 'AWS_ACCESS_KEY_ID',
                'AWS_SECRET_ACCESS_KEY']:
        os.environ.pop(key, None)


@pytest.fixture
async def test_queue(localstack_session):
    """Create a test queue."""
    sq = SimpleQ()
    queue = sq.queue('test-queue')
    await queue._ensure_queue_exists()

    yield queue

    # Cleanup
    try:
        await queue.delete()
    except Exception:
        pass  # Queue might not exist


@pytest.fixture
async def fifo_queue(localstack_session):
    """Create a FIFO test queue."""
    sq = SimpleQ()
    queue = sq.queue('test.fifo', fifo=True)
    await queue._ensure_queue_exists()

    yield queue

    try:
        await queue.delete()
    except Exception:
        pass
```

### Running Tests

**All tests run via pytest:**

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=simpleq --cov-report=html --cov-report=term

# Run only unit tests (fast)
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run specific test
pytest tests/unit/test_queue.py::test_queue_creation

# Run with verbose output
pytest -v

# Run in parallel (faster)
pytest -n auto

# Watch mode (re-run on changes)
pytest-watch
```

### Test Quality Requirements

**Every test must:**

1. ✅ Have a clear, descriptive name
2. ✅ Test one thing only
3. ✅ Be independent (no test order dependency)
4. ✅ Be fast (< 100ms for unit tests)
5. ✅ Have clear assertions
6. ✅ Clean up after itself
7. ✅ Be deterministic (no flaky tests)

**Example of good test structure:**

```python
def test_queue_enqueue_increments_cost_tracker():
    """
    Given a queue with a cost tracker
    When a job is enqueued
    Then the cost tracker should increment send requests by 1
    """
    # Arrange
    tracker = CostTracker()
    queue = Queue("test", cost_tracker=tracker)
    job = Job(task_name="test")

    # Act
    asyncio.run(queue.enqueue(job))

    # Assert
    metrics = tracker.get_metrics("test")
    assert metrics.send_requests == 1
```

---

## Continuous Integration

### GitHub Actions

**All CI/CD runs through GitHub Actions:**

#### Main Test Workflow

```yaml
# .github/workflows/test.yml
name: Test

on:
  push:
    branches: [main, master, v2-development]
  pull_request:
    branches: [main, master, v2-development]

jobs:
  test:
    name: Test Python ${{ matrix.python-version }}
    runs-on: ubuntu-latest

    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    services:
      localstack:
        image: localstack/localstack:latest
        ports:
          - 4566:4566
        env:
          SERVICES: sqs
          DEBUG: 1

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v1

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: uv pip install -e ".[dev,observability,dashboard]"

      - name: Lint with ruff
        run: |
          ruff check .
          ruff format --check .

      - name: Type check with mypy
        run: mypy simpleq

      - name: Run tests
        run: |
          pytest \
            --cov=simpleq \
            --cov-report=xml \
            --cov-report=term \
            --cov-fail-under=90 \
            -v
        env:
          SIMPLEQ_ENDPOINT_URL: http://localhost:4566

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
          fail_ci_if_error: true
```

#### Security Scanning

```yaml
# .github/workflows/security.yml
name: Security

on:
  push:
    branches: [main, master]
  pull_request:
  schedule:
    - cron: '0 0 * * 0'  # Weekly

jobs:
  security:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v1

      - name: Install dependencies
        run: uv pip install -e ".[dev]"

      - name: Run safety check
        run: |
          uv pip install safety
          safety check

      - name: Run bandit
        run: |
          uv pip install bandit
          bandit -r simpleq/

      - name: Audit dependencies
        run: uv pip audit
```

#### Performance Benchmarks

```yaml
# .github/workflows/benchmark.yml
name: Benchmark

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  benchmark:
    runs-on: ubuntu-latest

    services:
      localstack:
        image: localstack/localstack:latest
        ports:
          - 4566:4566
        env:
          SERVICES: sqs

    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v1

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv pip install -e ".[dev]"

      - name: Run benchmarks
        run: pytest tests/performance/ -v
        env:
          SIMPLEQ_ENDPOINT_URL: http://localhost:4566

      - name: Comment PR with results
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            // Post benchmark results as PR comment
            // (Implementation details...)
```

#### Release Workflow

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v1

      - name: Build package
        run: |
          uv pip install build
          python -m build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          generate_release_notes: true
```

### Pull Request Requirements

**All PRs must pass:**

1. ✅ All tests pass (unit + integration)
2. ✅ Code coverage ≥ 90%
3. ✅ No linting errors (ruff)
4. ✅ No type errors (mypy)
5. ✅ No security issues (safety, bandit)
6. ✅ Performance benchmarks don't regress
7. ✅ Documentation updated if needed

**PR template:**

```markdown
## Description
<!-- What does this PR do? -->

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
<!-- How was this tested? -->
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing performed

## Checklist
- [ ] Code follows style guidelines (ruff)
- [ ] Type hints added (mypy clean)
- [ ] Tests added and passing
- [ ] Coverage ≥ 90%
- [ ] Documentation updated
- [ ] CHANGELOG.md updated

## Performance Impact
<!-- Any performance implications? -->
```

---

## Configuration & Defaults

### Reasonable Defaults

**SimpleQ should work out-of-box with zero configuration for 90% of use cases:**

#### Default Configuration

```python
# simpleq/config.py
import os
from typing import Literal

class DefaultConfig:
    """Default configuration values."""

    # AWS Configuration
    REGION: str = "us-east-1"
    ENDPOINT_URL: str | None = None  # Auto-detect localstack

    # Queue Configuration
    BATCH_SIZE: int = 10  # SQS max
    WAIT_SECONDS: int = 20  # SQS max for long polling
    VISIBILITY_TIMEOUT: int = 300  # 5 minutes

    # Worker Configuration
    CONCURRENCY: int = 10
    GRACEFUL_SHUTDOWN_TIMEOUT: int = 30

    # Retry Configuration
    MAX_RETRIES: int = 3
    BACKOFF_STRATEGY: Literal["exponential", "linear", "constant"] = "exponential"

    # Cost Tracking
    ENABLE_COST_TRACKING: bool = True
    SQS_PRICE_PER_MILLION: float = 0.40  # USD per million requests

    # Observability
    ENABLE_METRICS: bool = True
    ENABLE_TRACING: bool = False  # Requires X-Ray SDK
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @classmethod
    def from_env(cls) -> "DefaultConfig":
        """Load config from environment variables."""
        config = cls()

        # Allow env overrides
        if region := os.getenv("AWS_REGION"):
            config.REGION = region

        if endpoint := os.getenv("SIMPLEQ_ENDPOINT_URL"):
            config.ENDPOINT_URL = endpoint

        if concurrency := os.getenv("SIMPLEQ_CONCURRENCY"):
            config.CONCURRENCY = int(concurrency)

        return config
```

#### Auto-Detection Features

**Automatically detect and configure for common environments:**

```python
def auto_detect_environment() -> dict[str, str]:
    """Auto-detect environment and configure accordingly."""
    config = {}

    # Detect localstack
    if os.getenv("LOCALSTACK_HOSTNAME") or os.path.exists("/.dockerenv"):
        config["endpoint_url"] = "http://localhost:4566"
        logger.info("Detected localstack environment")

    # Detect CI
    if os.getenv("CI"):
        config["endpoint_url"] = "http://localhost:4566"
        config["log_level"] = "DEBUG"
        logger.info("Detected CI environment")

    # Detect AWS Lambda
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        config["enable_xray"] = True
        logger.info("Detected Lambda environment")

    # Detect ECS
    if os.getenv("ECS_CONTAINER_METADATA_URI"):
        config["enable_xray"] = True
        logger.info("Detected ECS environment")

    return config
```

### Environment Variables

**Support standard AWS env vars plus SimpleQ-specific:**

```bash
# AWS Standard
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx

# SimpleQ Specific
SIMPLEQ_ENDPOINT_URL=http://localhost:4566  # For localstack
SIMPLEQ_CONCURRENCY=20                       # Worker concurrency
SIMPLEQ_LOG_LEVEL=DEBUG                      # Logging level
SIMPLEQ_ENABLE_XRAY=true                     # AWS X-Ray tracing
SIMPLEQ_COST_TRACKING=true                   # Cost tracking
```

---

## Documentation Standards

### Docstring Format

**Use Google-style docstrings with full type information:**

```python
async def enqueue(
    self,
    job: Job,
    *,
    delay_seconds: int = 0,
    message_group_id: str | None = None,
) -> None:
    """Enqueue a job to the queue.

    Args:
        job: The job to enqueue.
        delay_seconds: Optional delay before job is available (max 900s).
        message_group_id: Message group ID for FIFO queues. Required for
            FIFO queues. Jobs with same group ID are processed in order.

    Raises:
        ValueError: If message_group_id is required but not provided.
        ClientError: If SQS operation fails.

    Example:
        >>> queue = Queue("emails")
        >>> job = Job(task_name="send_email", args=("user@example.com",))
        >>> await queue.enqueue(job)

        With delay:
        >>> await queue.enqueue(job, delay_seconds=300)  # 5 minute delay

        FIFO queue:
        >>> fifo_queue = Queue("orders.fifo", fifo=True)
        >>> await fifo_queue.enqueue(job, message_group_id="customer-123")
    """
```

### Inline Comments

**Comment the "why", not the "what":**

```python
# Good - Explains reasoning
# Use exponential backoff to avoid overwhelming the API
# during transient failures
delay = 2 ** retry_count

# Bad - States the obvious
# Set delay to 2 to the power of retry_count
delay = 2 ** retry_count
```

### Module Documentation

**Every module needs a module docstring:**

```python
"""Task queue abstractions for SimpleQ.

This module provides the core Queue class for interacting with AWS SQS.
It handles message serialization, batching, long polling, and cost tracking.

The Queue class supports both standard and FIFO queues, with automatic
dead letter queue configuration and message deduplication.

Example:
    Basic usage:
    >>> from simpleq import SimpleQ
    >>> sq = SimpleQ()
    >>> queue = sq.queue("emails")

    FIFO queue with DLQ:
    >>> queue = sq.queue("orders.fifo", fifo=True, dlq=True)

See Also:
    - task.py: Task decorator and registration
    - worker.py: Worker implementation
    - job.py: Job model and serialization
"""
```

---

## Error Handling

### Exception Hierarchy

**Define clear exception hierarchy:**

```python
# simpleq/exceptions.py

class SimpleQError(Exception):
    """Base exception for all SimpleQ errors."""
    pass


class ConfigurationError(SimpleQError):
    """Raised when configuration is invalid."""
    pass


class QueueError(SimpleQError):
    """Base exception for queue-related errors."""
    pass


class QueueNotFoundError(QueueError):
    """Raised when queue doesn't exist."""
    pass


class SerializationError(SimpleQError):
    """Raised when job serialization fails."""
    pass


class RetryExhaustedError(SimpleQError):
    """Raised when all retries are exhausted."""
    pass
```

### Error Handling Patterns

**Handle errors gracefully with clear messages:**

```python
async def enqueue(self, job: Job) -> None:
    """Enqueue a job with proper error handling."""
    try:
        await self._send_to_sqs(job)
    except ClientError as e:
        error_code = e.response['Error']['Code']

        if error_code == 'QueueDoesNotExist':
            raise QueueNotFoundError(
                f"Queue '{self.name}' does not exist. "
                f"Create it with: simpleq queue create {self.name}"
            ) from e

        elif error_code == 'AccessDenied':
            raise ConfigurationError(
                f"Access denied to queue '{self.name}'. "
                f"Check AWS credentials and IAM permissions."
            ) from e

        else:
            # Re-raise with context
            raise QueueError(
                f"Failed to enqueue job to '{self.name}': {e}"
            ) from e

    except Exception as e:
        logger.exception("Unexpected error enqueueing job")
        raise SimpleQError(f"Unexpected error: {e}") from e
```

---

## Logging Standards

### Structured Logging

**Use structlog for structured, searchable logs:**

```python
import structlog

logger = structlog.get_logger()

# Good - Structured logging
logger.info(
    "job_enqueued",
    queue_name=self.name,
    task_name=job.task_name,
    delay_seconds=delay_seconds,
    message_group_id=message_group_id,
)

# Bad - Unstructured string
logger.info(f"Enqueued job {job.task_name} to {self.name}")
```

### Log Levels

**Use appropriate log levels:**

- **DEBUG** - Detailed diagnostic information
- **INFO** - General operational information
- **WARNING** - Something unexpected but handled
- **ERROR** - Error that prevented operation
- **CRITICAL** - System failure

```python
# DEBUG - Detailed info
logger.debug("sqs_request", operation="receive_message", max_messages=10)

# INFO - Normal operation
logger.info("job_completed", task_name="send_email", duration_ms=150)

# WARNING - Unexpected but handled
logger.warning("dlq_threshold_reached", queue_name="emails", messages=100)

# ERROR - Operation failed
logger.error("job_failed", task_name="process_order", error=str(e))

# CRITICAL - System failure
logger.critical("all_regions_failed", regions=self.regions)
```

---

## Performance Considerations

### Optimization Guidelines

1. **Use asyncio properly** - Don't block the event loop
   ```python
   # Good
   async def process_jobs(self):
       tasks = [self._process_job(job) for job in jobs]
       await asyncio.gather(*tasks)

   # Bad - Blocks event loop
   async def process_jobs(self):
       for job in jobs:
           time.sleep(1)  # NEVER do this in async code
   ```

2. **Batch SQS operations** - Always use max batch size (10)
   ```python
   # Good - Batch receive
   messages = await queue.receive_messages(MaxNumberOfMessages=10)

   # Bad - One at a time
   for _ in range(10):
       message = await queue.receive_messages(MaxNumberOfMessages=1)
   ```

3. **Use long polling** - Reduce API calls
   ```python
   # Good - 20 second wait
   messages = await queue.receive_messages(WaitTimeSeconds=20)

   # Bad - Short polling (more expensive)
   messages = await queue.receive_messages(WaitTimeSeconds=0)
   ```

4. **Connection pooling** - Reuse boto3 sessions
   ```python
   # Good - Reuse session
   self._session = aioboto3.Session()
   async with self._session.resource('sqs') as sqs:
       # All operations use same session

   # Bad - Create new session each time
   async def enqueue(self, job):
       session = aioboto3.Session()  # Wasteful
   ```

### Performance Testing

**Include performance tests:**

```python
# tests/performance/test_throughput.py
import pytest
import time
from simpleq import SimpleQ

@pytest.mark.performance
async def test_enqueue_throughput():
    """Should enqueue 10,000 jobs in < 30 seconds."""
    sq = SimpleQ()
    queue = sq.queue("perf-test")

    @sq.task(queue=queue)
    async def noop():
        pass

    start = time.time()

    # Enqueue 10,000 jobs
    for i in range(10_000):
        await noop.delay()

    duration = time.time() - start

    assert duration < 30, f"Enqueue took {duration:.2f}s, expected < 30s"
    print(f"Throughput: {10_000 / duration:.0f} jobs/sec")
```

---

## Security Best Practices

### Input Validation

**Validate all inputs with Pydantic:**

```python
from pydantic import BaseModel, Field, field_validator

class JobInput(BaseModel):
    """Validated job input."""

    task_name: str = Field(..., min_length=1, max_length=255)
    args: tuple = Field(default_factory=tuple)
    kwargs: dict = Field(default_factory=dict)

    @field_validator('task_name')
    @classmethod
    def validate_task_name(cls, v: str) -> str:
        """Ensure task name is safe."""
        if not v.replace('_', '').isalnum():
            raise ValueError("Task name must be alphanumeric")
        return v
```

### Secrets Management

**Never log or expose secrets:**

```python
# Good - Redact secrets from logs
logger.info("queue_created", queue_url=queue_url)  # Safe

# Bad - Exposes credentials
logger.info("connecting", access_key=aws_access_key)  # NEVER do this
```

### Dependencies

**Keep dependencies updated and audited:**

```bash
# Run in CI and locally
uv pip install safety
safety check

# Audit for known vulnerabilities
uv pip audit
```

---

## Summary Checklist

When implementing any feature, ensure:

- [ ] **TDD** - Tests written first
- [ ] **Coverage** - 90%+ coverage
- [ ] **Type hints** - Full type annotations
- [ ] **Docstrings** - Complete documentation
- [ ] **Clean code** - Follows all style guidelines
- [ ] **Error handling** - Graceful error handling
- [ ] **Logging** - Structured logging
- [ ] **Performance** - Optimized for speed
- [ ] **Security** - Input validation, no secrets in logs
- [ ] **Tests pass** - All CI checks green
- [ ] **UV** - Latest dependencies
- [ ] **No regressions** - Performance benchmarks pass

---

## Quick Reference

### Setup Development Environment

```bash
# Clone repo
git clone https://github.com/rdegges/simpleq.git
cd simpleq

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv pip install -e ".[dev,observability,dashboard]"

# Install pre-commit hooks
pre-commit install

# Run tests
pytest

# Start localstack
docker run -d -p 4566:4566 localstack/localstack

# Run with localstack
SIMPLEQ_ENDPOINT_URL=http://localhost:4566 pytest
```

### Common Commands

```bash
# Lint
ruff check .
ruff format .

# Type check
mypy simpleq

# Test
pytest
pytest --cov=simpleq --cov-report=html

# Security
safety check
bandit -r simpleq/

# Benchmark
pytest tests/performance/
```

---

**Remember: SimpleQ is the best Python task queue ever built. Every line of code should reflect that standard of excellence!** 🚀
