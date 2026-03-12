"""Optional real-AWS smoke tests."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from simpleq import SimpleQ
from simpleq.exceptions import QueueValidationError
from simpleq.job import Job
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


def _skip_if_missing_tag_permissions(exc: ClientError) -> None:
    error = exc.response.get("Error", {})
    if error.get("Code") != "AccessDenied":
        return
    message = str(error.get("Message", "")).lower()
    required_actions = ("sqs:tagqueue", "sqs:untagqueue", "sqs:listqueuetags")
    if any(action in message for action in required_actions):
        pytest.skip(
            "Live AWS principal is missing SQS tag permissions required for "
            "queue tag reconciliation. Update the IAM policy in "
            "tests/live/iam-policy.json to run this smoke test."
        )


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
async def test_live_list_queues_returns_sorted_unique_names_for_prefix() -> None:
    _load_dotenv(Path(".env"))
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing live AWS credentials: {', '.join(missing)}")

    prefix = f"simpleq-live-list-{uuid4().hex[:8]}-"
    queue_a_name = f"{prefix}zeta"
    queue_b_name = f"{prefix}alpha"
    simpleq = _live_simpleq(wait_seconds=0, visibility_timeout=2)
    queue_a = simpleq.queue(queue_a_name)
    queue_b = simpleq.queue(queue_b_name)

    try:
        await queue_a.ensure_exists()
        await queue_b.ensure_exists()

        queue_names = await simpleq.list_queues(prefix)

        assert queue_names == sorted(set(queue_names))
        assert queue_a_name in queue_names
        assert queue_b_name in queue_names
    finally:
        await queue_a.delete()
        await queue_b.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_existing_queue_attributes_and_tags_are_reconciled() -> None:
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
        tags={"env": "dev", "owner": "legacy"},
    )
    try:
        await initial_queue.ensure_exists()
    except ClientError as exc:
        _skip_if_missing_tag_permissions(exc)
        raise

    updated_simpleq = _live_simpleq(wait_seconds=5, visibility_timeout=9)
    updated_queue = updated_simpleq.queue(
        queue_name,
        dlq=True,
        wait_seconds=5,
        visibility_timeout=9,
        tags={"env": "prod", "team": "platform"},
    )

    try:
        try:
            queue_url = await updated_queue.ensure_exists()
        except ClientError as exc:
            _skip_if_missing_tag_permissions(exc)
            raise
        attributes = await updated_simpleq.transport.get_queue_attributes(
            updated_queue.name,
            queue_url,
            [
                "MaximumMessageSize",
                "VisibilityTimeout",
                "ReceiveMessageWaitTimeSeconds",
                "RedrivePolicy",
            ],
        )

        redrive_policy = json.loads(attributes["RedrivePolicy"])
        assert attributes["MaximumMessageSize"] == "1048576"
        assert attributes["VisibilityTimeout"] == "9"
        assert attributes["ReceiveMessageWaitTimeSeconds"] == "5"
        assert initial_queue.dlq_name in redrive_policy["deadLetterTargetArn"]
        try:
            tags = await asyncio.to_thread(
                updated_simpleq.transport.client.list_queue_tags,
                QueueUrl=queue_url,
            )
        except ClientError as exc:
            _skip_if_missing_tag_permissions(exc)
            raise
        assert tags["Tags"] == {"env": "prod", "team": "platform"}
    finally:
        await updated_queue.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_message_attributes_support_values_over_256_characters() -> None:
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
    queue = simpleq.queue(f"simpleq-live-attrs-{uuid4().hex[:8]}", wait_seconds=0)
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("attribute-smoke",),
        kwargs={},
        queue_name=queue.name,
    )
    large_value = "a" * 2048

    try:
        await queue.enqueue(job, attributes={"trace": large_value})
        received = await queue.receive(max_messages=1, wait_seconds=0)
        assert len(received) == 1
        assert received[0].message_attributes["trace"] == large_value
        await queue.ack(received[0])
    finally:
        await queue.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_delete_recovers_from_stale_cached_queue_url() -> None:
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
    queue = simpleq.queue(
        f"simpleq-live-stale-delete-{uuid4().hex[:8]}",
        wait_seconds=0,
    )

    queue_url = await queue.ensure_exists()
    await asyncio.to_thread(simpleq.transport.client.delete_queue, QueueUrl=queue_url)

    await queue.delete()
    simpleq.transport.invalidate_queue_url(queue.name)

    for _ in range(20):
        if await simpleq.transport.get_queue_url(queue.name) is None:
            break
        await asyncio.sleep(0.2)
    else:
        raise AssertionError("Queue still exists after stale-cache delete recovery.")


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_message_attributes_support_values_over_256_kib() -> None:
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
    queue = simpleq.queue(
        f"simpleq-live-large-attrs-{uuid4().hex[:8]}",
        wait_seconds=0,
    )
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("attribute-large-smoke",),
        kwargs={},
        queue_name=queue.name,
    )
    large_value = "a" * 300_000

    try:
        await queue.enqueue(job, attributes={"trace": large_value})
        received = await queue.receive(max_messages=1, wait_seconds=0)
        assert len(received) == 1
        assert received[0].message_attributes["trace"] == large_value
        await queue.ack(received[0])
    finally:
        await queue.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_receive_waits_for_delayed_message_visibility() -> None:
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
    queue = simpleq.queue(f"simpleq-live-long-poll-{uuid4().hex[:8]}", wait_seconds=0)
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("delayed",),
        kwargs={},
        queue_name=queue.name,
    )

    try:
        await queue.enqueue(job, delay_seconds=1)

        start = time.monotonic()
        received = await queue.receive(max_messages=1, wait_seconds=2)
        elapsed = time.monotonic() - start

        assert [item.args[0] for item in received] == ["delayed"]
        assert elapsed >= 0.8
        await queue.ack(received[0])
    finally:
        await queue.delete()


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

        stats = await queue.stats()
        assert stats.dlq_available_messages == 1
        assert stats.dlq_in_flight_messages == 0
        assert stats.dlq_delayed_messages == 0

        dlq_jobs = [job async for job in queue.get_dlq_jobs(limit=5)]
        assert len(dlq_jobs) == 1
        assert dlq_jobs[0].args == ("order-1",)
        assert dlq_jobs[0].metadata["message_group_id"] == "customer-1"
        assert dlq_jobs[0].metadata["_simpleq_message_group_id"] == "customer-1"
        assert dlq_jobs[0].metadata["deduplication_id"] != "dedup-order-1"
        assert dlq_jobs[0].metadata["_simpleq_deduplication_id"] != "dedup-order-1"

        redriven = await queue.redrive_dlq_jobs(limit=1)
        assert redriven == 1

        for _ in range(25):
            received = await queue.receive(max_messages=1, wait_seconds=0)
            if received:
                assert received[0].args == ("order-1",)
                assert received[0].metadata["message_group_id"] == "customer-1"
                assert received[0].metadata["_simpleq_message_group_id"] == "customer-1"
                assert received[0].metadata["deduplication_id"] not in {
                    "dedup-order-1",
                    dlq_jobs[0].metadata["deduplication_id"],
                }
                assert received[0].metadata["_simpleq_deduplication_id"] not in {
                    "dedup-order-1",
                    dlq_jobs[0].metadata["_simpleq_deduplication_id"],
                }
                await queue.ack(received[0])
                break
        else:
            raise AssertionError("Redriven FIFO message did not become visible.")
    finally:
        await queue.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fifo_content_based_dlq_redrive_smoke() -> None:
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
        f"simpleq-live-fifo-content-dlq-{uuid4().hex[:8]}.fifo",
        fifo=True,
        dlq=True,
        content_based_deduplication=True,
        wait_seconds=0,
        visibility_timeout=1,
    )
    failing = simpleq.task(
        queue=queue,
        message_group_id=lambda value: "customer-1",
        max_retries=1,
    )(tasks.always_fail)

    try:
        await failing.delay("order-1")
        worker = simpleq.worker(queues=[queue], concurrency=1, poll_interval=0.1)
        await worker.work(burst=True)

        for _ in range(25):
            stats = await queue.stats()
            if stats.dlq_available_messages and stats.dlq_available_messages >= 1:
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError(
                "FIFO content-based DLQ message did not become visible."
            )

        dlq_jobs = [job async for job in queue.get_dlq_jobs(limit=5)]
        assert len(dlq_jobs) == 1
        assert dlq_jobs[0].args == ("order-1",)

        redriven = await queue.redrive_dlq_jobs(limit=1)
        assert redriven == 1

        for _ in range(25):
            received = await queue.receive(max_messages=1, wait_seconds=0)
            if received:
                assert received[0].args == ("order-1",)
                assert received[0].metadata["deduplication_id"] not in {
                    dlq_jobs[0].metadata["deduplication_id"],
                    dlq_jobs[0].metadata["_simpleq_deduplication_id"],
                }
                assert received[0].metadata["_simpleq_deduplication_id"] not in {
                    dlq_jobs[0].metadata["deduplication_id"],
                    dlq_jobs[0].metadata["_simpleq_deduplication_id"],
                }
                await queue.ack(received[0])
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError(
                "Redriven FIFO content-based message did not become visible."
            )
    finally:
        await queue.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fifo_receive_blocks_later_messages_in_same_group() -> None:
    _load_dotenv(Path(".env"))
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing live AWS credentials: {', '.join(missing)}")

    simpleq = _live_simpleq(wait_seconds=0, visibility_timeout=5)
    queue = simpleq.queue(
        f"simpleq-live-fifo-lock-{uuid4().hex[:8]}.fifo",
        fifo=True,
        content_based_deduplication=False,
        wait_seconds=0,
        visibility_timeout=5,
    )
    task = simpleq.task(
        queue=queue,
        message_group_id=lambda _value: "customer-1",
        deduplication_id=lambda value: f"dedup-{value}",
    )(tasks.record_sync)

    try:
        await task.delay("first")
        await task.delay("second")

        first_batch = await queue.receive(max_messages=1, wait_seconds=0)
        assert [job.args[0] for job in first_batch] == ["first"]

        blocked_batch = await queue.receive(max_messages=1, wait_seconds=0)
        assert blocked_batch == []

        await queue.ack(first_batch[0])

        for _ in range(25):
            second_batch = await queue.receive(max_messages=1, wait_seconds=0)
            if second_batch:
                assert [job.args[0] for job in second_batch] == ["second"]
                await queue.ack(second_batch[0])
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("Second FIFO message did not become available.")
    finally:
        await queue.delete()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_unresolvable_task_moves_to_dlq() -> None:
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
    queue = simpleq.queue(f"simpleq-live-missing-task-{uuid4().hex[:8]}", dlq=True)
    try:
        await queue.enqueue(
            Job(
                task_name="simpleq.no_such_module:no_such_task",
                args=("payload",),
                kwargs={},
                queue_name=queue.name,
            )
        )
        worker = simpleq.worker(queues=[queue], concurrency=1, poll_interval=0.1)
        await worker.work(burst=True)

        for _ in range(25):
            dlq_jobs = [job async for job in queue.get_dlq_jobs(limit=1)]
            if dlq_jobs:
                assert dlq_jobs[0].task_name == "simpleq.no_such_module:no_such_task"
                assert "task-definition-resolution-failed" in str(
                    dlq_jobs[0].metadata.get("last_error")
                )
                break
        else:
            raise AssertionError("Missing-task message did not arrive in DLQ.")
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
