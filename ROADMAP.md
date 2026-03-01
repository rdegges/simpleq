# SimpleQ v2.0 Roadmap

**Vision:** The Python task queue for AWS. Zero infrastructure, infinite scale, pennies in cost.

**Unique Value:** SQS-native, async-first, RQ-simple, enterprise-reliable, cost-optimized.

---

## Phase 1: Foundation (Weeks 1-2) 🏗️

**Goal:** Modernize codebase to 2026 standards

### Tasks

- [ ] **Python 3.10+ Migration**
  - Remove all Python 2 code
  - Add `from __future__ import annotations`
  - Use modern syntax (match/case, walrus operator, etc.)

- [ ] **Dependency Updates**
  - Replace `boto` → `boto3` + `aioboto3`
  - Add `pydantic` for validation
  - Add `structlog` for logging
  - Add `httpx` for async HTTP

- [ ] **Modern Packaging**
  - Convert `setup.py` → `pyproject.toml`
  - Add `uv` or `poetry` support
  - Semantic versioning with `setuptools-scm`

- [ ] **Type Hints**
  - Add type hints to all functions
  - Configure `mypy` strict mode
  - Type-safe boto3 with stubs

- [ ] **CI/CD**
  - GitHub Actions workflows
  - `ruff` for linting
  - `mypy` for type checking
  - `pytest` with coverage (>90%)
  - Pre-commit hooks

- [ ] **Async Core**
  - Rewrite `Queue` with async/await
  - Support both sync and async tasks
  - Use `aioboto3` for SQS operations
  - Async worker implementation

**Deliverable:** Modernized codebase, passing tests, 90%+ coverage

---

## Phase 2: SQS-Native Features (Weeks 3-4) 🚀

**Goal:** Deep SQS integration that competitors can't match

### Tasks

- [ ] **FIFO Queue Support**
  ```python
  sq = SimpleQ(fifo=True)

  @sq.task(message_group_id="user-123")
  async def process_order(order_id: str):
      # Guaranteed ordering within message group
      ...
  ```

- [ ] **Message Deduplication**
  ```python
  @sq.task(deduplication_id=lambda args: args[0])
  async def send_email(email_id: str):
      # Automatic dedup for 5 minutes
      ...
  ```

- [ ] **Native Dead Letter Queue**
  ```python
  sq = SimpleQ(
      dlq=True,
      max_retries=3,
      dlq_retention_days=14
  )
  ```

- [ ] **Message Attributes**
  ```python
  @sq.task(attributes={"priority": "high", "source": "api"})
  async def urgent_task():
      ...
  ```

- [ ] **Visibility Timeout Management**
  - Auto-extend for long-running jobs
  - Heartbeat mechanism
  - Prevent job loss

- [ ] **Cost Optimization**
  - Batch send/receive (10 messages)
  - Long polling (20 second waits)
  - API call tracking
  - Cost metrics and dashboard

**Deliverable:** SQS-native features no competitor has

---

## Phase 3: Developer Experience (Weeks 5-6) 🎨

**Goal:** RQ-level simplicity with enterprise power

### Tasks

- [ ] **Type-Safe Task API**
  ```python
  from pydantic import BaseModel

  class EmailTask(BaseModel):
      to: str
      subject: str
      body: str

  @sq.task(schema=EmailTask)
  async def send_email(task: EmailTask):
      # Automatic validation, type hints everywhere
      ...
  ```

- [ ] **Zero-Config Local Development**
  ```python
  # Auto-detects localstack in dev
  # Uses real SQS in production
  # NO configuration needed

  sq = SimpleQ()  # Just works
  ```

- [ ] **CLI Tool**
  ```bash
  simpleq worker start --queues my-queue --concurrency 10
  simpleq queue create my-queue --fifo
  simpleq queue stats my-queue
  simpleq job enqueue my-queue send_email --data '{"to":"..."}'
  simpleq cost report --last-30-days
  ```

- [ ] **Framework Integrations**
  - FastAPI plugin
  - Django management commands
  - Flask extension

- [ ] **Observability**
  - Prometheus metrics endpoint
  - OpenTelemetry tracing
  - Structured JSON logging
  - CloudWatch integration
  - AWS X-Ray tracing

- [ ] **Web Dashboard**
  - Real-time job monitoring
  - Queue statistics
  - Worker health
  - **Cost tracking** (unique!)
  - DLQ management
  - Job replay

**Deliverable:** Best-in-class DX, production-ready observability

---

## Phase 4: Advanced Features (Weeks 7-8) ⚡

**Goal:** Enterprise features for production

### Tasks

- [ ] **Retry & Error Handling**
  ```python
  @sq.task(
      max_retries=5,
      backoff="exponential",
      retry_exceptions=[NetworkError]
  )
  async def flaky_api_call():
      ...
  ```

- [ ] **Job Scheduling**
  ```python
  # Delayed execution (SQS delay seconds)
  await send_email.delay(delay_seconds=300)

  # EventBridge for cron
  @sq.cron("0 9 * * *")  # Daily 9 AM
  async def daily_report():
      ...
  ```

- [ ] **Simple Chains**
  ```python
  # Simple workflow
  result = await (
      fetch_data.s() |
      process_data.s() |
      save_results.s()
  ).run()
  ```

- [ ] **Multi-Region Support**
  ```python
  sq = SimpleQ(
      regions=["us-east-1", "us-west-2"],
      failover=True,
      routing="latency"
  )
  ```

- [ ] **Batch Processing**
  ```python
  @sq.batch(size=100, timeout=30)
  async def process_batch(jobs: list[Job]):
      # Process 100 jobs at once
      ...
  ```

- [ ] **Job Deduplication**
  - Content-based deduplication
  - Custom deduplication IDs
  - 5-minute window

**Deliverable:** Enterprise-ready, production-tested

---

## Phase 5: Documentation & Launch (Weeks 9-10) 📚

**Goal:** World-class documentation and successful launch

### Tasks

- [ ] **Documentation Site**
  - MkDocs Material theme
  - Quick start (< 5 min to first job)
  - API reference (auto-generated)
  - Architecture deep-dive
  - Migration guides (Celery, RQ, Dramatiq)
  - Cost comparison calculator
  - Video tutorials

- [ ] **Example Projects**
  - FastAPI + SimpleQ starter
  - Django + SimpleQ starter
  - Serverless Lambda workers
  - ECS/Fargate deployment
  - Terraform modules
  - CDK constructs

- [ ] **Benchmarks**
  - vs Celery
  - vs Taskiq
  - vs Dramatiq
  - vs RQ
  - Cost analysis

- [ ] **Launch Content**
  - "Why We Built SimpleQ" blog post
  - "Migrating from Celery" guide
  - "SQS Task Queue Cost Comparison"
  - "Zero to Production in 5 Minutes" video
  - HN/Reddit launch posts
  - ProductHunt launch

- [ ] **Community**
  - Contributing guidelines
  - Good first issues
  - Discord server
  - GitHub Discussions

**Deliverable:** Polished v2.0 release, marketing materials ready

---

## Success Metrics

### 3 Months
- ⭐ 1,000 GitHub stars
- 📦 10,000 monthly PyPI downloads
- 🏢 5 production deployments
- 📝 1 AWS blog mention

### 6 Months
- ⭐ 2,500 GitHub stars
- 📦 50,000 monthly PyPI downloads
- 🏢 25 production deployments
- 📝 Featured in Python Weekly

### 12 Months
- ⭐ 5,000 GitHub stars
- 📦 200,000 monthly PyPI downloads
- 🏢 100 production deployments
- 🎤 PyCon talk accepted
- 💰 $50k ARR from enterprise support

---

## Key Differentiators (Must-Haves)

These features are non-negotiable - they're what makes SimpleQ unique:

1. ✅ **SQS FIFO support** (no competitor has this)
2. ✅ **Cost tracking dashboard** (unique to SimpleQ)
3. ✅ **Zero-config local dev** (localstack auto-detect)
4. ✅ **Type-safe tasks** (Pydantic schemas)
5. ✅ **Native async** (not middleware)
6. ✅ **AWS-deep integration** (X-Ray, CloudWatch, EventBridge)

---

## What We're NOT Building

To stay focused, we explicitly exclude:

- ❌ Multi-cloud support (AWS only)
- ❌ Complex workflow orchestration (use Step Functions)
- ❌ Custom serialization formats (JSON + CloudPickle only)
- ❌ Multiple broker support (SQS only)
- ❌ Real-time streaming (SQS isn't for that)

---

## Team & Resources

**Time Commitment:**
- 10-12 weeks full-time equivalent
- Can be done part-time over 6 months

**Skills Needed:**
- Python async/await expertise
- AWS SQS knowledge
- Task queue domain expertise
- Technical writing (docs)

**Budget:**
- $0 (OSS project)
- AWS costs: ~$50/month for development/testing
- Optional: Domain + hosting for docs site

---

## Next Steps

**Immediate (Week 1):**
1. Create `v2-development` branch
2. Set up GitHub project board
3. Configure GitHub Actions
4. Create issue templates
5. Start Phase 1 tasks

**Quick Wins:**
- Python 3 + boto3 migration (proves we're serious)
- Modern docs site (shows project is active)
- GitHub Actions (demonstrates quality)

**Communication:**
- Weekly progress updates on GitHub Discussions
- Monthly blog posts
- Engage on Reddit/HN when hitting milestones

---

## How to Get Involved

**For Randall:**
- Lead architecture decisions
- Review PRs
- Write launch content
- Community engagement

**For Contributors:**
- Check "Good First Issue" labels
- Join Discord for discussion
- Submit PRs following guidelines

**For Companies:**
- Beta testing opportunities
- Early adopter case studies
- Feature sponsorship
- Enterprise support (future)

---

**Let's build the task queue AWS developers deserve! 🚀**
