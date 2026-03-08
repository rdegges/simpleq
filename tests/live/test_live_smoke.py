"""Optional real-AWS smoke tests."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from simpleq import SimpleQ
from simpleq.exceptions import QueueValidationError
from tests.fixtures import tasks


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key, value)


def _live_simpleq(**overrides: object) -> SimpleQ:
    """Build a SimpleQ client without auto-detecting LocalStack."""
    with patch("simpleq.config.detect_localstack_endpoint", return_value=None):
        return SimpleQ(**overrides)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_standard_and_fifo_smoke(tmp_path) -> None:
    _load_dotenv(Path(".env"))
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing live AWS credentials: {', '.join(missing)}")

    simpleq = _live_simpleq(wait_seconds=0, visibility_timeout=2)
    standard = simpleq.queue(f"simpleq-live-{uuid4().hex[:8]}", dlq=True)
    fifo = simpleq.queue(
        f"simpleq-live-{uuid4().hex[:8]}.fifo",
        fifo=True,
        dlq=True,
        content_based_deduplication=False,
        wait_seconds=0,
    )

    standard_task = simpleq.task(queue=standard)(tasks.record_async)
    fifo_task = simpleq.task(
        queue=fifo,
        message_group_id="group-1",
        deduplication_id=lambda value: f"dedup-{value}",
    )(tasks.record_sync)

    try:
        await standard_task.delay("standard")
        await fifo_task.delay("fifo")
        worker = simpleq.worker(
            queues=[standard, fifo], concurrency=1, poll_interval=0.1
        )
        await worker.work(burst=True)
        assert ("async", "standard") in tasks.LOG
        assert ("sync", "fifo") in tasks.LOG
    finally:
        await standard.delete()
        await fifo.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_existing_queue_attributes_are_reconciled() -> None:
    _load_dotenv(Path(".env"))
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing live AWS credentials: {', '.join(missing)}")

    queue_name = f"simpleq-live-reconcile-{uuid4().hex[:8]}"
    initial_simpleq = _live_simpleq(wait_seconds=0, visibility_timeout=2)
    initial_queue = initial_simpleq.queue(
        queue_name,
        dlq=True,
        wait_seconds=0,
        visibility_timeout=2,
    )
    await initial_queue.ensure_exists()

    updated_simpleq = _live_simpleq(wait_seconds=5, visibility_timeout=9)
    updated_queue = updated_simpleq.queue(
        queue_name,
        dlq=True,
        wait_seconds=5,
        visibility_timeout=9,
    )

    try:
        queue_url = await updated_queue.ensure_exists()
        attributes = await updated_simpleq.transport.get_queue_attributes(
            updated_queue.name,
            queue_url,
            [
                "VisibilityTimeout",
                "ReceiveMessageWaitTimeSeconds",
                "RedrivePolicy",
            ],
        )

        redrive_policy = json.loads(attributes["RedrivePolicy"])
        assert attributes["VisibilityTimeout"] == "9"
        assert attributes["ReceiveMessageWaitTimeSeconds"] == "5"
        assert initial_queue.dlq_name in redrive_policy["deadLetterTargetArn"]
    finally:
        await updated_queue.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fifo_dlq_redrive_smoke() -> None:
    _load_dotenv(Path(".env"))
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing live AWS credentials: {', '.join(missing)}")

    simpleq = _live_simpleq(wait_seconds=0, visibility_timeout=1)
    queue = simpleq.queue(
        f"simpleq-live-fifo-dlq-{uuid4().hex[:8]}.fifo",
        fifo=True,
        dlq=True,
        content_based_deduplication=False,
        wait_seconds=0,
        visibility_timeout=1,
    )
    failing = simpleq.task(
        queue=queue,
        message_group_id=lambda value: "customer-1",
        deduplication_id=lambda value: f"dedup-{value}",
        max_retries=1,
    )(tasks.always_fail)

    try:
        await failing.delay("order-1")
        worker = simpleq.worker(queues=[queue], concurrency=1, poll_interval=0.1)
        await worker.work(burst=True)

        dlq_jobs = [job async for job in queue.get_dlq_jobs(limit=5)]
        assert len(dlq_jobs) == 1
        assert dlq_jobs[0].args == ("order-1",)

        redriven = await queue.redrive_dlq_jobs(limit=1)
        assert redriven == 1

        for _ in range(25):
            received = await queue.receive(max_messages=1, wait_seconds=0)
            if received:
                assert received[0].args == ("order-1",)
                await queue.ack(received[0])
                break
        else:
            raise AssertionError("Redriven FIFO message did not become visible.")
    finally:
        await queue.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_lazy_import_preserves_schema_metadata(
    tmp_path, monkeypatch
) -> None:
    _load_dotenv(Path(".env"))
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing live AWS credentials: {', '.join(missing)}")

    queue_name = f"simpleq-live-lazy-{uuid4().hex[:8]}"
    module_name = f"simpleq_live_lazy_{uuid4().hex[:8]}"
    module_path = tmp_path / f"{module_name}.py"
    module_path.write_text(
        "\n".join(
            [
                "from simpleq import SimpleQ",
                "from unittest.mock import patch",
                "from tests.fixtures.tasks import EmailPayload, LOG",
                "",
                'with patch("simpleq.config.detect_localstack_endpoint", return_value=None):',
                "    sq = SimpleQ(wait_seconds=0, visibility_timeout=2)",
                f'queue = sq.queue("{queue_name}", wait_seconds=0)',
                "",
                "@sq.task(queue=queue, schema=EmailPayload, max_retries=2)",
                "async def send_email(payload: EmailPayload) -> str:",
                '    LOG.append(("live-lazy-schema", payload.subject))',
                "    return payload.subject",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    module = importlib.import_module(module_name)
    worker_simpleq = _live_simpleq(wait_seconds=0, visibility_timeout=2)

    try:
        await module.send_email.delay(
            to="user@example.com",
            subject="Live welcome",
            body="Hello",
        )
        worker = worker_simpleq.worker(
            queues=[queue_name],
            concurrency=1,
            poll_interval=0.1,
        )
        await worker.work(burst=True)

        assert ("live-lazy-schema", "Live welcome") in tasks.LOG
    finally:
        await module.queue.delete()
        sys.modules.pop(module_name, None)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_change_visibility_rejects_invalid_timeout() -> None:
    _load_dotenv(Path(".env"))
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing live AWS credentials: {', '.join(missing)}")

    simpleq = _live_simpleq(wait_seconds=0, visibility_timeout=2)
    queue = simpleq.queue(f"simpleq-live-visibility-{uuid4().hex[:8]}", wait_seconds=0)
    task = simpleq.task(queue=queue)(tasks.record_sync)

    try:
        await task.delay("visibility")
        messages = await queue.receive(max_messages=1, wait_seconds=0)
        assert len(messages) == 1

        with pytest.raises(
            QueueValidationError,
            match="visibility_timeout must be between 0 and 43200",
        ):
            await queue.change_visibility(messages[0], 43_201)

        await queue.ack(messages[0])
    finally:
        await queue.delete()
