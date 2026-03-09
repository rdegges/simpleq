"""Integration tests for queue and worker behavior against LocalStack."""

from __future__ import annotations

import asyncio
import importlib
import sys
import time

import pytest

from simpleq import SimpleQ
from simpleq.exceptions import QueueValidationError
from simpleq.job import Job
from tests.conftest import eventually
from tests.fixtures import tasks


@pytest.mark.integration
@pytest.mark.asyncio
async def test_standard_queue_round_trip(
    simpleq_localstack, unique_name, cleanup_queues
) -> None:
    queue = simpleq_localstack.queue(
        unique_name("emails"), dlq=True, visibility_timeout=2, wait_seconds=0
    )
    cleanup_queues.append(queue)

    task = simpleq_localstack.task(queue=queue)(tasks.record_async)
    await task.delay("hello")

    worker = simpleq_localstack.worker(queues=[queue], concurrency=1, poll_interval=0.1)
    await worker.work(burst=True)

    assert tasks.LOG == [("async", "hello")]
    stats = await queue.stats()
    assert stats.available_messages == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_exists_reconciles_existing_queue_attributes(
    localstack_endpoint: str,
    unique_name,
    cleanup_queues,
) -> None:
    queue_name = unique_name("reconcile")
    initial_simpleq = SimpleQ(
        endpoint_url=localstack_endpoint,
        wait_seconds=0,
        visibility_timeout=2,
    )
    initial_queue = initial_simpleq.queue(
        queue_name,
        dlq=True,
        wait_seconds=0,
        visibility_timeout=2,
    )
    cleanup_queues.append(initial_queue)
    await initial_queue.ensure_exists()

    updated_simpleq = SimpleQ(
        endpoint_url=localstack_endpoint,
        wait_seconds=4,
        visibility_timeout=7,
    )
    updated_queue = updated_simpleq.queue(
        queue_name,
        dlq=True,
        wait_seconds=4,
        visibility_timeout=7,
    )
    await updated_queue.ensure_exists()

    queue_url = await updated_queue.ensure_exists()
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

    assert attributes["MaximumMessageSize"] == "1048576"
    assert attributes["VisibilityTimeout"] == "7"
    assert attributes["ReceiveMessageWaitTimeSeconds"] == "4"
    assert initial_queue.dlq_name in attributes["RedrivePolicy"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_exists_reconciles_existing_queue_tags(
    localstack_endpoint: str,
    unique_name,
    cleanup_queues,
) -> None:
    queue_name = unique_name("reconcile-tags")
    initial_simpleq = SimpleQ(
        endpoint_url=localstack_endpoint,
        wait_seconds=0,
        visibility_timeout=2,
    )
    initial_queue = initial_simpleq.queue(
        queue_name,
        wait_seconds=0,
        tags={"env": "dev", "owner": "legacy"},
    )
    cleanup_queues.append(initial_queue)
    await initial_queue.ensure_exists()

    updated_simpleq = SimpleQ(
        endpoint_url=localstack_endpoint,
        wait_seconds=0,
        visibility_timeout=2,
    )
    updated_queue = updated_simpleq.queue(
        queue_name,
        wait_seconds=0,
        tags={"env": "prod", "team": "platform"},
    )

    queue_url = await updated_queue.ensure_exists()
    response = await asyncio.to_thread(
        updated_simpleq.transport.client.list_queue_tags,
        QueueUrl=queue_url,
    )

    assert response["Tags"] == {"env": "prod", "team": "platform"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_lazy_import_preserves_schema_metadata(
    localstack_endpoint: str,
    unique_name,
    cleanup_queues,
    tmp_path,
    monkeypatch,
) -> None:
    queue_name = unique_name("lazy-schema")
    module_name = f"simpleq_dynamic_{queue_name.replace('-', '_')}"
    module_path = tmp_path / f"{module_name}.py"
    module_path.write_text(
        "\n".join(
            [
                "from simpleq import SimpleQ",
                "from tests.fixtures.tasks import EmailPayload, LOG",
                "",
                "sq = SimpleQ(wait_seconds=0, visibility_timeout=2)",
                f'queue = sq.queue("{queue_name}", wait_seconds=0)',
                "",
                "@sq.task(queue=queue, schema=EmailPayload, max_retries=2)",
                "async def send_email(payload: EmailPayload) -> str:",
                '    LOG.append(("lazy-schema", payload.subject))',
                "    return payload.subject",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    module = importlib.import_module(module_name)
    cleanup_queues.append(module.queue)

    try:
        await module.send_email.delay(
            to="user@example.com",
            subject="Welcome",
            body="Hello",
        )

        fresh_worker = SimpleQ(
            endpoint_url=localstack_endpoint,
            wait_seconds=0,
            visibility_timeout=2,
        ).worker(queues=[queue_name], concurrency=1, poll_interval=0.1)
        await fresh_worker.work(burst=True)

        assert ("lazy-schema", "Welcome") in tasks.LOG
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_batch_enqueue(simpleq_localstack, unique_name, cleanup_queues) -> None:
    queue = simpleq_localstack.queue(unique_name("batch"), wait_seconds=0)
    cleanup_queues.append(queue)
    await queue.ensure_exists()

    task_name = "tests.fixtures.tasks:record_sync"
    jobs = [
        queue.simpleq.queue(queue.name)  # keep cache warm
        for _ in range(0)
    ]
    del jobs
    entries = [
        queue.__class__.BatchEntry  # type: ignore[attr-defined]
        for _ in range(0)
    ]
    del entries

    from simpleq.job import Job
    from simpleq.queue import BatchEntry

    payloads = [
        BatchEntry(
            Job(
                task_name=task_name,
                args=(f"value-{index}",),
                kwargs={},
                queue_name=queue.name,
            )
        )
        for index in range(3)
    ]
    message_ids = await queue.enqueue_many(payloads)
    assert len(message_ids) == 3

    received = await queue.receive(max_messages=3, wait_seconds=0)
    assert {job.args[0] for job in received} == {"value-0", "value-1", "value-2"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_receive_waits_for_delayed_message_visibility(
    simpleq_localstack, unique_name, cleanup_queues
) -> None:
    queue = simpleq_localstack.queue(unique_name("long-poll"), wait_seconds=0)
    cleanup_queues.append(queue)
    await queue.enqueue(
        Job(
            task_name="tests.fixtures.tasks:record_sync",
            args=("delayed",),
            kwargs={},
            queue_name=queue.name,
        ),
        delay_seconds=1,
    )

    start = time.monotonic()
    received = await queue.receive(max_messages=1, wait_seconds=2)
    elapsed = time.monotonic() - start

    assert [job.args[0] for job in received] == ["delayed"]
    assert elapsed >= 0.8
    await queue.ack(received[0])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_message_attributes_support_values_over_256_kib(
    simpleq_localstack, unique_name, cleanup_queues
) -> None:
    queue = simpleq_localstack.queue(unique_name("large-attrs"), wait_seconds=0)
    cleanup_queues.append(queue)
    large_value = "a" * 300_000
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("attribute-smoke",),
        kwargs={},
        queue_name=queue.name,
    )

    await queue.enqueue(job, attributes={"trace": large_value})
    received = await queue.receive(max_messages=1, wait_seconds=0)

    assert len(received) == 1
    assert received[0].message_attributes["trace"] == large_value
    await queue.ack(received[0])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fifo_ordering(simpleq_localstack, unique_name, cleanup_queues) -> None:
    queue = simpleq_localstack.queue(
        unique_name("orders") + ".fifo",
        fifo=True,
        dlq=True,
        content_based_deduplication=False,
        visibility_timeout=2,
        wait_seconds=0,
    )
    cleanup_queues.append(queue)
    ordered_task = simpleq_localstack.task(
        queue=queue,
        message_group_id=lambda value: "customer-1",
        deduplication_id=lambda value: f"dedup-{value}",
    )(tasks.record_sync)

    for value in ["a", "b", "c"]:
        await ordered_task.delay(value)

    seen = []
    for _ in range(3):
        messages = await queue.receive(max_messages=1, wait_seconds=0)
        assert messages
        seen.append(messages[0].args[0])
        await queue.ack(messages[0])

    assert seen == ["a", "b", "c"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fifo_receive_blocks_later_messages_in_same_group(
    simpleq_localstack, unique_name, cleanup_queues
) -> None:
    queue = simpleq_localstack.queue(
        unique_name("fifo-lock") + ".fifo",
        fifo=True,
        content_based_deduplication=False,
        visibility_timeout=5,
        wait_seconds=0,
    )
    cleanup_queues.append(queue)
    task = simpleq_localstack.task(
        queue=queue,
        message_group_id=lambda _value: "customer-1",
        deduplication_id=lambda value: f"dedup-{value}",
    )(tasks.record_sync)

    await task.delay("first")
    await task.delay("second")

    first_batch = await queue.receive(max_messages=1, wait_seconds=0)
    assert [job.args[0] for job in first_batch] == ["first"]

    blocked_batch = await queue.receive(max_messages=1, wait_seconds=0)
    assert blocked_batch == []

    await queue.ack(first_batch[0])

    second_batch = await queue.receive(max_messages=1, wait_seconds=0)
    assert [job.args[0] for job in second_batch] == ["second"]
    await queue.ack(second_batch[0])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_standard_delay(simpleq_localstack, unique_name, cleanup_queues) -> None:
    queue = simpleq_localstack.queue(unique_name("delayed"), wait_seconds=0)
    cleanup_queues.append(queue)
    delayed_task = simpleq_localstack.task(queue=queue)(tasks.record_sync)
    await delayed_task.delay("later", delay_seconds=1)

    assert await queue.receive(max_messages=1, wait_seconds=0) == []

    await eventually(
        lambda: _message_visible(queue),
        timeout=5.0,
        interval=0.2,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_change_visibility_rejects_invalid_timeout(
    simpleq_localstack, unique_name, cleanup_queues
) -> None:
    queue = simpleq_localstack.queue(unique_name("visibility"), wait_seconds=0)
    cleanup_queues.append(queue)
    task = simpleq_localstack.task(queue=queue)(tasks.record_sync)
    await task.delay("value")

    messages = await queue.receive(max_messages=1, wait_seconds=0)
    assert len(messages) == 1

    with pytest.raises(
        QueueValidationError,
        match="visibility_timeout must be between 0 and 43200",
    ):
        await queue.change_visibility(messages[0], 43_201)

    # The message remains acknowledged normally after the rejected timeout.
    await queue.ack(messages[0])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_then_success(
    simpleq_localstack, unique_name, cleanup_queues
) -> None:
    queue = simpleq_localstack.queue(
        unique_name("retry"), dlq=True, visibility_timeout=1, wait_seconds=0
    )
    cleanup_queues.append(queue)
    flaky = simpleq_localstack.task(queue=queue, retry_exceptions=[RuntimeError])(
        tasks.fail_once
    )
    await flaky.delay("job-1")

    worker = simpleq_localstack.worker(queues=[queue], concurrency=1, poll_interval=0.1)
    await worker.work(burst=True)
    await eventually(lambda: _message_visible(queue), timeout=5.0, interval=0.2)
    await worker.work(burst=True)

    assert ("retry-success", "job-1") in tasks.LOG


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_moves_unresolvable_task_to_dlq(
    simpleq_localstack, unique_name, cleanup_queues
) -> None:
    queue = simpleq_localstack.queue(
        unique_name("missing-task"), dlq=True, visibility_timeout=1, wait_seconds=0
    )
    cleanup_queues.append(queue)
    await queue.enqueue(
        Job(
            task_name="simpleq.no_such_module:no_such_task",
            args=("payload",),
            kwargs={},
            queue_name=queue.name,
        )
    )

    worker = simpleq_localstack.worker(queues=[queue], concurrency=1, poll_interval=0.1)
    await worker.work(burst=True)
    await eventually(lambda: _dlq_has_messages(queue), timeout=5.0, interval=0.2)

    dlq_jobs = [job async for job in queue.get_dlq_jobs(limit=1)]
    assert len(dlq_jobs) == 1
    assert dlq_jobs[0].task_name == "simpleq.no_such_module:no_such_task"
    assert "task-definition-resolution-failed" in str(
        dlq_jobs[0].metadata.get("last_error")
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dlq_and_redrive(simpleq_localstack, unique_name, cleanup_queues) -> None:
    queue = simpleq_localstack.queue(
        unique_name("dlq"), dlq=True, visibility_timeout=1, wait_seconds=0
    )
    cleanup_queues.append(queue)
    failing = simpleq_localstack.task(queue=queue, max_retries=2)(tasks.always_fail)
    await failing.delay("job-2")

    worker = simpleq_localstack.worker(queues=[queue], concurrency=1, poll_interval=0.1)
    await worker.work(burst=True)
    await eventually(lambda: _message_visible(queue), timeout=5.0, interval=0.2)
    await worker.work(burst=True)
    await eventually(lambda: _dlq_has_messages(queue), timeout=5.0, interval=0.2)

    stats = await queue.stats()
    assert stats.dlq_available_messages == 1
    assert stats.dlq_in_flight_messages == 0
    assert stats.dlq_delayed_messages == 0

    dlq_jobs = [job async for job in queue.get_dlq_jobs(limit=5)]
    assert len(dlq_jobs) == 1
    assert dlq_jobs[0].metadata["last_error"] == "failure-job-2"

    redriven = await queue.redrive_dlq_jobs()
    assert redriven == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fifo_dlq_and_redrive(simpleq_localstack, unique_name, cleanup_queues) -> None:
    queue = simpleq_localstack.queue(
        unique_name("fifo-dlq") + ".fifo",
        fifo=True,
        dlq=True,
        content_based_deduplication=False,
        visibility_timeout=1,
        wait_seconds=0,
    )
    cleanup_queues.append(queue)
    failing = simpleq_localstack.task(
        queue=queue,
        message_group_id=lambda value: "customer-1",
        deduplication_id=lambda value: f"dedup-{value}",
        max_retries=1,
    )(tasks.always_fail)

    await failing.delay("order-1")

    worker = simpleq_localstack.worker(queues=[queue], concurrency=1, poll_interval=0.1)
    await worker.work(burst=True)
    await eventually(lambda: _dlq_has_messages(queue), timeout=5.0, interval=0.2)

    dlq_jobs = [job async for job in queue.get_dlq_jobs(limit=5)]
    assert len(dlq_jobs) == 1
    assert dlq_jobs[0].args == ("order-1",)

    redriven = await queue.redrive_dlq_jobs(limit=1)
    assert redriven == 1

    await eventually(lambda: _message_visible(queue), timeout=5.0, interval=0.2)
    received = await queue.receive(max_messages=1, wait_seconds=0)
    assert len(received) == 1
    assert received[0].args == ("order-1",)
    await queue.ack(received[0])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_visibility_heartbeat(
    simpleq_localstack, unique_name, cleanup_queues
) -> None:
    queue = simpleq_localstack.queue(
        unique_name("heartbeat"), visibility_timeout=1, wait_seconds=0
    )
    cleanup_queues.append(queue)
    sleeper = simpleq_localstack.task(queue=queue)(tasks.sleep_and_record)
    await sleeper.delay("slow")

    worker = simpleq_localstack.worker(queues=[queue], concurrency=1, poll_interval=0.1)
    await worker.work(burst=True)

    assert ("slept", "slow") in tasks.LOG
    stats = await queue.stats()
    assert stats.available_messages == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cli_queue_flow(
    simpleq_localstack, unique_name, cleanup_queues, monkeypatch
) -> None:
    from typer.testing import CliRunner

    from simpleq.cli import app

    queue = simpleq_localstack.queue(unique_name("cli"), wait_seconds=0)
    cleanup_queues.append(queue)
    monkeypatch.setattr("simpleq.cli.make_client", lambda **_: simpleq_localstack)

    runner = CliRunner()
    result = await asyncio.to_thread(
        runner.invoke, app, ["queue", "create", queue.name]
    )
    assert result.exit_code == 0

    stats = await asyncio.to_thread(runner.invoke, app, ["queue", "stats", queue.name])
    assert stats.exit_code == 0
    assert queue.name in stats.stdout


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cli_worker_reuses_imported_queue_configuration(
    localstack_endpoint: str,
    simpleq_localstack,
    unique_name,
    cleanup_queues,
    tmp_path,
    monkeypatch,
) -> None:
    from simpleq.cli import job_enqueue, worker_start

    queue_name = unique_name("cli-worker")
    queue = simpleq_localstack.queue(
        queue_name,
        dlq=True,
        visibility_timeout=1,
        wait_seconds=0,
    )
    cleanup_queues.append(queue)

    module_name = f"simpleq_dynamic_{queue_name.replace('-', '_')}"
    module_path = tmp_path / f"{module_name}.py"
    module_path.write_text(
        "\n".join(
            [
                "from simpleq import SimpleQ",
                "",
                "sq = SimpleQ()",
                f'queue = sq.queue("{queue_name}", dlq=True, wait_seconds=0, visibility_timeout=1)',
                "",
                "@sq.task(queue=queue, max_retries=1)",
                "def explode(value: str) -> None:",
                '    raise RuntimeError(f"explode-{value}")',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        await asyncio.to_thread(
            lambda: job_enqueue(
                f"{module_name}:explode",
                imports=[module_name],
                payload_json='["boom"]',
                endpoint_url=localstack_endpoint,
            )
        )
        await asyncio.to_thread(
            lambda: worker_start(
                queues=[queue_name],
                imports=[module_name],
                concurrency=1,
                burst=True,
                endpoint_url=localstack_endpoint,
            )
        )
        await eventually(lambda: _dlq_has_messages(queue), timeout=5.0, interval=0.2)
    finally:
        sys.modules.pop(module_name, None)


async def _message_visible(queue) -> bool:
    stats = await queue.stats()
    return stats.available_messages == 1


async def _dlq_has_messages(queue) -> bool:
    dlq_queue = queue.simpleq.queue(
        queue.dlq_name,
        fifo=queue.fifo,
        dlq=False,
        content_based_deduplication=queue.content_based_deduplication,
        max_retries=queue.max_retries,
        visibility_timeout=queue.visibility_timeout,
        wait_seconds=queue.wait_seconds,
        tags=dict(queue.tags),
    )
    stats = await dlq_queue.stats()
    return stats.available_messages == 1
